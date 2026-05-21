import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.database import get_db
from app.models import SpidIdP


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-plan3")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")


@pytest_asyncio.fixture
async def auth_client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/login", data={"username": "admin", "password": "secret"})
        yield client

    app.dependency_overrides.clear()


async def test_idps_list_shows_registry_api_results(auth_client):
    from app.models import SpidIdP

    # Use the route's DB dependency override to insert synchronized cache rows.
    from app.main import app
    session = None
    async for s in app.dependency_overrides[get_db]():
        session = s
        break

    session.add_all([
        SpidIdP(
            alias="spid-sielte",
            display_name="Sielte",
            metadata_url="https://registry.spid.gov.it/entities-idp/https%3A%2F%2Fidentity.sieltecloud.it",
            registry_entity_id="https://identity.sieltecloud.it",
            registry_logo_uri="https://cdn.jsdelivr.net/gh/italia/spid-sp-access-button/src/production/img/spid-idp-sielteid.svg",
            registry_organization_name="Sielte S.p.A.",
            registry_lastupdate_date="2026-01-09 14:52:07",
            registry_disabled=False,
            enabled=False,
        )
    ])
    await session.commit()

    response = await auth_client.get("/admin/idps")

    assert response.status_code == 200
    assert "Aggiorna metadata SPID Registry" in response.text
    assert "https://identity.sieltecloud.it" in response.text
    assert "Sielte S.p.A." in response.text
    assert "2026-01-09 14:52:07" in response.text
    assert "Logo Sielte S.p.A." in response.text


async def test_idps_detail_shows_full_metadata(auth_client):
    mock_detail_call = {
        "request_url": "https://registry.spid.gov.it/entities-idp/https%3A%2F%2Fidentity.sieltecloud.it?output=json",
        "ok": True,
        "headers": {"tot_metadata": "1", "tot_pages": "1", "current_page": "1", "last_modified": "2026-01-09 14:52:07"},
        "detail": {
            "entity_id": "https://identity.sieltecloud.it",
            "organization_name": "Sielte S.p.A.",
            "organization_display_name": "http://www.sielte.it",
            "code": "03600700870",
            "lastupdate_date": "2026-01-09 14:52:07",
            "registry_link": "https://registry.spid.gov.it/entities-idp/https%3A%2F%2Fidentity.sieltecloud.it?output=json",
            "single_sign_on_service": [{"Binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect", "Location": "https://identity.sieltecloud.it/simplesaml/saml2/idp/SSO.php"}],
        },
    }

    with patch("app.routes.idps._fetch_spid_registry_idp_detail", new=AsyncMock(return_value=mock_detail_call)):
        response = await auth_client.get("/admin/idps/detail", params={"entity_id": "https://identity.sieltecloud.it"})

    assert response.status_code == 200
    assert "Dettaglio metadata SPID" in response.text
    assert "Sielte S.p.A." in response.text
    assert "single_sign_on_service" in response.text


async def test_idps_list_unauthenticated():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/idps", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


async def test_idp_toggle_enables(auth_client, db_session):
    idp = SpidIdP(
        alias="spid-toggle",
        display_name="Toggle IdP",
        metadata_url="https://toggle.example/metadata",
        enabled=False,
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    with patch("app.routes.idps.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.idps.reload_satosa", return_value=True):
        response = await auth_client.post(f"/admin/idps/{idp.id}/toggle", follow_redirects=False)

    assert response.status_code == 302
    await db_session.refresh(idp)
    assert idp.enabled is True


async def test_idp_force_refresh_calls_fetch(auth_client, db_session):
    idp = SpidIdP(
        alias="spid-refresh",
        display_name="Refresh IdP",
        metadata_url="https://refresh.example/metadata",
        enabled=True,
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    with patch("app.routes.idps.fetch_idp_metadata", new_callable=AsyncMock, return_value=True), \
         patch("app.routes.idps.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.idps.reload_satosa", return_value=True):
        response = await auth_client.post(f"/admin/idps/{idp.id}/refresh", follow_redirects=False)

    assert response.status_code == 302


async def test_idps_manual_sync_endpoint(auth_client):
    with patch("app.routes.idps.sync_spid_idps_from_registry", new=AsyncMock(return_value=3)), \
         patch("app.routes.idps.generate_and_write", new=AsyncMock()), \
         patch("app.routes.idps.reload_satosa", return_value=True):
        response = await auth_client.post("/admin/idps/sync", follow_redirects=False)

    assert response.status_code == 302
    assert "sync=ok" in response.headers["location"]
    assert "inserted=3" in response.headers["location"]


async def test_idps_list_shows_sync_feedback(auth_client):
    response = await auth_client.get("/admin/idps?sync=ok&inserted=2")
    assert response.status_code == 200
    assert "Sync completata" in response.text
    assert "Nuovi IdP inseriti: 2" in response.text
