from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SpidMetadataProfile(Base):
    """Configurazione che determina il metadata SP, fotografata quando AgID la valida.

    Il profilo sono i PARAMETRI (certificato, dati ente/contatti, toggle), non il
    documento: "Ripristina" li riapplica e SATOSA rigenera un metadata equivalente.
    `content_hash` è l'impronta del metadata generato con questi parametri (vedi
    app/metadata_profile.py), per accorgersi se una nuova immagine lo cambia.
    """

    __tablename__ = "spid_metadata_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    label: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    # "validated" (al più uno, applicativo) | "archived"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="validated")

    # cert_id può sparire (cert eliminato, backup che esporta solo il cert attivo):
    # cert_fingerprint resta per il confronto.
    cert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("spid_cert.id", ondelete="SET NULL"), nullable=True)
    cert_fingerprint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    org_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    org_display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    org_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contact_email: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    vat_number: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    ipa_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    eidas_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eidas_environment: Mapped[str] = mapped_column(String(16), nullable=False, default="prod")
    legal_entity_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Solo confronto: deriva da PROXY_HOSTNAME/PROXY_BASE_URL, non ripristinabile.
    entity_id: Mapped[str] = mapped_column(Text, nullable=False, default="")

    metadata_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("spid_metadata_version.id", ondelete="SET NULL"), nullable=True
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
