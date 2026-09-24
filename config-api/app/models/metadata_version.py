from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SpidMetadataVersion(Base):
    __tablename__ = "spid_metadata_version"
    # NIENTE UniqueConstraint globale su (source, content_hash): con l'hash
    # semantico (pre-firma) il contenuto può legittimamente ripetersi nel
    # tempo (ciclo toggle-on -> toggle-off -> toggle-on riporta lo stesso
    # hash di una riga VECCHIA, non solo dell'ultima). Un vincolo globale
    # bloccava silenziosamente quell'insert (IntegrityError scambiata per
    # "race tra 2 worker già gestita"), lasciando is_exposed su una riga
    # che SATOSA non serve più davvero. Il dedup "niente rumore" resta
    # gestito a livello applicativo confrontando solo con l'ultima riga
    # (vedi internal.py log_metadata_snapshot).

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # "generated" | "uploaded"
    xml_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("spid_cert.id", ondelete="SET NULL"), nullable=True)
    is_exposed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Snapshot delle impostazioni EnteSettings che determinano il comportamento
    # RUNTIME del backend spidsaml2 (ficep_enable/legal_entity_enable in
    # satosa_config_generator.py) — indipendenti dal documento metadata stesso.
    # "Esponi" ripristina solo il documento pubblicato, mai questi toggle: senza
    # questo snapshot un admin potrebbe esporre un vecchio metadata (senza ACS
    # eIDAS) mentre il backend ha ancora ficep_enable=true attivo, causando uno
    # stato pubblicato/comportamento incoerente. NULL per righe storiche
    # precedenti a questa colonna (nessun confronto possibile, nessun warning).
    eidas_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    eidas_environment: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    legal_entity_enabled: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
