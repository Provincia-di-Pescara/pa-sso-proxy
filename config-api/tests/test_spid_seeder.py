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


async def test_registry_sync_skips_ficep_and_disables_existing_row(db_session):
    """Il registro SPID elenca il nodo eIDAS (FICEP): non va importato come IdP SPID,
    la riga creata dalle sync precedenti resta ma disabilitata."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from app.spid_seeder import sync_spid_idps_from_registry

    ficep = "https://sp-proxy.eid.gov.it/spproxy/idpit"
    db_session.add(SpidIdP(
        alias="spid-sp-proxy-eid-gov-it-spproxy-idpit", display_name="AgID",
        metadata_url="https://registry.spid.gov.it/entities-idp/x",
        registry_entity_id=ficep, enabled=True,
    ))
    await db_session.commit()

    response = MagicMock()
    response.json.return_value = [
        {"entity_id": ficep, "organization_name": "AgID", "_disabled": "N"},
        {"entity_id": "https://sp-proxy.pre.eid.gov.it/spproxy/idpit", "organization_name": "AgID QA"},
        {"entity_id": "https://loginspid.aruba.it", "organization_name": "ArubaPEC S.p.A.", "_disabled": "N"},
    ]
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    with patch("app.spid_seeder.httpx.AsyncClient", return_value=client):
        inserted = await sync_spid_idps_from_registry(db_session)

    assert inserted == 1
    rows = {r.registry_entity_id: r for r in (await db_session.execute(select(SpidIdP))).scalars()}
    assert rows[ficep].enabled is False
    assert "https://sp-proxy.pre.eid.gov.it/spproxy/idpit" not in rows
    assert rows["https://loginspid.aruba.it"].enabled is True
