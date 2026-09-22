import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.models import EnteSettings, SpidIdP


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-eidas")
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


async def test_eidas_config_page_loads(auth_client, db_session):
    # Setup EnteSettings
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
    ))
    await db_session.commit()

    response = await auth_client.get("/admin/eidas")
    assert response.status_code == 200
    assert "Integrazione eIDAS" in response.text
    assert "Stato Metadata SAML" in response.text


async def test_eidas_config_page_shows_active_cert_not_latest(auth_client, db_session):
    from datetime import datetime, timezone
    from app.models import SpidCert

    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
    ))
    old = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nold\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nold\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=old.test.it",
        is_active=True,
    )
    db_session.add(old)
    await db_session.commit()
    new = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nnew\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nnew\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=new.test.it",
        is_active=False,
    )
    db_session.add(new)
    await db_session.commit()

    response = await auth_client.get("/admin/eidas")
    assert response.status_code == 200
    assert "CN=old.test.it" in response.text
    assert "CN=new.test.it" not in response.text


async def test_eidas_enable_flow(auth_client, db_session):
    # Setup EnteSettings and mock SpidIdP entries for eidas
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
        eidas_enabled=False,
    ))
    db_session.add(SpidIdP(alias="eidas-qa", display_name="eIDAS QA", enabled=False, metadata_url="http://test-qa"))
    db_session.add(SpidIdP(alias="eidas-prod", display_name="eIDAS Prod", enabled=False, metadata_url="http://test-prod"))
    await db_session.commit()

    # Enable eIDAS on QA environment
    response = await auth_client.post(
        "/admin/eidas/toggle",
        data={"action": "enable", "confirmed": "yes", "environment": "qa"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/admin/eidas?saved=1" in response.headers["location"]

    # Verify database updates
    s = (await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one()
    assert s.eidas_enabled is True
    assert s.eidas_environment == "qa"

    # Verify IdPs are updated
    idp_qa = (await db_session.execute(select(SpidIdP).where(SpidIdP.alias == "eidas-qa"))).scalar_one()
    idp_prod = (await db_session.execute(select(SpidIdP).where(SpidIdP.alias == "eidas-prod"))).scalar_one()
    assert idp_qa.enabled is True
    assert idp_prod.enabled is False


async def test_eidas_disable_flow(auth_client, db_session):
    # Setup EnteSettings and mock SpidIdP entries for eidas as active
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
        eidas_enabled=True,
        eidas_environment="qa",
    ))
    db_session.add(SpidIdP(alias="eidas-qa", display_name="eIDAS QA", enabled=True, metadata_url="http://test-qa"))
    db_session.add(SpidIdP(alias="eidas-prod", display_name="eIDAS Prod", enabled=False, metadata_url="http://test-prod"))
    await db_session.commit()

    # Disable eIDAS
    response = await auth_client.post(
        "/admin/eidas/toggle",
        data={"action": "disable", "confirmed": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    # Verify database updates
    s = (await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one()
    assert s.eidas_enabled is False

    # Verify IdPs are disabled
    idp_qa = (await db_session.execute(select(SpidIdP).where(SpidIdP.alias == "eidas-qa"))).scalar_one()
    idp_prod = (await db_session.execute(select(SpidIdP).where(SpidIdP.alias == "eidas-prod"))).scalar_one()
    assert idp_qa.enabled is False
    assert idp_prod.enabled is False


async def test_eidas_new_switch_toggle_flow(auth_client, db_session):
    # Setup EnteSettings and mock SpidIdP entries
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
        eidas_enabled=False,
    ))
    db_session.add(SpidIdP(alias="eidas-qa", display_name="eIDAS QA", enabled=False, metadata_url="http://test-qa"))
    db_session.add(SpidIdP(alias="eidas-prod", display_name="eIDAS Prod", enabled=False, metadata_url="http://test-prod"))
    await db_session.commit()

    # Enable eIDAS using the new toggle switch parameter (eidas_enabled="yes")
    response = await auth_client.post(
        "/admin/eidas/toggle",
        data={"eidas_enabled": "yes", "confirmed": "yes", "environment": "prod"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/admin/eidas?saved=1" in response.headers["location"]

    s = (await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one()
    assert s.eidas_enabled is True
    assert s.eidas_environment == "prod"

    idp_prod = (await db_session.execute(select(SpidIdP).where(SpidIdP.alias == "eidas-prod"))).scalar_one()
    assert idp_prod.enabled is True
