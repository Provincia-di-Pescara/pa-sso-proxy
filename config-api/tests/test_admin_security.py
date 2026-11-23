"""Hardening sessione admin: revoca server-side, guard globale, CSRF (Origin),
nessun segreto nel cookie, blocco globale TOTP."""
import base64
import json
import re
import sys
from datetime import datetime, timezone

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.models import AdminTotp


@pytest.fixture
def app_admin(db_session, monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    from app.main import app
    monkeypatch.setattr(sys.modules["app.main"], "ADMIN_USER", "admin")
    monkeypatch.setattr(sys.modules["app.main"], "ADMIN_PASSWORD", "secret")

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


def _client(app, **kw):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", **kw)


async def _login(c):
    r = await c.post("/admin/login", data={"username": "admin", "password": "secret"}, follow_redirects=False)
    assert r.headers["location"] == "/admin/"
    return r


def _session_payload(c) -> dict:
    raw = c.cookies.get("session")
    data = raw.split(".")[0]
    return json.loads(base64.b64decode(data + "=" * (-len(data) % 4)))


# --- revoca server-side --------------------------------------------------------

async def test_logout_revokes_copied_cookie(app_admin):
    async with _client(app_admin) as c:
        await _login(c)
        stolen = c.cookies.get("session")
        assert (await c.get("/admin/", follow_redirects=False)).status_code == 200
        await c.post("/admin/logout", follow_redirects=False)
    async with _client(app_admin, cookies={"session": stolen}) as attacker:
        r = await attacker.get("/admin/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"].startswith("/admin/login")


async def test_idle_timeout_is_server_side(app_admin, monkeypatch):
    from app import admin_sessions
    async with _client(app_admin) as c:
        await _login(c)
        now = admin_sessions._now()
        monkeypatch.setattr(admin_sessions, "_now", lambda: now + admin_sessions.IDLE_TIMEOUT + 1)
        r = await c.get("/admin/", follow_redirects=False)
        assert r.status_code == 302
        assert "timeout=1" in r.headers["location"]


async def test_absolute_lifetime(app_admin, monkeypatch):
    from app import admin_sessions
    async with _client(app_admin) as c:
        await _login(c)
        start = admin_sessions._now()
        # attività continua, ma oltre la durata massima assoluta
        t = start
        while t < start + admin_sessions.ABSOLUTE_LIFETIME:
            t += admin_sessions.IDLE_TIMEOUT - 1
            monkeypatch.setattr(admin_sessions, "_now", lambda t=t: t)
            await c.get("/admin/", follow_redirects=False)
        r = await c.get("/admin/", follow_redirects=False)
        assert r.status_code == 302


# --- guard globale -------------------------------------------------------------

def _admin_paths(app):
    # Schema OpenAPI (API pubblica): la struttura interna di app.routes cambia
    # tra le versioni di FastAPI (router inclusi come _IncludedRouter).
    public = ("/admin/login", "/admin/static", "/admin/logout")
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/admin") or path.startswith(public):
            continue
        yield re.sub(r"\{[^}]+\}", "1", path), {m.upper() for m in ops}


async def test_every_admin_route_requires_login(app_admin):
    checked = 0
    async with _client(app_admin) as c:
        for path, methods in _admin_paths(app_admin):
            for method in methods & {"GET", "POST"}:
                r = await c.request(method, path, follow_redirects=False)
                assert r.status_code in (302, 303), (method, path, r.status_code)
                assert r.headers["location"].startswith("/admin/login"), (method, path)
                checked += 1
    assert checked > 30


# --- CSRF (Origin / Sec-Fetch-Site) -------------------------------------------

@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "https://test.evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Referer": "https://evil.example/page"},
    {"Origin": "null"},
])
async def test_cross_origin_post_rejected(app_admin, headers):
    async with _client(app_admin) as c:
        await _login(c)
        r = await c.post("/admin/logout", headers=headers, follow_redirects=False)
        assert r.status_code == 403
        # sessione ancora valida: il logout non è avvenuto
        assert (await c.get("/admin/", follow_redirects=False)).status_code == 200


async def test_cross_origin_login_rejected(app_admin):
    async with _client(app_admin) as c:
        r = await c.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            headers={"Origin": "https://evil.example"},
            follow_redirects=False,
        )
        assert r.status_code == 403


@pytest.mark.parametrize("headers", [
    {"Origin": "http://test"},
    {"Origin": "https://test"},  # TLS terminato dal reverse proxy: conta l'host
    {"Sec-Fetch-Site": "same-origin", "Origin": "http://test"},
    {"Referer": "http://test/admin/"},
    {},  # client non browser (curl, script): niente CSRF possibile
])
async def test_same_origin_post_allowed(app_admin, headers):
    async with _client(app_admin) as c:
        await _login(c)
        r = await c.post("/admin/logout", headers=headers, follow_redirects=False)
        assert r.status_code == 302


# --- nessun segreto nel cookie -------------------------------------------------

async def test_client_secret_not_stored_in_cookie(app_admin, monkeypatch):
    from app.routes import clients as clients_routes

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(clients_routes, "generate_and_write", _noop)
    monkeypatch.setattr(clients_routes, "reload_satosa", lambda: None)
    async with _client(app_admin) as c:
        await _login(c)
        r = await c.post(
            "/admin/clients/new",
            data={"name": "App", "redirect_uris": "https://app.example.it/cb"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        payload = json.dumps(_session_payload(c))
        page = await c.get(r.headers["location"])
        secret = re.search(r"[A-Za-z0-9_-]{43}", page.text).group(0)
        assert secret not in payload
        # mostrato una sola volta
        again = await c.get(r.headers["location"])
        assert secret not in again.text


# --- blocco globale del secondo fattore ---------------------------------------

async def test_totp_global_lock_across_ips(app_admin, db_session, monkeypatch):
    from app import admin_2fa
    from app.rate_limiter import TOTP_MAX_FAILURES
    monkeypatch.setenv("ADMIN_2FA_ENABLED", "true")
    secret = pyotp.random_base32()
    db_session.add(AdminTotp(id=1, secret_enc=admin_2fa.encrypt_secret(secret),
                             confirmed_at=datetime.now(timezone.utc)))
    await db_session.commit()
    async with _client(app_admin) as c:
        await c.post("/admin/login", data={"username": "admin", "password": "secret"}, follow_redirects=False)
        for i in range(TOTP_MAX_FAILURES):
            await c.post("/admin/login/2fa", data={"code": "000000"},
                         headers={"X-Real-IP": f"198.51.100.{i}"}, follow_redirects=False)
        r = await c.post("/admin/login/2fa", data={"code": pyotp.TOTP(secret).now()},
                         headers={"X-Real-IP": "203.0.113.77"}, follow_redirects=False)
        assert r.status_code == 429
        assert (await c.get("/admin/", follow_redirects=False)).status_code == 302


def test_session_https_only_default_true(monkeypatch):
    from app.admin_sessions import env_flag
    monkeypatch.delenv("SESSION_HTTPS_ONLY", raising=False)
    assert env_flag("SESSION_HTTPS_ONLY", True) is True
    monkeypatch.setenv("SESSION_HTTPS_ONLY", "false")
    assert env_flag("SESSION_HTTPS_ONLY", True) is False
