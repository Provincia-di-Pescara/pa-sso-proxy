from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.models import EnteSettings, SpidCert, SpidMetadataVersion


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-metadata-version")
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


async def test_spid_metadata_version_defaults(db_session):
    row = SpidMetadataVersion(
        source="generated",
        xml_content="<EntityDescriptor/>",
        content_hash="abc123",
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    assert row.is_exposed is False
    assert row.is_validated is False
    assert row.cert_id is None


async def test_metadata_get_page_redirects_to_idps(auth_client):
    """La pagina dedicata /admin/metadata non esiste più: è il tab 'Gestione metadata' di /admin/idps."""
    response = await auth_client.get("/admin/metadata", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/admin/idps#gestione-metadata"


async def test_idps_page_lists_metadata_versions_in_gestione_tab(auth_client, db_session):
    db_session.add(SpidMetadataVersion(
        source="generated", xml_content="<A/>", content_hash="h1abcdef0123", is_exposed=True,
    ))
    await db_session.commit()
    response = await auth_client.get("/admin/idps")
    assert response.status_code == 200
    assert 'id="gestione-metadata"' in response.text
    assert "h1abcdef0123" in response.text
    assert "Esposto" in response.text


async def test_expose_non_latest_writes_override_file(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    latest = SpidMetadataVersion(source="generated", xml_content="<Latest/>", content_hash="h2", is_exposed=True)
    older = SpidMetadataVersion(source="generated", xml_content="<Older/>", content_hash="h1", is_exposed=False)
    db_session.add_all([older, latest])
    await db_session.commit()
    await db_session.refresh(older)

    response = await auth_client.post(f"/admin/metadata/{older.id}/expose", follow_redirects=False)
    assert response.status_code == 303

    override_path = tmp_path / "spid_sp_metadata_override.xml"
    assert override_path.exists()
    assert override_path.read_text() == "<Older/>"

    await db_session.refresh(older)
    await db_session.refresh(latest)
    assert older.is_exposed is True
    assert latest.is_exposed is False


async def test_expose_latest_removes_override_file(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    override_path = tmp_path / "spid_sp_metadata_override.xml"
    override_path.write_text("<Stale/>")

    older = SpidMetadataVersion(source="generated", xml_content="<Older/>", content_hash="h1", is_exposed=True)
    latest = SpidMetadataVersion(source="generated", xml_content="<Latest/>", content_hash="h2", is_exposed=False)
    db_session.add_all([older, latest])
    await db_session.commit()
    await db_session.refresh(latest)

    response = await auth_client.post(f"/admin/metadata/{latest.id}/expose", follow_redirects=False)
    assert response.status_code == 303
    assert not override_path.exists()


async def test_expose_warns_when_cert_mismatch(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    active_cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nc\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nk\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=active.it",
        is_active=True,
    )
    db_session.add(active_cert)
    await db_session.commit()

    latest = SpidMetadataVersion(source="generated", xml_content="<Latest/>", content_hash="h2", is_exposed=True)
    older = SpidMetadataVersion(source="generated", xml_content="<Older/>", content_hash="h1", is_exposed=False, cert_id=9999)
    db_session.add_all([older, latest])
    await db_session.commit()
    await db_session.refresh(older)

    response = await auth_client.post(f"/admin/metadata/{older.id}/expose", follow_redirects=False)
    assert response.status_code == 303
    assert "metadata_warning=" in response.headers["location"]


async def test_expose_restores_settings_toggles_from_snapshot(auth_client, db_session, tmp_path, monkeypatch):
    """
    'Esponi' è un rollback completo: se il profilo porta uno snapshot dei
    toggle eIDAS/persona giuridica, EnteSettings viene riallineato — non solo
    il documento pubblicato, anche il comportamento runtime del backend
    (ficep_enable/legal_entity_enable).
    """
    from unittest.mock import AsyncMock, patch

    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    settings = EnteSettings(
        id=1, org_display_name="Test", org_name="Test Ente", org_url="https://test.it",
        proxy_hostname="sso.test.it", ipa_code="TEST", contact_email="t@t.it",
        contact_phone="+39", org_city="Pescara",
        eidas_enabled=True, eidas_environment="prod", legal_entity_enabled=True,
    )
    db_session.add(settings)
    await db_session.commit()

    latest = SpidMetadataVersion(
        source="generated", xml_content="<Latest/>", content_hash="h2", is_exposed=True,
        eidas_enabled=True, eidas_environment="prod", legal_entity_enabled=True,
    )
    older_profile = SpidMetadataVersion(
        source="generated", xml_content="<Older/>", content_hash="h1", is_exposed=False,
        eidas_enabled=False, eidas_environment="qa", legal_entity_enabled=False,
    )
    db_session.add_all([older_profile, latest])
    await db_session.commit()
    await db_session.refresh(older_profile)

    with patch("app.routes.metadata.generate_and_write", new=AsyncMock()) as mock_gen, \
         patch("app.routes.metadata.reload_satosa") as mock_reload:
        response = await auth_client.post(f"/admin/metadata/{older_profile.id}/expose", follow_redirects=False)

    assert response.status_code == 303
    mock_gen.assert_awaited_once()
    mock_reload.assert_called_once()

    await db_session.refresh(settings)
    assert settings.eidas_enabled is False
    assert settings.eidas_environment == "qa"
    assert settings.legal_entity_enabled is False


async def test_expose_does_not_touch_settings_when_snapshot_absent(auth_client, db_session, tmp_path, monkeypatch):
    """Profili storici (precedenti al tracciamento toggle) hanno eidas_enabled=None:
    'Esponi' ripristina solo il documento, le impostazioni live restano intatte."""
    from unittest.mock import AsyncMock, patch

    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    settings = EnteSettings(
        id=1, org_display_name="Test", org_name="Test Ente", org_url="https://test.it",
        proxy_hostname="sso.test.it", ipa_code="TEST", contact_email="t@t.it",
        contact_phone="+39", org_city="Pescara",
        eidas_enabled=True, eidas_environment="prod", legal_entity_enabled=True,
    )
    db_session.add(settings)
    await db_session.commit()

    latest = SpidMetadataVersion(source="generated", xml_content="<Latest/>", content_hash="h2", is_exposed=True)
    legacy_profile = SpidMetadataVersion(source="generated", xml_content="<Legacy/>", content_hash="h1", is_exposed=False)
    db_session.add_all([legacy_profile, latest])
    await db_session.commit()
    await db_session.refresh(legacy_profile)

    with patch("app.routes.metadata.generate_and_write", new=AsyncMock()) as mock_gen, \
         patch("app.routes.metadata.reload_satosa") as mock_reload:
        response = await auth_client.post(f"/admin/metadata/{legacy_profile.id}/expose", follow_redirects=False)

    assert response.status_code == 303
    mock_gen.assert_not_awaited()
    mock_reload.assert_not_called()

    await db_session.refresh(settings)
    assert settings.eidas_enabled is True
    assert settings.legal_entity_enabled is True


async def test_validate_switches_flag(auth_client, db_session):
    v1 = SpidMetadataVersion(source="generated", xml_content="<A/>", content_hash="h1", is_validated=True)
    v2 = SpidMetadataVersion(source="generated", xml_content="<B/>", content_hash="h2", is_validated=False)
    db_session.add_all([v1, v2])
    await db_session.commit()
    await db_session.refresh(v2)

    response = await auth_client.post(f"/admin/metadata/{v2.id}/validate", follow_redirects=False)
    assert response.status_code == 303

    await db_session.refresh(v1)
    await db_session.refresh(v2)
    assert v1.is_validated is False
    assert v2.is_validated is True


async def test_upload_valid_xml_creates_uploaded_row(auth_client, db_session):
    xml_bytes = b'<?xml version="1.0"?><md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="https://test.it/metadata"/>'
    response = await auth_client.post(
        "/admin/metadata/upload",
        files={"file": ("metadata.xml", xml_bytes, "text/xml")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "metadata_error=" not in response.headers["location"]

    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "uploaded"
    assert rows[0].cert_id is None
    assert rows[0].is_exposed is False


async def test_upload_invalid_xml_rejected(auth_client, db_session):
    response = await auth_client.post(
        "/admin/metadata/upload",
        files={"file": ("bad.xml", b"not xml at all", "text/xml")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "metadata_error=" in response.headers["location"]

    result = await db_session.execute(select(SpidMetadataVersion))
    assert result.scalars().all() == []


async def test_download_returns_xml_content(auth_client, db_session):
    v = SpidMetadataVersion(source="generated", xml_content="<Downloadable/>", content_hash="h1")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    response = await auth_client.get(f"/admin/metadata/{v.id}/download")
    assert response.status_code == 200
    assert "<Downloadable/>" in response.text


async def test_delete_blocked_if_exposed(auth_client, db_session):
    v = SpidMetadataVersion(source="generated", xml_content="<A/>", content_hash="h1", is_exposed=True)
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    response = await auth_client.post(f"/admin/metadata/{v.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert "metadata_error=" in response.headers["location"]

    result = await db_session.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == v.id))
    assert result.scalar_one_or_none() is not None


async def test_delete_removes_unexposed_unvalidated_row(auth_client, db_session):
    v = SpidMetadataVersion(source="uploaded", xml_content="<A/>", content_hash="h1")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    response = await auth_client.post(f"/admin/metadata/{v.id}/delete", follow_redirects=False)
    assert response.status_code == 303

    result = await db_session.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == v.id))
    assert result.scalar_one_or_none() is None


async def test_regenerate_metadata_triggers_reload_and_redirects(auth_client, db_session):
    from unittest.mock import AsyncMock, patch

    with patch("app.routes.metadata.generate_and_write", new=AsyncMock()) as mock_gen, \
         patch("app.routes.metadata.reload_satosa") as mock_reload:
        response = await auth_client.post("/admin/metadata/regenerate", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/idps#gestione-metadata"
    mock_gen.assert_awaited_once()
    mock_reload.assert_called_once()


async def test_regenerate_metadata_requires_auth(db_session, app_env):
    from httpx import AsyncClient, ASGITransport
    from app.database import get_db

    async def override_get_db():
        yield db_session

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/admin/metadata/regenerate", follow_redirects=False)
    app.dependency_overrides.clear()

    assert response.status_code == 302
    assert response.headers["location"] == "/admin/login"
