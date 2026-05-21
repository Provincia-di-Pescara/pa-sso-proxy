"""add CIE OIDC Federation columns

Revision ID: 002
Revises: 001
Create Date: 2026-05-21
"""
from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cie_config", sa.Column("entity_id", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("client_id", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("oidc_provider_url", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("trust_anchor_url", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("authority_hint_url", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("homepage_uri", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("policy_uri", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("logo_uri", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("trust_mark_id", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("trust_mark", sa.Text(), nullable=True))
    op.add_column("cie_config", sa.Column("oidc_contact_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cie_config", "oidc_contact_email")
    op.drop_column("cie_config", "trust_mark")
    op.drop_column("cie_config", "trust_mark_id")
    op.drop_column("cie_config", "logo_uri")
    op.drop_column("cie_config", "policy_uri")
    op.drop_column("cie_config", "homepage_uri")
    op.drop_column("cie_config", "authority_hint_url")
    op.drop_column("cie_config", "trust_anchor_url")
    op.drop_column("cie_config", "oidc_provider_url")
    op.drop_column("cie_config", "client_id")
    op.drop_column("cie_config", "entity_id")