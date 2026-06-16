"""add eidas_enabled and eidas_environment to ente_settings

Revision ID: 012
Revises: 011
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='ente_settings'"
    ))}
    if "eidas_enabled" not in existing:
        op.add_column("ente_settings", sa.Column("eidas_enabled", sa.Boolean(), nullable=False, server_default="false"))
    if "eidas_environment" not in existing:
        op.add_column("ente_settings", sa.Column("eidas_environment", sa.String(16), nullable=False, server_default="prod"))


def downgrade():
    op.drop_column("ente_settings", "eidas_environment")
    op.drop_column("ente_settings", "eidas_enabled")
