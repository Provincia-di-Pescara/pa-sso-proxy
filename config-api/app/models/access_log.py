from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AccessLog(Base):
    __tablename__ = "access_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    provider_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    idp_entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    fiscal_number_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
