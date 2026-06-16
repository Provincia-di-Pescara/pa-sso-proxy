from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AccessStatsMonthly(Base):
    __tablename__ = "access_stats_monthly"
    __table_args__ = (
        UniqueConstraint(
            "year", "month", "idp_entity_id", "provider_type", "user_type", "client_id",
            name="uq_access_stats_monthly"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    idp_entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_type: Mapped[str] = mapped_column(String(16), nullable=False)
    user_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
