import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch

from app.database import get_db
from app.models import EnteSettings, SpidCert


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


async def test_certs_status_no_cert(auth_client):
    response = await auth_client.get("/admin/certs")
    assert response.status_code == 200
    assert "Nessun certificato" in response.text


async def test_certs_generate_without_settings_returns_400(auth_client):
    response = await auth_client.post("/admin/certs/generate", follow_redirects=False)
    assert response.status_code == 400


async def test_certs_generate_with_settings_creates_cert(auth_client, db_session):
    s = EnteSettings(
        id=1,
        org_display_name="Test", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="t@t.it", contact_phone="+39",
        org_city="Pescara",
    )
    db_session.add(s)
    await db_session.commit()

    mock_cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=sso.test.it",
    )
    with patch("app.routes.certs.generate_spid_cert", return_value=mock_cert):
        response = await auth_client.post("/admin/certs/generate", follow_redirects=False)

    assert response.status_code == 302
    assert "/admin/certs" in response.headers["location"]
