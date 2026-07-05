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


@pytest.mark.asyncio
async def test_session_inactivity_expiry_and_rolling(override_db, monkeypatch):
    import time
    from app.main import app
    import app.main as main_mod

    # Set a custom SESSION_MAX_AGE for testing (e.g. 5 seconds)
    monkeypatch.setattr(main_mod, "SESSION_MAX_AGE", 5)

    # Mock time.time to return a controlled mock time
    start_time = 100000.0
    current_time = start_time
    
    def mock_time():
        return current_time
        
    monkeypatch.setattr(time, "time", mock_time)
    monkeypatch.setattr(main_mod.time, "time", mock_time)

    # Use AsyncClient with ASGITransport to test cookie-based session persistence
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Login at t = start_time
        login_res = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=False,
        )
        assert login_res.status_code == 302
        
        # Verify that we can access the dashboard (t = start_time, session is fresh)
        dash_res = await client.get("/admin/", follow_redirects=False)
        assert dash_res.status_code == 200

        # 2. Advance time by 3 seconds (t = start_time + 3.0), within SESSION_MAX_AGE (5s)
        current_time = start_time + 3.0
        dash_res2 = await client.get("/admin/", follow_redirects=False)
        assert dash_res2.status_code == 200
        
        # 3. Advance time by another 3 seconds (t = start_time + 6.0)
        # Total time since login is 6s (which is > SESSION_MAX_AGE), but last request was 3s ago.
        # Since it is rolling, the session should remain active!
        current_time = start_time + 6.0
        dash_res3 = await client.get("/admin/", follow_redirects=False)
        assert dash_res3.status_code == 200

        # 4. Advance time by 6 seconds (t = start_time + 12.0)
        # 6 seconds have passed since the last request, which is > SESSION_MAX_AGE (5s)
        # The session must expire.
        current_time = start_time + 12.0
        dash_res4 = await client.get("/admin/", follow_redirects=False)
        assert dash_res4.status_code == 302
        assert "/admin/login?timeout=1" in dash_res4.headers["location"]

        # 5. Verify that accessing the login page with timeout=1 displays the correct message
        login_page_res = await client.get("/admin/login?timeout=1")
        assert login_page_res.status_code == 200
        assert "scaduta per inattività" in login_page_res.text.lower()
