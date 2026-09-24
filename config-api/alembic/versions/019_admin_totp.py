"""add admin_totp table (2FA TOTP admin WebUI)

Revision ID: 019
Revises: 018
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa


revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def _existing_tables() -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "admin_totp" not in _existing_tables():
        op.create_table(
            "admin_totp",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
            sa.Column("secret_enc", sa.Text(), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_counter", sa.BigInteger(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )


def downgrade() -> None:
    op.drop_table("admin_totp")
