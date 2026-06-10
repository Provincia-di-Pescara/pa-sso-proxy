import pytest
from httpx import AsyncClient, ASGITransport
from app.database import get_db

@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture
def override_db(db_session, app_env, monkeypatch):
    from app.main import app
    import sys
    if "app.main" in sys.modules:
        monkeypatch.setattr(sys.modules["app.main"], "ADMIN_USER", "admin")
        monkeypatch.setattr(sys.modules["app.main"], "ADMIN_PASSWORD", "secret")
        
    async def override_get_db():
        yield db_session
        
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_page_accessible(override_db):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/login")
    assert response.status_code == 200
    assert "login" in response.text.lower()


@pytest.mark.asyncio
async def test_dashboard_redirects_unauthenticated(override_db):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_login_success_and_redirect(override_db):
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
async def test_login_wrong_password(override_db):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert "credenziali" in response.text.lower()
