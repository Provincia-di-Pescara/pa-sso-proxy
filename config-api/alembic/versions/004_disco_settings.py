"""add disco page settings columns

Revision ID: 004
Revises: 003
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns("ente_settings")
    for col in ["logo_url", "privacy_url", "legal_notes_url", "accessibility_url", "support_url"]:
        if col not in existing:
            op.add_column("ente_settings", sa.Column(col, sa.Text(), nullable=True, server_default=""))


def downgrade() -> None:
    existing = _existing_columns("ente_settings")
    for col in ["logo_url", "privacy_url", "legal_notes_url", "accessibility_url", "support_url"]:
        if col in existing:
            op.drop_column("ente_settings", col)
