"""add vat_number to ente_settings

Revision ID: 009
Revises: 008
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("ente_settings", "vat_number"):
        op.add_column(
            "ente_settings",
            sa.Column("vat_number", sa.String(32), nullable=False, server_default=""),
        )


def downgrade() -> None:
    if _has_column("ente_settings", "vat_number"):
        op.drop_column("ente_settings", "vat_number")
