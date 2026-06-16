import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa
from app.spid_seeder import sync_spid_idps_from_registry

logger = logging.getLogger(__name__)

SPID_AGGREGATE_URL = "https://registry.spid.gov.it/metadata/idp/spid-entities-idps.xml"
_SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")
SPID_AGGREGATE_PATH = os.path.join(_SATOSA_CONF_DIR, "spid-entities-idps.xml")
_AGGREGATE_HASH_PATH = os.path.join(_SATOSA_CONF_DIR, ".spid-aggregate-hash")


async def fetch_spid_aggregate() -> bool:
    """Download SPID aggregate metadata XML. Returns True if content changed and file was written."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(SPID_AGGREGATE_URL)
        resp.raise_for_status()
    content = resp.content
    new_hash = hashlib.sha256(content).hexdigest()
    old_hash = Path(_AGGREGATE_HASH_PATH).read_text().strip() if Path(_AGGREGATE_HASH_PATH).exists() else ""
    if new_hash == old_hash:
        return False
    Path(SPID_AGGREGATE_PATH).write_bytes(content)
    Path(_AGGREGATE_HASH_PATH).write_text(new_hash)
    logger.info("SPID aggregate metadata updated (hash %s)", new_hash[:12])
    return True


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

    aggregate_updated = False
    try:
        aggregate_updated = await fetch_spid_aggregate()
    except Exception as exc:
        logger.warning("SPID aggregate download failed: %s", exc)

    async with AsyncSessionLocal() as session:
        try:
            inserted = await sync_spid_idps_from_registry(session)
            logger.info("SPID registry sync: %d nuovi IdP inseriti", inserted)
        except Exception as exc:
            logger.warning("SPID registry sync failed: %s", exc)
        count = await fetch_all_enabled(session)
        if aggregate_updated and count == 0:
            await generate_and_write(session)
            await asyncio.to_thread(reload_satosa)
            logger.info("SATOSA reloaded after aggregate metadata update")
        logger.info("Metadata watcher: %d IdP aggiornati", count)
