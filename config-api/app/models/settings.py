from typing import Optional
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class EnteSettings(Base):
    __tablename__ = "ente_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # sempre 1
    org_display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    org_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    org_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ipa_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    contact_email: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    org_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    proxy_hostname: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    logo_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    favicon_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    privacy_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    legal_notes_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    accessibility_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    support_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
