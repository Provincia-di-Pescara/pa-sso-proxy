"""add is_active to spid_cert, backfill from latest row

Revision ID: 014
Revises: 013
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='spid_cert'"
    ))}
    if "is_active" not in existing:
        op.add_column("spid_cert", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"))
    conn.execute(sa.text(
        "UPDATE spid_cert SET is_active = true "
        "WHERE id = (SELECT id FROM spid_cert ORDER BY created_at DESC LIMIT 1)"
    ))


def downgrade():
    op.drop_column("spid_cert", "is_active")
