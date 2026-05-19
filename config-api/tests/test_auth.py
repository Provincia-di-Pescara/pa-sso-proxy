import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_login_page_accessible(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/login")
    assert response.status_code == 200
    assert "login" in response.text.lower()


@pytest.mark.asyncio
async def test_dashboard_redirects_unauthenticated(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_login_success_and_redirect(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/"


@pytest.mark.asyncio
async def test_login_wrong_password(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert "credenziali" in response.text.lower()
