"""drop unique constraint on spid_metadata_version(source, content_hash)

Il vincolo (aggiunto in 016 per la race tra i 2 worker uWSGI) impediva di
storicizzare uno snapshot quando il contenuto tornava identico a una riga
VECCHIA (non l'ultima) — non solo il caso raro "collisione tra due insert
simultanei", ma il ciclo normale toggle-on -> toggle-off -> toggle-on
(A->B->A), dove il contenuto semantico legittimamente ricompare nel tempo.
L'insert falliva in silenzio (IntegrityError catturata e trattata come
"race già gestita da un altro worker"), lasciando is_exposed puntato su una
riga che SATOSA non serve più davvero.

Da quando il dedup usa l'hash SEMANTICO (fix precedente) invece dell'hash
del documento firmato, i contenuti possono ripetersi legittimamente nel
tempo — l'unicità globale non è più la garanzia corretta. Il controllo
applicativo "differisce dall'ultima riga" (log_metadata_snapshot) resta la
difesa primaria per evitare rumore; un occasionale duplicato consecutivo
dalla race dei 2 worker (stesso hash, stesso istante) è rumore cosmetico
accettabile, non una corruzione dello stato is_exposed.

Revision ID: 018
Revises: 017
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_spid_metadata_version_source_content_hash"


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT constraint_name FROM information_schema.table_constraints "
        "WHERE table_schema='public' AND table_name='spid_metadata_version'"
    ))}
    if CONSTRAINT_NAME not in existing:
        return
    op.drop_constraint(CONSTRAINT_NAME, "spid_metadata_version", type_="unique")


def downgrade():
    op.create_unique_constraint(
        CONSTRAINT_NAME,
        "spid_metadata_version",
        ["source", "content_hash"],
    )
