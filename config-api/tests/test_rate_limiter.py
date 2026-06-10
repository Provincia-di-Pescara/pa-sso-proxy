import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from app.models import LoginAttempt
from app.database import get_db
from app.rate_limiter import (
    is_ip_banned,
    record_failed_attempt,
    clear_attempts,
    MAX_ATTEMPTS,
)

@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("LOGIN_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("LOGIN_BAN_MINUTES", "15")
    monkeypatch.setenv("LOGIN_WINDOW_MINUTES", "10")
    
    import sys
    if "app.main" in sys.modules:
        monkeypatch.setattr(sys.modules["app.main"], "ADMIN_USER", "admin")
        monkeypatch.setattr(sys.modules["app.main"], "ADMIN_PASSWORD", "secret")


@pytest.mark.asyncio
async def test_rate_limiter_helpers(db_session):
    ip = "1.2.3.4"
    
    # 1. Not banned initially
    banned, remaining = await is_ip_banned(db_session, ip)
    assert not banned
    assert remaining == 0
    
    # 2. Record 4 attempts - still not banned
    for _ in range(4):
        await record_failed_attempt(db_session, ip)
    banned, remaining = await is_ip_banned(db_session, ip)
    assert not banned
    
    # 3. 5th attempt triggers ban
    await record_failed_attempt(db_session, ip)
    banned, remaining = await is_ip_banned(db_session, ip)
    assert banned
    assert remaining > 0
    
    # 4. Clear attempts resets ban
    await clear_attempts(db_session, ip)
    banned, remaining = await is_ip_banned(db_session, ip)
    assert not banned


@pytest.mark.asyncio
async def test_rate_limiter_pruning(db_session):
    ip = "1.2.3.4"
    # Insert a very old attempt directly
    old_attempt = LoginAttempt(
        ip_address=ip,
        attempted_at=datetime.now(timezone.utc) - timedelta(days=2)
    )
    db_session.add(old_attempt)
    await db_session.commit()
    
    # Count total attempts
    res = await db_session.execute(select(func.count()).select_from(LoginAttempt))
    assert res.scalar() == 1
    
    # Recording a new failed attempt should trigger cleanup of attempts older than 24h
    await record_failed_attempt(db_session, ip)
    
    # Check that only the new attempt remains
    res = await db_session.execute(select(LoginAttempt))
    attempts = res.scalars().all()
    assert len(attempts) == 1
    attempted_at = attempts[0].attempted_at
    if attempted_at.tzinfo is None:
        attempted_at = attempted_at.replace(tzinfo=timezone.utc)
    assert (datetime.now(timezone.utc) - attempted_at).total_seconds() < 10


@pytest.mark.asyncio
async def test_login_routes_rate_limiting(app_env, db_session):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Perform 4 failed login requests
        for _ in range(4):
            resp = await client.post(
                "/admin/login",
                data={"username": "admin", "password": "wrong-password"},
                headers={"X-Real-IP": "5.6.7.8"}
            )
            assert resp.status_code == 200
            assert "credenziali" in resp.text.lower()
            assert "banned" not in resp.text.lower()
            
        # 5th failed attempt should trigger ban and return 429
        resp = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "wrong-password"},
            headers={"X-Real-IP": "5.6.7.8"}
        )
        assert resp.status_code == 429
        assert "troppi tentativi" in resp.text.lower()
        assert "disabled" in resp.text.lower()
        
        # Subsequent GET request should also show error and have disabled fields, but return 200
        resp_get = await client.get("/admin/login", headers={"X-Real-IP": "5.6.7.8"})
        assert resp_get.status_code == 200
        assert "troppi tentativi" in resp_get.text.lower()
        assert "disabled" in resp_get.text.lower()

        # Subsequent POST request should immediately return 429
        resp_post = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            headers={"X-Real-IP": "5.6.7.8"}
        )
        assert resp_post.status_code == 429

        # A different IP address is not banned
        resp_diff = await client.get("/admin/login", headers={"X-Real-IP": "9.9.9.9"})
        assert resp_diff.status_code == 200
        assert "troppi tentativi" not in resp_diff.text.lower()
        assert "disabled" not in resp_diff.text.lower()

    app.dependency_overrides.clear()
