import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metadata_profile import latest_generated_version, metadata_fingerprint
from app.models import AccessLog, EnteSettings, SpidCert, SpidMetadataVersion

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
    # Inviato da satosa (hash del testo prima della firma): ignorato. Dipendeva
    # dai prefissi XML scelti da pysaml2, che con 7.5.5 sono cambiati a contenuto
    # identico. L'impronta la calcola config-api (metadata_fingerprint).
    semantic_hash: Optional[str] = None


@router.post("/internal/spid-metadata-snapshot")
async def log_metadata_snapshot(entry: MetadataSnapshotEntry, db: AsyncSession = Depends(get_db)):
    try:
        content_hash = metadata_fingerprint(entry.xml_content)
        last_row = await latest_generated_version(db)
        if last_row is None or last_row.content_hash != content_hash:
            cert_result = await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))
            cert = cert_result.scalar_one_or_none()
            settings_result = await db.execute(select(EnteSettings).limit(1))
            settings = settings_result.scalar_one_or_none()
            db.add(SpidMetadataVersion(
                source="generated",
                xml_content=entry.xml_content,
                content_hash=content_hash,
                cert_id=cert.id if cert else None,
                is_exposed=False,
                # Toggle live al momento della generazione: solo informativi
                # (il ripristino passa dal profilo validato, metadata_profile.py).
                eidas_enabled=getattr(settings, "eidas_enabled", None),
                eidas_environment=getattr(settings, "eidas_environment", None),
                legal_entity_enabled=getattr(settings, "legal_entity_enabled", None),
            ))
            await db.commit()
    except Exception:
        logger.error("Failed to save metadata snapshot", exc_info=True)
    return {"ok": True}
