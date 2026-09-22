from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SpidCert(Base):
    __tablename__ = "spid_cert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    certificate_pem: Mapped[str] = mapped_column(Text, nullable=False)
    private_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    not_valid_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subject_dn: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
