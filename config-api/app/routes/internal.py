import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AccessLog, SpidCert, SpidMetadataVersion

logger = logging.getLogger(__name__)
router = APIRouter()


class AccessLogEntry(BaseModel):
    provider_type: str
    client_id: Optional[str] = None
    result: str
    error_code: Optional[str] = None
    user_type: Optional[str] = None
    idp_entity_id: Optional[str] = None
    fiscal_number_hash: Optional[str] = None


@router.post("/internal/access-log")
async def log_access(entry: AccessLogEntry, db: AsyncSession = Depends(get_db)):
    try:
        record = AccessLog(
            provider_type=entry.provider_type[:16],
            client_id=entry.client_id,
            result=entry.result[:16],
            error_code=entry.error_code,
            user_type=entry.user_type,
            idp_entity_id=entry.idp_entity_id,
            fiscal_number_hash=entry.fiscal_number_hash,
        )
        db.add(record)
        await db.commit()
    except Exception:
        logger.error("Failed to save access log entry", exc_info=True)
    return {"ok": True}


class MetadataSnapshotEntry(BaseModel):
    xml_content: str
    # Hash del contenuto PRIMA della firma (deterministico a parità di cert+config).
    # pysaml2 firma con un ID XML casuale ad ogni chiamata (sid()), quindi l'hash
    # del documento FIRMATO cambia sempre anche a configurazione identica — usarlo
    # per il dedup produrrebbe una riga nuova ad ogni singolo reload SATOSA (inclusi
    # quelli del cron di sync registry IdP, che non toccano affatto il metadata SP).
    # Fallback al hash del contenuto firmato solo per compatibilità con un satosa
    # image più vecchio durante un rolling deploy.
    semantic_hash: Optional[str] = None


@router.post("/internal/spid-metadata-snapshot")
async def log_metadata_snapshot(entry: MetadataSnapshotEntry, db: AsyncSession = Depends(get_db)):
    try:
        content_hash = entry.semantic_hash or hashlib.sha256(entry.xml_content.encode("utf-8")).hexdigest()
        last_result = await db.execute(
            select(SpidMetadataVersion)
            .where(SpidMetadataVersion.source == "generated")
            .order_by(SpidMetadataVersion.created_at.desc())
            .limit(1)
        )
        last_row = last_result.scalar_one_or_none()
        if last_row is None or last_row.content_hash != content_hash:
            cert_result = await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))
            cert = cert_result.scalar_one_or_none()
            # `last_row` being currently exposed means SATOSA is serving it as the
            # live/dynamic metadata (no override file pinning an older version —
            # pinning an older version would have left is_exposed=False on
            # last_row, see metadata.py's expose route). Since the new snapshot
            # is now what SATOSA actually serves live, the exposed flag must
            # follow it, or the "Esposto" badge in the UI would lie.
            was_live_exposed = last_row is not None and last_row.is_exposed is True
            row = SpidMetadataVersion(
                source="generated",
                xml_content=entry.xml_content,
                content_hash=content_hash,
                cert_id=cert.id if cert else None,
                is_exposed=last_row is None or was_live_exposed,
            )
            db.add(row)
            try:
                await db.commit()
            except IntegrityError:
                # Race between uWSGI workers: another worker already inserted a
                # row with this (source, content_hash) between our read and our
                # insert. Nothing to do — the row exists, fire-and-forget.
                await db.rollback()
                logger.info(
                    "Metadata snapshot with hash %s already inserted by a concurrent worker; skipping",
                    content_hash,
                )
            else:
                if was_live_exposed:
                    last_row.is_exposed = False
                    await db.commit()
    except Exception:
        logger.error("Failed to save metadata snapshot", exc_info=True)
    return {"ok": True}
