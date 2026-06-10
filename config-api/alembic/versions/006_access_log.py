"""create access_log table

Revision ID: 006
Revises: 005
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def _existing_tables() -> set:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def upgrade() -> None:
    if "access_log" not in _existing_tables():
        op.create_table(
            "access_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "timestamp",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("provider_type", sa.String(16), nullable=False),
            sa.Column("client_id", sa.String(128), nullable=True),
            sa.Column("result", sa.String(16), nullable=False),
            sa.Column("error_code", sa.String(64), nullable=True),
        )
        op.create_index("ix_access_log_timestamp", "access_log", ["timestamp"])
        op.create_index("ix_access_log_provider_type", "access_log", ["provider_type"])
        op.create_index("ix_access_log_client_id", "access_log", ["client_id"])


def downgrade() -> None:
    if "access_log" in _existing_tables():
        op.drop_table("access_log")
