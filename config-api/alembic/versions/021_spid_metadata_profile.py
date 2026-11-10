"""add spid_metadata_profile (profilo metadata SPID validato = parametri)

Revision ID: 021
Revises: 020
Create Date: 2026-11-10

I dati (profilo dalla riga storica is_validated, impronte ricalcolate) li
sistema app/metadata_profile.py:normalize_metadata_history all'avvio di
config-api: idempotente e indipendente dalla migrazione.
"""
from alembic import op
import sqlalchemy as sa


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "spid_metadata_profile" in inspector.get_table_names():
        return
    op.create_table(
        "spid_metadata_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("label", sa.String(256), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="validated"),
        sa.Column("cert_id", sa.Integer(), sa.ForeignKey("spid_cert.id", ondelete="SET NULL"), nullable=True),
        sa.Column("cert_fingerprint", sa.String(64), nullable=True),
        sa.Column("org_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("org_display_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("org_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(256), nullable=False, server_default=""),
        sa.Column("contact_phone", sa.String(64), nullable=False, server_default=""),
        sa.Column("vat_number", sa.String(32), nullable=False, server_default=""),
        sa.Column("ipa_code", sa.String(32), nullable=False, server_default=""),
        sa.Column("eidas_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("eidas_environment", sa.String(16), nullable=False, server_default="prod"),
        sa.Column("legal_entity_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("entity_id", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "metadata_version_id",
            sa.Integer(),
            sa.ForeignKey("spid_metadata_version.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content_hash", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("spid_metadata_profile")
