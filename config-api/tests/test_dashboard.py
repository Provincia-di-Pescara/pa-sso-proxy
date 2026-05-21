import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.database import get_db


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
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


async def test_dashboard_accessible_when_logged_in(auth_client):
    response = await auth_client.get("/admin/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


async def test_dashboard_shows_real_counts(auth_client, db_session):
    from app.models import OIDCClient, SpidIdP
    db_session.add(OIDCClient(
        client_id="c1", client_secret_hash="h", name="C1",
        redirect_uris=["https://x.test/cb"], allowed_scopes=["openid"], enabled=True,
    ))
    db_session.add(SpidIdP(alias="spid-aruba", display_name="Aruba", metadata_url="https://x", enabled=True))
    await db_session.commit()

    response = await auth_client.get("/admin/")
    assert response.status_code == 200
    assert "1" in response.text


@pytest.mark.asyncio
async def test_health_endpoint(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_satosa_status_running():
    from unittest.mock import AsyncMock, MagicMock, patch
    import httpx as _httpx
    from app.routes.dashboard import _satosa_status

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))

    with patch("app.routes.dashboard.httpx.AsyncClient", return_value=mock_client):
        status = await _satosa_status()

    assert status == "running"


@pytest.mark.asyncio
async def test_satosa_status_unreachable():
    from unittest.mock import AsyncMock, patch
    import httpx as _httpx
    from app.routes.dashboard import _satosa_status

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))

    with patch("app.routes.dashboard.httpx.AsyncClient", return_value=mock_client):
        status = await _satosa_status()

    assert status == "unreachable"
