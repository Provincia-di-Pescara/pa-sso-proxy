"""create access_stats_monthly table for permanent statistical aggregates

Revision ID: 011
Revises: 010
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table in inspector.get_table_names()


def upgrade() -> None:
    if not _table_exists("access_stats_monthly"):
        op.create_table(
            "access_stats_monthly",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("month", sa.Integer(), nullable=False),
            sa.Column("idp_entity_id", sa.Text(), nullable=True),
            sa.Column("provider_type", sa.String(16), nullable=False),
            sa.Column("user_type", sa.String(16), nullable=True),
            sa.Column("client_id", sa.String(128), nullable=True),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.UniqueConstraint(
                "year", "month", "idp_entity_id", "provider_type", "user_type", "client_id",
                name="uq_access_stats_monthly"
            ),
        )
        op.create_index("ix_access_stats_monthly_year_month", "access_stats_monthly", ["year", "month"])


def downgrade() -> None:
    if _table_exists("access_stats_monthly"):
        op.drop_index("ix_access_stats_monthly_year_month", table_name="access_stats_monthly")
        op.drop_table("access_stats_monthly")
