from typing import Optional
from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class CieConfig(Base):
    __tablename__ = "cie_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # sempre 1
    saml_metadata_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
    )
    entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oidc_federation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jwk_federation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
    jwk_core_sig_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
    jwk_core_enc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
