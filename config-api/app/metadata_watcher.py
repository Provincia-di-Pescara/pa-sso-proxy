import asyncio
import hashlib
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

logger = logging.getLogger(__name__)


async def fetch_idp_metadata(db: AsyncSession, idp: SpidIdP) -> bool:
    """Fetch metadata XML for one IdP. Returns True if content changed and DB was updated."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(idp.metadata_url)
        resp.raise_for_status()
    content = resp.text
    new_hash = hashlib.sha256(content.encode()).hexdigest()
    if new_hash == idp.metadata_hash:
        return False
    idp.metadata_cache = content
    idp.metadata_hash = new_hash
    idp.last_updated = datetime.now(timezone.utc)
    await db.commit()
    return True


async def fetch_all_enabled(db: AsyncSession) -> int:
    """Fetch metadata for all enabled IdPs. Calls generate+reload if any updated. Returns update count."""
    result = await db.execute(select(SpidIdP).where(SpidIdP.enabled == True))
    idps = result.scalars().all()
    updated = 0
    for idp in idps:
        try:
            if await fetch_idp_metadata(db, idp):
                updated += 1
        except Exception as exc:
            logger.warning("Metadata fetch failed for %s: %s", idp.alias, exc)
    if updated > 0:
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    return updated


async def run_metadata_watcher() -> None:
    """Scheduler entry point. Creates its own DB session."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        count = await fetch_all_enabled(session)
        logger.info("Metadata watcher: %d IdP aggiornati", count)
