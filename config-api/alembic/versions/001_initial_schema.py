"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oidc_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(128), unique=True, nullable=False),
        sa.Column("client_secret_hash", sa.String(256), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("redirect_uris", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("allowed_scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "spid_idps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("metadata_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("metadata_cache", sa.Text(), nullable=True),
        sa.Column("metadata_hash", sa.String(64), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "jwk_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("use", sa.String(16), nullable=False),
        sa.Column("private_jwk", postgresql.JSONB(), nullable=False),
        sa.Column("public_jwk", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "ente_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_display_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("org_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("org_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("ipa_code", sa.String(32), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(256), nullable=False, server_default=""),
        sa.Column("contact_phone", sa.String(64), nullable=False, server_default=""),
        sa.Column("org_city", sa.String(128), nullable=False, server_default=""),
        sa.Column("proxy_hostname", sa.String(256), nullable=False, server_default=""),
    )
    op.create_table(
        "spid_cert",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("certificate_pem", sa.Text(), nullable=False),
        sa.Column("private_key_pem", sa.Text(), nullable=False),
        sa.Column("not_valid_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_dn", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "cie_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "saml_metadata_url",
            sa.Text(),
            nullable=False,
            server_default="https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
        ),
        sa.Column("oidc_federation_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("jwk_federation_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
        sa.Column("jwk_core_sig_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
        sa.Column("jwk_core_enc_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("cie_config")
    op.drop_table("spid_cert")
    op.drop_table("ente_settings")
    op.drop_table("jwk_keys")
    op.drop_table("spid_idps")
    op.drop_table("oidc_clients")
