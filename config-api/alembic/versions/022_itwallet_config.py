"""add itwallet_config (verifier IT-Wallet: config ente, chiavi EC, federazione)

Revision ID: 022
Revises: 021
Create Date: 2026-11-27

Riga unica id=1, creata dall'app. Idempotente: salta se la tabella esiste.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "itwallet_config" in inspector.get_table_names():
        return
    op.create_table(
        "itwallet_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("environment", sa.Text(), nullable=True),
        sa.Column("trust_anchor_url", sa.Text(), nullable=True),
        sa.Column("authority_hint_url", sa.Text(), nullable=True),
        sa.Column("trust_anchor_jwks", postgresql.JSONB(), nullable=True),
        sa.Column("jwk_federation_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
        sa.Column("jwk_sig_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
        sa.Column("jwk_enc_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
        sa.Column("organization_name", sa.Text(), nullable=True),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("homepage_uri", sa.Text(), nullable=True),
        sa.Column("policy_uri", sa.Text(), nullable=True),
        sa.Column("tos_uri", sa.Text(), nullable=True),
        sa.Column("logo_uri", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("trust_mark", sa.Text(), nullable=True),
        sa.Column("trust_mark_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("itwallet_config")
