"""add CIE OIDC environment column

Revision ID: 003
Revises: 002
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns("cie_config")
    if "oidc_environment" not in existing:
        op.add_column("cie_config", sa.Column("oidc_environment", sa.Text(), nullable=True))


def downgrade() -> None:
    existing = _existing_columns("cie_config")
    if "oidc_environment" in existing:
        op.drop_column("cie_config", "oidc_environment")
