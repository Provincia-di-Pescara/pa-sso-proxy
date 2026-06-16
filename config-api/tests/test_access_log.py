import pytest
import pytest_asyncio
import hmac
import hashlib
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from app.database import get_db
from app.models import AccessLog, OIDCClient

@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")
    monkeypatch.setenv("CF_HASH_KEY", "test-key-32-bytes-long-for-hmac")

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

async def test_access_log_list(auth_client, db_session):
    db_session.add(AccessLog(
        provider_type="spid",
        result="success",
        timestamp=datetime.now(timezone.utc)
    ))
    await db_session.commit()

    response = await auth_client.get("/admin/access-log")
    assert response.status_code == 200
    assert "Monitoraggio Accessi" in response.text
    assert "SPID" in response.text

async def test_access_log_advanced_list(auth_client, db_session):
    db_session.add(AccessLog(
        provider_type="cie",
        result="success",
        timestamp=datetime.now(timezone.utc),
        fiscal_number_hash="somehashvalue"
    ))
    db_session.add(AccessLog(
        provider_type="spid",
        result="failure",
        timestamp=datetime.now(timezone.utc),
        fiscal_number_hash="somehashvalue2"
    ))
    await db_session.commit()

    response = await auth_client.get("/admin/access-log/advanced")
    assert response.status_code == 200
    assert "Log Accessi" in response.text
    assert "somehashvalue" in response.text
    assert "somehashvalue2" not in response.text # SPID was failure, so it should be filtered out

async def test_access_log_advanced_search_cf(auth_client, db_session):
    key = b"test-key-32-bytes-long-for-hmac"
    cf = "RSSMRA80A01F205X"
    cf_hash = hmac.new(key, cf.encode("utf-8"), hashlib.sha256).hexdigest()

    db_session.add(AccessLog(
        provider_type="spid",
        result="success",
        timestamp=datetime.now(timezone.utc),
        fiscal_number_hash=cf_hash
    ))
    db_session.add(AccessLog(
        provider_type="cie",
        result="success",
        timestamp=datetime.now(timezone.utc),
        fiscal_number_hash=cf_hash
    ))
    db_session.add(AccessLog(
        provider_type="cie",
        result="failure",
        timestamp=datetime.now(timezone.utc),
        fiscal_number_hash=cf_hash
    ))
    db_session.add(AccessLog(
        provider_type="cie",
        result="success",
        timestamp=datetime.now(timezone.utc),
        fiscal_number_hash="otherhash"
    ))
    await db_session.commit()

    # Search with cleartext CF
    response = await auth_client.get(f"/admin/access-log/advanced?search_cf={cf}")
    assert response.status_code == 200
    assert "Risultati della ricerca per Codice Fiscale" in response.text
    assert cf_hash in response.text
    # Total accesses should show 2 (excluding the failure one)
    assert "2" in response.text
    assert "SPID" in response.text
    assert "CIE" in response.text

    # Search with hash directly (64 characters hexadecimal)
    response_hash = await auth_client.get(f"/admin/access-log/advanced?search_cf={cf_hash}")
    assert response_hash.status_code == 200
    assert cf_hash in response_hash.text
    assert "2" in response_hash.text
