from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.database import get_db
from app.models import SpidCert, SpidMetadataVersion


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


async def test_metadata_history_page_loads_empty(auth_client):
    response = await auth_client.get("/admin/metadata")
    assert response.status_code == 200
    assert "Nessuna versione" in response.text


async def test_metadata_history_page_lists_versions(auth_client, db_session):
    db_session.add(SpidMetadataVersion(
        source="generated", xml_content="<A/>", content_hash="h1", is_exposed=True,
    ))
    await db_session.commit()
    response = await auth_client.get("/admin/metadata")
    assert response.status_code == 200
    assert "generated" in response.text or "Generato" in response.text


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
    assert "warning=" in response.headers["location"]
