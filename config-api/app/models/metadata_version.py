from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SpidMetadataVersion(Base):
    __tablename__ = "spid_metadata_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # "generated" | "uploaded"
    xml_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("spid_cert.id", ondelete="SET NULL"), nullable=True)
    is_exposed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
