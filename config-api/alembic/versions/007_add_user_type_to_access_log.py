"""add user_type to access_log

Revision ID: 007
Revises: 006
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if column already exists to be safe and idempotent
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("access_log")]
    if "user_type" not in columns:
        op.add_column(
            "access_log",
            sa.Column("user_type", sa.String(16), nullable=True)
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("access_log")]
    if "user_type" in columns:
        op.drop_column("access_log", "user_type")
