from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SpidIdP(Base):
    __tablename__ = "spid_idps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    metadata_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_cache: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    registry_entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    registry_logo_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    registry_organization_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    registry_lastupdate_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    registry_disabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    registry_payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    registry_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
