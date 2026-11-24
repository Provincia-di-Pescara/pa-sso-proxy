"""Hardening minori dall'audit di sicurezza: URL ente, state OIDC, secret
client, parser XML."""
import json
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.models import EnteSettings, OIDCClient
from app.routes.settings import validate_settings
from app.url_validation import valid_public_url

APP_DIR = Path(__file__).resolve().parent.parent / "app"


# --- F1: URL configurati dall'admin --------------------------------------------

@pytest.mark.parametrize("value", [
    "", "https://ente.it", "http://ente.it/privacy", "https://ente.it:8443/a?b=c#d",
    "/static/logo.svg",
])
def test_valid_public_url_ok(value):
    assert valid_public_url(value)


@pytest.mark.parametrize("value", [
    "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<b>", "vbscript:x",
    "//evil.example/x", "https://", "ftp://ente.it", "https://a b.it", "https://ente.it/\"onmouseover=x",
    "https://user:pw@ente.it/", "https://ente.it/<script>", "\\\\evil", "x" * 3000,
    " javascript:alert(1)",
])
def test_valid_public_url_rejected(value):
    assert not valid_public_url(value)


@pytest.mark.parametrize("host,ok", [
    ("sso.ente.it", True), ("localhost", True), ("localhost:8443", True),
    ("https://sso.ente.it", False), ("sso.ente.it/path", False), ("sso ente.it", False),
    ("sso.ente.it\nX: y", False), ("", False), ("-bad.it", False), ("a" * 300, False),
])
def test_proxy_hostname_validation(host, ok):
    err = validate_settings({"proxy_hostname": host})
    assert (err is None) is ok


@pytest.fixture
def app_admin(db_session, monkeypatch):
    import sys
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    from app.main import app
    monkeypatch.setattr(sys.modules["app.main"], "ADMIN_USER", "admin")
    monkeypatch.setattr(sys.modules["app.main"], "ADMIN_PASSWORD", "secret")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


FORM = {
    "org_name": "Ente", "proxy_hostname": "sso.ente.it", "ipa_code": "c_x",
    "org_city": "Pescara", "vat_number": "00000000000",
}


async def test_settings_rejects_javascript_url(app_admin, db_session):
    async with _client(app_admin) as c:
        await c.post("/admin/login", data={"username": "admin", "password": "secret"})
        r = await c.post("/admin/settings", data={**FORM, "privacy_url": "javascript:alert(1)"})
    assert r.status_code == 400
    assert "Privacy: URL non valido" in r.text
    assert (await db_session.get(EnteSettings, 1)) is None


async def test_settings_accepts_valid_urls(app_admin, db_session):
    async with _client(app_admin) as c:
        await c.post("/admin/login", data={"username": "admin", "password": "secret"})
        r = await c.post("/admin/settings", data={**FORM, "privacy_url": " https://ente.it/privacy ",
                                                  "logo_url": "/static/logo.svg"})
    assert r.status_code == 302
    s = await db_session.get(EnteSettings, 1)
    assert s.privacy_url == "https://ente.it/privacy" and s.logo_url == "/static/logo.svg"


def test_generator_drops_invalid_stored_urls():
    """Valori salvati prima della validazione non arrivano alla discovery."""
    from types import SimpleNamespace
    from app.satosa_config_generator import _eid_locale_strings
    s = SimpleNamespace(org_display_name="Ente", logo_url="javascript:x", favicon_url="https://ente.it/f.ico",
                        privacy_url="javascript:alert(1)", legal_notes_url="", accessibility_url="/a",
                        support_url="data:text/html,x")
    data = _eid_locale_strings(None, s, [])["it"]
    assert data["header"]["logo_url"] == ""
    assert data["header"]["favicon_url"] == "https://ente.it/f.ico"
    assert data["footer"] == {"privacy_policy_url": "", "legal_notice_url": "",
                              "accessibility_url": "/a", "support_url": ""}


# --- F7: state OIDC senza sessione ---------------------------------------------

async def test_verifica_callback_without_session_state_rejected(app_admin):
    async with _client(app_admin) as c:
        r = await c.get("/verifica/callback?code=abc")
    assert r.status_code == 200
    assert "state_mismatch" in r.text


# --- F3: mai l'hash come secret ------------------------------------------------

async def test_client_without_plain_secret_excluded(db_session, tmp_path, monkeypatch):
    from app import satosa_config_generator as g
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    db_session.add_all([
        EnteSettings(id=1, org_name="Ente", proxy_hostname="sso.ente.it", ipa_code="c_x", org_city="Roma"),
        OIDCClient(client_id="ok", client_secret_hash="$2b$hash", client_secret_plain="segreto",
                   name="Ok", redirect_uris=["https://a/cb"], allowed_scopes=["openid"]),
        OIDCClient(client_id="legacy", client_secret_hash="$2b$hash", client_secret_plain=None,
                   name="Legacy", redirect_uris=["https://b/cb"], allowed_scopes=["openid"]),
    ])
    await db_session.commit()
    await g.generate_satosa_config(db_session)
    db = json.loads((tmp_path / "oidc_clients.json").read_text())
    assert db["ok"]["client_secret"] == "segreto"
    assert "legacy" not in db
    assert "$2b$hash" not in (tmp_path / "oidc_clients.json").read_text()


# --- F9: niente parser XML stdlib ----------------------------------------------

def test_no_stdlib_xml_parser():
    offenders = [
        str(p.relative_to(APP_DIR)) for p in APP_DIR.rglob("*.py")
        if re.search(r"^\s*(import|from)\s+xml\.(etree|dom|sax)", p.read_text(encoding="utf-8"), re.M)
    ]
    assert offenders == [], "usare defusedxml"
