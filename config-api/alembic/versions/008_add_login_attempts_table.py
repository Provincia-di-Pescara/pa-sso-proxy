"""add login_attempts table

Revision ID: 008
Revises: 007
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def _existing_tables() -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "login_attempts" not in _existing_tables():
        op.create_table(
            "login_attempts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("ip_address", sa.String(45), nullable=False),
            sa.Column(
                "attempted_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index("ix_login_attempts_ip_address", "login_attempts", ["ip_address"])
        op.create_index("ix_login_attempts_attempted_at", "login_attempts", ["attempted_at"])


def downgrade() -> None:
    if "login_attempts" in _existing_tables():
        op.drop_table("login_attempts")
