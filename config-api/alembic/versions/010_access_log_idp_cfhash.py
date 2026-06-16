"""add idp_entity_id and fiscal_number_hash to access_log

Revision ID: 010
Revises: 009
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    if not _has_column("access_log", "idp_entity_id"):
        op.add_column("access_log", sa.Column("idp_entity_id", sa.Text(), nullable=True))
        op.create_index("ix_access_log_idp_entity_id", "access_log", ["idp_entity_id"])
    if not _has_column("access_log", "fiscal_number_hash"):
        op.add_column("access_log", sa.Column("fiscal_number_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    if _has_column("access_log", "fiscal_number_hash"):
        op.drop_column("access_log", "fiscal_number_hash")
    if _has_column("access_log", "idp_entity_id"):
        op.drop_index("ix_access_log_idp_entity_id", table_name="access_log")
        op.drop_column("access_log", "idp_entity_id")
