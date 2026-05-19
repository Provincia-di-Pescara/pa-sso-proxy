from datetime import datetime
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class JwkKey(Base):
    __tablename__ = "jwk_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    use: Mapped[str] = mapped_column(String(16), nullable=False)  # federation | sig | enc
    private_jwk: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_jwk: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
