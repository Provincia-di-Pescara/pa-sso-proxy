"""snapshot eidas_enabled/eidas_environment/legal_entity_enabled on spid_metadata_version

"Esponi" ripristina solo il documento metadata pubblicato, mai i toggle
EnteSettings che determinano il comportamento runtime del backend spidsaml2
(ficep_enable/legal_entity_enable in satosa_config_generator.py). Senza
questo snapshot non è possibile avvisare l'admin quando espone una versione
storica incoerente con i toggle live attuali.

Revision ID: 017
Revises: 016
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='spid_metadata_version'"
    ))}
    if "eidas_enabled" not in existing:
        op.add_column("spid_metadata_version", sa.Column("eidas_enabled", sa.Boolean(), nullable=True))
    if "eidas_environment" not in existing:
        op.add_column("spid_metadata_version", sa.Column("eidas_environment", sa.String(length=8), nullable=True))
    if "legal_entity_enabled" not in existing:
        op.add_column("spid_metadata_version", sa.Column("legal_entity_enabled", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("spid_metadata_version", "legal_entity_enabled")
    op.drop_column("spid_metadata_version", "eidas_environment")
    op.drop_column("spid_metadata_version", "eidas_enabled")
