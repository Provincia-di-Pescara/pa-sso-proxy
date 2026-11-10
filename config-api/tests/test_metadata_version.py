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
    db_session.add(SpidMetadataVersion(source="generated", xml_content="<A/>", content_hash="h1abcdef0123"))
    await db_session.commit()
    response = await auth_client.get("/admin/idps")
    assert response.status_code == 200
    assert 'id="gestione-metadata"' in response.text
    assert "h1abcdef0123" in response.text
    assert "Pubblicato" in response.text  # ultima riga generata = metadata servito


async def test_expose_generated_row_rejected(auth_client, db_session, tmp_path, monkeypatch):
    """Le righe generate non si espongono più: il file di override bloccava il
    metadata pubblicato su una versione vecchia (modifiche successive ignorate)."""
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    older = SpidMetadataVersion(source="generated", xml_content="<Older/>", content_hash="h1")
    db_session.add_all([older, SpidMetadataVersion(source="generated", xml_content="<Latest/>", content_hash="h2")])
    await db_session.commit()

    response = await auth_client.post(f"/admin/metadata/{older.id}/expose", follow_redirects=False)

    assert response.status_code == 303
    assert "metadata_error=" in response.headers["location"]
    assert not (tmp_path / "spid_sp_metadata_override.xml").exists()


async def test_expose_uploaded_writes_override_and_clear_removes_it(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    uploaded = SpidMetadataVersion(source="uploaded", xml_content="<Manual/>", content_hash="h1")
    db_session.add(uploaded)
    await db_session.commit()

    response = await auth_client.post(f"/admin/metadata/{uploaded.id}/expose", follow_redirects=False)
    assert response.status_code == 303
    override = tmp_path / "spid_sp_metadata_override.xml"
    assert override.read_text() == "<Manual/>"
    await db_session.refresh(uploaded)
    assert uploaded.is_exposed is True

    page = await auth_client.get("/admin/idps")
    assert "file caricato a mano" in page.text

    response = await auth_client.post("/admin/metadata/override/clear", follow_redirects=False)
    assert response.status_code == 303
    assert not override.exists()
    await db_session.refresh(uploaded)
    assert uploaded.is_exposed is False


async def test_mark_validated_creates_profile_from_current_config(auth_client, db_session):
    from app.models import SpidMetadataProfile

    db_session.add(EnteSettings(
        id=1, org_display_name="Ente", org_name="Ente", org_url="https://ente.it",
        proxy_hostname="sso.ente.it", ipa_code="c_x", contact_email="pec@ente.it",
        contact_phone="", org_city="Pescara", eidas_enabled=True, legal_entity_enabled=False,
    ))
    db_session.add(SpidMetadataVersion(source="generated", xml_content="<A/>", content_hash="h-live"))
    await db_session.commit()

    response = await auth_client.post(
        "/admin/metadata/profile/validate", data={"label": "AgID 2026-11"}, follow_redirects=False
    )

    assert response.status_code == 303
    profile = (await db_session.execute(select(SpidMetadataProfile))).scalar_one()
    assert profile.status == "validated"
    assert profile.label == "AgID 2026-11"
    assert profile.eidas_enabled is True
    assert profile.contact_email == "pec@ente.it"
    assert profile.content_hash == "h-live"
    assert profile.entity_id == "https://sso.ente.it/spidSaml2/metadata"


async def test_restore_profile_route_applies_and_regenerates(auth_client, db_session):
    from unittest.mock import AsyncMock, patch
    from app.models import SpidMetadataProfile

    settings = EnteSettings(
        id=1, org_display_name="Ente", org_name="Ente", org_url="https://ente.it",
        proxy_hostname="sso.ente.it", ipa_code="c_x", contact_email="nuova@ente.it",
        contact_phone="", org_city="Pescara", eidas_enabled=True, legal_entity_enabled=True,
    )
    profile = SpidMetadataProfile(
        status="validated", org_display_name="Ente", org_name="Ente", org_url="https://ente.it",
        ipa_code="c_x", contact_email="pec@ente.it", eidas_enabled=False, legal_entity_enabled=False,
        entity_id="https://sso.ente.it/spidSaml2/metadata",
    )
    db_session.add_all([settings, profile])
    await db_session.commit()

    with patch("app.routes.metadata.generate_and_write", new=AsyncMock()) as gen, \
         patch("app.routes.metadata.reload_satosa") as reload:
        response = await auth_client.post(f"/admin/metadata/profile/{profile.id}/restore", follow_redirects=False)

    assert response.status_code == 303
    assert "metadata_info=" in response.headers["location"]
    gen.assert_awaited_once()
    reload.assert_called_once()
    await db_session.refresh(settings)
    assert settings.eidas_enabled is False
    assert settings.legal_entity_enabled is False
    assert settings.contact_email == "pec@ente.it"


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
