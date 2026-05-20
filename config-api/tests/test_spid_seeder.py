import pytest
from sqlalchemy import select
from app.models import SpidIdP


async def test_seed_inserts_all_idps(db_session):
    from app.spid_seeder import seed_spid_idps, SPID_IDPS
    await seed_spid_idps(db_session)
    result = await db_session.execute(select(SpidIdP))
    rows = result.scalars().all()
    assert len(rows) == len(SPID_IDPS)
    aliases = {r.alias for r in rows}
    assert "spid-aruba" in aliases
    assert "spid-poste" in aliases


async def test_seed_is_idempotent(db_session):
    from app.spid_seeder import seed_spid_idps, SPID_IDPS
    await seed_spid_idps(db_session)
    await seed_spid_idps(db_session)
    result = await db_session.execute(select(SpidIdP))
    rows = result.scalars().all()
    assert len(rows) == len(SPID_IDPS)


async def test_seeded_idps_disabled_by_default(db_session):
    from app.spid_seeder import seed_spid_idps
    await seed_spid_idps(db_session)
    result = await db_session.execute(select(SpidIdP).where(SpidIdP.enabled == True))
    enabled = result.scalars().all()
    assert len(enabled) == 0
