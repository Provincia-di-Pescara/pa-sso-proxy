"""unique constraint on spid_metadata_version(source, content_hash)

Prevents duplicate rows when two uWSGI workers race to report an identical
metadata snapshot concurrently (see internal.py log_metadata_snapshot).

Revision ID: 016
Revises: 015
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_spid_metadata_version_source_content_hash"


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT constraint_name FROM information_schema.table_constraints "
        "WHERE table_schema='public' AND table_name='spid_metadata_version'"
    ))}
    if CONSTRAINT_NAME in existing:
        return
    op.create_unique_constraint(
        CONSTRAINT_NAME,
        "spid_metadata_version",
        ["source", "content_hash"],
    )


def downgrade():
    op.drop_constraint(CONSTRAINT_NAME, "spid_metadata_version", type_="unique")
