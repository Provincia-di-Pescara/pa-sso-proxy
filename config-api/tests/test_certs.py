import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

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


async def test_certs_history_no_certs(auth_client):
    response = await auth_client.get("/admin/certs")
    assert response.status_code == 200
    assert "Nessun certificato" in response.text


async def test_certs_generate_without_settings_returns_400(auth_client):
    response = await auth_client.post("/admin/certs/generate", follow_redirects=False)
    assert response.status_code == 303
    assert "/admin/idps" in response.headers["location"]
    assert "cert_error" in response.headers["location"]


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

    assert response.status_code == 303
    assert "/admin/idps" in response.headers["location"]


async def test_spid_cert_is_active_defaults_false(db_session):
    cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=sso.test.it",
    )
    db_session.add(cert)
    await db_session.commit()
    await db_session.refresh(cert)
    assert cert.is_active is False


async def _add_cert(db_session, subject_dn, is_active, cert_pem="cert", key_pem="key"):
    from app.models import SpidCert
    cert = SpidCert(
        certificate_pem=f"-----BEGIN CERTIFICATE-----\n{cert_pem}\n-----END CERTIFICATE-----",
        private_key_pem=f"-----BEGIN PRIVATE KEY-----\n{key_pem}\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn=subject_dn,
        is_active=is_active,
    )
    db_session.add(cert)
    await db_session.commit()
    await db_session.refresh(cert)
    return cert


async def test_certs_history_lists_all(auth_client, db_session):
    await _add_cert(db_session, "CN=old.test.it", is_active=False)
    await _add_cert(db_session, "CN=new.test.it", is_active=True)
    response = await auth_client.get("/admin/certs")
    assert response.status_code == 200
    assert "CN=old.test.it" in response.text
    assert "CN=new.test.it" in response.text


async def test_certs_download_cert_pem(auth_client, db_session):
    cert = await _add_cert(db_session, "CN=test.it", is_active=True, cert_pem="mycertdata")
    response = await auth_client.get(f"/admin/certs/{cert.id}/download/cert")
    assert response.status_code == 200
    assert "mycertdata" in response.text
    assert response.headers["content-type"].startswith("application/x-pem-file")


async def test_certs_download_key_pem(auth_client, db_session):
    cert = await _add_cert(db_session, "CN=test.it", is_active=True, key_pem="mykeydata")
    response = await auth_client.get(f"/admin/certs/{cert.id}/download/key")
    assert response.status_code == 200
    assert "mykeydata" in response.text


async def test_certs_activate_switches_active_flag(auth_client, db_session):
    from app.models import SpidCert
    from sqlalchemy import select
    old = await _add_cert(db_session, "CN=old.test.it", is_active=True)
    new = await _add_cert(db_session, "CN=new.test.it", is_active=False)

    with patch("app.routes.certs.write_spid_cert"), patch(
        "app.routes.certs.generate_and_write", new=AsyncMock()
    ):
        response = await auth_client.post(f"/admin/certs/{new.id}/activate", follow_redirects=False)
    assert response.status_code == 303

    await db_session.refresh(old)
    await db_session.refresh(new)
    assert old.is_active is False
    assert new.is_active is True


async def test_certs_delete_active_is_blocked(auth_client, db_session):
    from app.models import SpidCert
    from sqlalchemy import select

    cert = await _add_cert(db_session, "CN=active.test.it", is_active=True)

    response = await auth_client.post(f"/admin/certs/{cert.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert "cert_error" in response.headers["location"]

    result = await db_session.execute(select(SpidCert).where(SpidCert.id == cert.id))
    assert result.scalar_one_or_none() is not None


async def test_certs_history_renders_cert_error_from_query_param(auth_client, db_session):
    cert = await _add_cert(db_session, "CN=active.test.it", is_active=True)

    delete_resp = await auth_client.post(f"/admin/certs/{cert.id}/delete", follow_redirects=False)
    assert delete_resp.status_code == 303
    location = delete_resp.headers["location"]
    assert "cert_error" in location

    follow_resp = await auth_client.get(location)
    assert follow_resp.status_code == 200
    assert "Impossibile eliminare il certificato attivo." in follow_resp.text


async def test_certs_delete_inactive_succeeds(auth_client, db_session):
    from app.models import SpidCert
    from sqlalchemy import select

    cert = await _add_cert(db_session, "CN=inactive.test.it", is_active=False)

    response = await auth_client.post(f"/admin/certs/{cert.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/certs"

    result = await db_session.execute(select(SpidCert).where(SpidCert.id == cert.id))
    assert result.scalar_one_or_none() is None
