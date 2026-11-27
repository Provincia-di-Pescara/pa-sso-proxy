from typing import Optional
from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class ItWalletConfig(Base):
    __tablename__ = "itwallet_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # sempre 1
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    environment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # collaudo | produzione | personalizzato
    trust_anchor_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    authority_hint_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trust_anchor_jwks: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    jwk_federation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
    jwk_sig_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
    jwk_enc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
    organization_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    homepage_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    policy_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tos_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logo_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trust_mark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trust_mark_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
