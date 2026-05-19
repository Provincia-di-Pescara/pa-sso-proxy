import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


async def authenticated_client(app):
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    await client.__aenter__()
    await client.post("/admin/login", data={"username": "admin", "password": "secret"})
    return client


@pytest.mark.asyncio
async def test_dashboard_accessible_when_logged_in(app_env):
    from app.main import app
    client = await authenticated_client(app)
    response = await client.get("/admin/")
    await client.__aexit__(None, None, None)
    assert response.status_code == 200
    assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_health_endpoint(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
