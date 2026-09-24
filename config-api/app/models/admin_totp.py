from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AdminTotp(Base):
    """Secret TOTP dell'admin WebUI (singleton, id=1).

    confirmed_at NULL = enrollment in corso: la riga non è ancora valida per il login.
    """

    __tablename__ = "admin_totp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # sempre 1
    secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_counter: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
