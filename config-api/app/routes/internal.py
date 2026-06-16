import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AccessLog

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
