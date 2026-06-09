"""add favicon_url to ente_settings

Revision ID: 005
Revises: 004
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    if "favicon_url" not in _existing_columns("ente_settings"):
        op.add_column("ente_settings", sa.Column("favicon_url", sa.Text(), nullable=True, server_default=""))


def downgrade() -> None:
    if "favicon_url" in _existing_columns("ente_settings"):
        op.drop_column("ente_settings", "favicon_url")
