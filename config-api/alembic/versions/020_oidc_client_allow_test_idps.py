"""add allow_test_idps to oidc_clients

Revision ID: 020
Revises: 019
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='oidc_clients'"
    ))}
    if "allow_test_idps" not in existing:
        op.add_column(
            "oidc_clients",
            sa.Column("allow_test_idps", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade():
    op.drop_column("oidc_clients", "allow_test_idps")
