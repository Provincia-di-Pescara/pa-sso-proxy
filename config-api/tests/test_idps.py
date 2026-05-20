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


async def test_idps_list_shows_idps(auth_client, db_session):
    idp = SpidIdP(
        alias="spid-test",
        display_name="Test IdP",
        metadata_url="https://test.example/metadata",
        enabled=False,
    )
    db_session.add(idp)
    await db_session.commit()

    response = await auth_client.get("/admin/idps")
    assert response.status_code == 200
    assert "Test IdP" in response.text
    assert "spid-test" in response.text


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
