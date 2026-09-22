"""create spid_metadata_version table

Revision ID: 015
Revises: 014
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing_tables = {row[0] for row in conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    ))}
    if "spid_metadata_version" in existing_tables:
        return
    op.create_table(
        "spid_metadata_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("xml_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("cert_id", sa.Integer(), sa.ForeignKey("spid_cert.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_exposed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_validated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("label", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_spid_metadata_version_content_hash", "spid_metadata_version", ["content_hash"])


def downgrade():
    op.drop_index("ix_spid_metadata_version_content_hash", table_name="spid_metadata_version")
    op.drop_table("spid_metadata_version")
