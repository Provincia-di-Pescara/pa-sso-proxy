"""add CIE OIDC Federation columns

Revision ID: 002
Revises: 001
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


TARGET_COLUMNS = (
    ("entity_id", sa.Text()),
    ("client_id", sa.Text()),
    ("oidc_provider_url", sa.Text()),
    ("trust_anchor_url", sa.Text()),
    ("authority_hint_url", sa.Text()),
    ("homepage_uri", sa.Text()),
    ("policy_uri", sa.Text()),
    ("logo_uri", sa.Text()),
    ("trust_mark_id", sa.Text()),
    ("trust_mark", sa.Text()),
    ("oidc_contact_email", sa.Text()),
)


def _existing_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _existing_columns("cie_config")
    for column_name, column_type in TARGET_COLUMNS:
        if column_name not in existing:
            op.add_column("cie_config", sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    existing = _existing_columns("cie_config")
    for column_name, _ in reversed(TARGET_COLUMNS):
        if column_name in existing:
            op.drop_column("cie_config", column_name)