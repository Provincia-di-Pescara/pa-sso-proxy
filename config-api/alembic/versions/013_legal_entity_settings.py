"""add legal_entity_enabled to ente_settings

Revision ID: 013
Revises: 012
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='ente_settings'"
    ))}
    if "legal_entity_enabled" not in existing:
        op.add_column("ente_settings", sa.Column("legal_entity_enabled", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("ente_settings", "legal_entity_enabled")
