import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.database import get_db
from app.models import OIDCClient


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-plan2")
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


async def test_clients_list_empty(auth_client):
    response = await auth_client.get("/admin/clients")
    assert response.status_code == 200
    assert "Nessun client" in response.text


async def test_clients_list_unauthenticated():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/clients", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


async def test_client_create_redirects_to_reveal(auth_client):
    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        response = await auth_client.post(
            "/admin/clients/new",
            data={
                "name": "Test App",
                "redirect_uris": "https://app.test/callback",
                "scopes": ["openid", "profile"],
            },
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "/reveal" in response.headers["location"]


async def test_client_create_missing_redirect_uri_returns_400(auth_client):
    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        response = await auth_client.post(
            "/admin/clients/new",
            data={"name": "Test App", "redirect_uris": "   ", "scopes": ["openid"]},
            follow_redirects=False,
        )
    assert response.status_code == 400


async def test_client_reveal_shows_secret_once(auth_client):
    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        create_resp = await auth_client.post(
            "/admin/clients/new",
            data={"name": "Test App", "redirect_uris": "https://app.test/cb", "scopes": ["openid"]},
            follow_redirects=True,
        )
    assert create_resp.status_code == 200
    # Secret shown on first visit
    assert "Client ID" in create_resp.text
    assert "Client Secret" in create_resp.text
