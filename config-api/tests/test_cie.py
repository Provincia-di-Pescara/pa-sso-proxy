import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.models import JwkKey, CieConfig


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


async def test_cie_form_shows_empty(auth_client):
    response = await auth_client.get("/admin/cie")
    assert response.status_code == 200
    assert "CIE OIDC" in response.text


async def test_cie_unauthenticated_redirects():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/cie", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


async def test_cie_save_creates_config(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    response = await auth_client.post(
        "/admin/cie",
        data={
            "saml_metadata_url": "https://idserver.servizicie.interno.gov.it/idp/shibboleth",
            "entity_id": "https://proxy.test",
            "client_id": "cie-client",
            "jwk_federation_id": "",
            "jwk_core_sig_id": "",
            "jwk_core_enc_id": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    result = await db_session.execute(select(CieConfig).where(CieConfig.id == 1))
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.saml_metadata_url == "https://idserver.servizicie.interno.gov.it/idp/shibboleth"


async def test_cie_generate_jwk_creates_key(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    response = await auth_client.post(
        "/admin/cie/generate-jwk/sig",
        follow_redirects=False,
    )
    assert response.status_code == 302

    result = await db_session.execute(select(JwkKey).where(JwkKey.use == "sig"))
    key = result.scalar_one_or_none()
    assert key is not None
    assert key.public_jwk["kty"] == "EC"
    assert key.use == "sig"


async def test_cie_delete_jwk_removes_key(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    key = JwkKey(name="test-key", use="sig", private_jwk={}, public_jwk={})
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)

    response = await auth_client.post(
        f"/admin/cie/delete-jwk/{key.id}",
        follow_redirects=False,
    )
    assert response.status_code == 302

    result = await db_session.execute(select(JwkKey).where(JwkKey.id == key.id))
    assert result.scalar_one_or_none() is None


async def test_cie_config_has_oidc_fields(db_session):
    config = CieConfig(
        id=1,
        saml_metadata_url="https://x",
        oidc_provider_url="https://oidc.provider.it",
        trust_anchor_url="https://trust.anchor.it",
        authority_hint_url="https://authority.hint.it",
        homepage_uri="https://ente.it",
        policy_uri="https://ente.it/privacy",
        logo_uri="https://ente.it/logo.png",
        trust_mark_id="https://registry.cie.gov.it/tm/rp",
        trust_mark="eyJhbGciOiJFUzI1NiJ9.stub",
        oidc_contact_email="admin@ente.it",
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)
    assert config.oidc_provider_url == "https://oidc.provider.it"
    assert config.trust_mark == "eyJhbGciOiJFUzI1NiJ9.stub"
    assert config.oidc_contact_email == "admin@ente.it"


async def test_cie_save_oidc_federation_fields(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    response = await auth_client.post(
        "/admin/cie",
        data={
            "saml_metadata_url": "https://idserver.servizicie.interno.gov.it/idp/shibboleth",
            "entity_id": "",
            "client_id": "https://proxy.ente.it/CieOidcRp",
            "jwk_federation_id": "",
            "jwk_core_sig_id": "",
            "jwk_core_enc_id": "",
            "oidc_federation_enabled": "on",
            "oidc_provider_url": "https://preprod.oidc.interno.gov.it",
            "trust_anchor_url": "https://registry.cie.gov.it",
            "authority_hint_url": "https://registry.cie.gov.it",
            "homepage_uri": "https://ente.it",
            "policy_uri": "",
            "logo_uri": "",
            "trust_mark_id": "https://registry.cie.gov.it/tm/rp",
            "trust_mark": "eyJhbGciOiJFUzI1NiJ9.stub",
            "oidc_contact_email": "admin@ente.it",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    result = await db_session.execute(select(CieConfig).where(CieConfig.id == 1))
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.oidc_federation_enabled is True
    assert config.trust_mark == "eyJhbGciOiJFUzI1NiJ9.stub"
    assert config.trust_mark_id == "https://registry.cie.gov.it/tm/rp"
    assert config.authority_hint_url == "https://registry.cie.gov.it"
    assert config.oidc_contact_email == "admin@ente.it"
