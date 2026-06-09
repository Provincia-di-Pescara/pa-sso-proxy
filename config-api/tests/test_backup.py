"""
Tests per il sistema di Backup & Ripristino.

Copre:
- GET /admin/backup      → pagina HTML (autenticato / non autenticato)
- GET /admin/backup/export → bundle JSON completo e correttamente strutturato
- POST /admin/backup/import → round-trip: export → restore → riesport → dati identici
"""
import json
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.database import get_db
from app.models import EnteSettings, OIDCClient, SpidIdP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-backup")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")


async def _make_auth_client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return app


# ---------------------------------------------------------------------------
# Helper: authenticated client
# ---------------------------------------------------------------------------

async def _login(client):
    await client.post("/admin/login", data={"username": "admin", "password": "secret"})


# ---------------------------------------------------------------------------
# Tests: pagina Backup
# ---------------------------------------------------------------------------

async def test_backup_page_unauthenticated(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/admin/backup", follow_redirects=False)
    assert resp.status_code == 302
    assert "/admin/login" in resp.headers["location"]


async def test_backup_page_authenticated(db_session, app_env):
    from app.main import app
    app.dependency_overrides[get_db] = lambda: (x for x in [db_session])

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _login(c)
        resp = await c.get("/admin/backup")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "Backup" in resp.text
    assert "Esporta" in resp.text
    assert "Ripristina" in resp.text


# ---------------------------------------------------------------------------
# Tests: export
# ---------------------------------------------------------------------------

async def test_backup_export_returns_json(db_session, app_env):
    """Export produce JSON con tutti i campi richiesti."""
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _login(c)
        resp = await c.get("/admin/backup/export")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]
    assert "attachment" in resp.headers.get("content-disposition", "")

    bundle = resp.json()
    assert bundle["version"] == "1"
    assert "exported_at" in bundle
    for key in ("ente_settings", "oidc_clients", "spid_idps", "cie_config", "jwk_keys", "spid_cert"):
        assert key in bundle, f"Campo mancante nel bundle: {key}"


async def test_backup_export_includes_client_data(db_session, app_env):
    """Export include correttamente i client OIDC inseriti."""
    from app.main import app

    c_obj = OIDCClient(
        client_id="backup-test-app",
        client_secret_hash="hashval",
        client_secret_plain="plain-secret",
        name="Backup Test",
        redirect_uris=["https://app.test/cb"],
        allowed_scopes=["openid"],
        enabled=True,
    )
    db_session.add(c_obj)
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _login(c)
        resp = await c.get("/admin/backup/export")
    app.dependency_overrides.clear()

    bundle = resp.json()
    assert any(cl["client_id"] == "backup-test-app" for cl in bundle["oidc_clients"])


async def test_backup_export_includes_spid_metadata(db_session, app_env):
    """Export include metadata_cache degli IdP SPID."""
    from app.main import app

    idp = SpidIdP(
        alias="arubaid",
        display_name="Aruba ID",
        metadata_url="https://loginspid.aruba.it/metadata",
        enabled=True,
        metadata_cache="<EntityDescriptor>FAKE</EntityDescriptor>",
        metadata_hash="abc123",
    )
    db_session.add(idp)
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _login(c)
        resp = await c.get("/admin/backup/export")
    app.dependency_overrides.clear()

    bundle = resp.json()
    idp_exported = next((i for i in bundle["spid_idps"] if i["alias"] == "arubaid"), None)
    assert idp_exported is not None
    assert idp_exported["metadata_cache"] == "<EntityDescriptor>FAKE</EntityDescriptor>"
    assert idp_exported["metadata_hash"] == "abc123"


# ---------------------------------------------------------------------------
# Tests: import round-trip
# ---------------------------------------------------------------------------

async def test_backup_import_round_trip(db_session, app_env):
    """Export → import → riesport: i dati client OIDC devono corrispondere."""
    from app.main import app

    # Popola DB
    c_obj = OIDCClient(
        client_id="roundtrip-app",
        client_secret_hash="hashed",
        client_secret_plain="plain",
        name="RoundTrip",
        redirect_uris=["https://rt.test/cb"],
        allowed_scopes=["openid", "profile"],
        enabled=True,
    )
    settings = EnteSettings(
        id=1,
        org_name="Ente Test",
        org_display_name="Ente Test",
        org_url="https://ente.test",
        ipa_code="TE00001",
        contact_email="admin@ente.test",
        contact_phone="",
        org_city="Testville",
        proxy_hostname="sso.ente.test",
        logo_url="",
        favicon_url="",
        privacy_url="",
        legal_notes_url="",
        accessibility_url="",
        support_url="",
    )
    db_session.add(c_obj)
    db_session.add(settings)
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.routes.backup.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.backup.reload_satosa", new_callable=AsyncMock):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await _login(c)

            # Export
            export_resp = await c.get("/admin/backup/export")
            assert export_resp.status_code == 200
            bundle_bytes = export_resp.content

            # Import
            import_resp = await c.post(
                "/admin/backup/import",
                files={"file": ("backup.json", bundle_bytes, "application/json")},
                follow_redirects=False,
            )
            assert import_resp.status_code == 302

            # Re-export
            reexport_resp = await c.get("/admin/backup/export")
            assert reexport_resp.status_code == 200

    app.dependency_overrides.clear()

    original = json.loads(bundle_bytes)
    restored = reexport_resp.json()

    # Client ID invariato
    orig_ids = {cl["client_id"] for cl in original["oidc_clients"]}
    rest_ids = {cl["client_id"] for cl in restored["oidc_clients"]}
    assert orig_ids == rest_ids

    # Settings hostname invariato
    assert original["ente_settings"].get("proxy_hostname") == restored["ente_settings"].get("proxy_hostname")


async def test_backup_import_invalid_json_returns_error(db_session, app_env):
    """Upload di un file non-JSON → redirect con messaggio di errore."""
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await _login(c)
        resp = await c.post(
            "/admin/backup/import",
            files={"file": ("bad.json", b"NOT JSON AT ALL", "application/json")},
            follow_redirects=False,
        )
    app.dependency_overrides.clear()
    assert resp.status_code == 302
    assert "/admin/backup" in resp.headers["location"]
