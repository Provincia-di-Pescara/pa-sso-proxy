import sys
from datetime import datetime, timezone

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.models import AdminTotp


@pytest.fixture
def app_2fa(db_session, monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("ADMIN_2FA_ENABLED", "true")
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


async def _password_login(c):
    return await c.post(
        "/admin/login",
        data={"username": "admin", "password": "secret"},
        follow_redirects=False,
    )


async def _enroll(db_session) -> str:
    from app import admin_2fa
    secret = pyotp.random_base32()
    db_session.add(AdminTotp(
        id=1,
        secret_enc=admin_2fa.encrypt_secret(secret),
        confirmed_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()
    return secret


async def _dashboard_status(c) -> int:
    return (await c.get("/admin/", follow_redirects=False)).status_code


# --- login password ----------------------------------------------------------

async def test_password_only_redirects_to_setup_when_not_enrolled(app_2fa):
    async with _client(app_2fa) as c:
        r = await _password_login(c)
        assert r.status_code == 302
        assert r.headers["location"] == "/admin/login/setup"
        assert await _dashboard_status(c) == 302


async def test_password_only_redirects_to_2fa_when_enrolled(app_2fa, db_session):
    await _enroll(db_session)
    async with _client(app_2fa) as c:
        r = await _password_login(c)
        assert r.headers["location"] == "/admin/login/2fa"
        assert await _dashboard_status(c) == 302


# --- setup ------------------------------------------------------------------

async def test_setup_wrong_then_right_code(app_2fa, db_session):
    from app import admin_2fa
    async with _client(app_2fa) as c:
        await _password_login(c)
        page = await c.get("/admin/login/setup")
        assert page.status_code == 200
        assert "<svg" in page.text

        row = await admin_2fa.get_totp(db_session)
        secret = admin_2fa.decrypt_secret(row.secret_enc)
        assert secret in page.text.replace(" ", "")

        bad = await c.post("/admin/login/setup", data={"code": "000000"}, follow_redirects=False)
        assert bad.status_code == 200
        assert "Codice non valido" in bad.text
        assert await _dashboard_status(c) == 302

        ok = await c.post(
            "/admin/login/setup",
            data={"code": pyotp.TOTP(secret).now()},
            follow_redirects=False,
        )
        assert ok.status_code == 302
        assert ok.headers["location"] == "/admin/"
        assert await _dashboard_status(c) == 200

    row = await admin_2fa.get_totp(db_session)
    assert row.confirmed_at is not None


async def test_setup_reload_keeps_same_secret(app_2fa, db_session):
    from app import admin_2fa
    async with _client(app_2fa) as c:
        await _password_login(c)
        await c.get("/admin/login/setup")
        first = admin_2fa.decrypt_secret((await admin_2fa.get_totp(db_session)).secret_enc)
        await c.get("/admin/login/setup")
        second = admin_2fa.decrypt_secret((await admin_2fa.get_totp(db_session)).secret_enc)
    assert first == second


async def test_setup_with_confirmed_row_redirects_to_2fa(app_2fa, db_session):
    await _enroll(db_session)
    async with _client(app_2fa) as c:
        await _password_login(c)
        r = await c.get("/admin/login/setup", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/admin/login/2fa"
        r = await c.post("/admin/login/setup", data={"code": "123456"}, follow_redirects=False)
        assert r.headers["location"] == "/admin/login/2fa"


# --- 2fa --------------------------------------------------------------------

async def test_2fa_login_and_replay_rejected(app_2fa, db_session):
    secret = await _enroll(db_session)
    code = pyotp.TOTP(secret).now()
    async with _client(app_2fa) as c:
        await _password_login(c)
        page = await c.get("/admin/login/2fa")
        assert page.status_code == 200
        r = await c.post("/admin/login/2fa", data={"code": code}, follow_redirects=False)
        assert r.headers["location"] == "/admin/"
        assert await _dashboard_status(c) == 200

    async with _client(app_2fa) as c:
        await _password_login(c)
        r = await c.post("/admin/login/2fa", data={"code": code}, follow_redirects=False)
        assert r.status_code == 200
        assert "Codice non valido" in r.text
        assert await _dashboard_status(c) == 302


async def test_2fa_without_pending_redirects_to_login(app_2fa, db_session):
    await _enroll(db_session)
    async with _client(app_2fa) as c:
        for path in ("/admin/login/2fa", "/admin/login/setup"):
            r = await c.get(path, follow_redirects=False)
            assert r.status_code == 302
            assert r.headers["location"] == "/admin/login"
        r = await c.post("/admin/login/2fa", data={"code": "123456"}, follow_redirects=False)
        assert r.headers["location"] == "/admin/login"


async def test_2fa_pending_expired(app_2fa, db_session, monkeypatch):
    from app import admin_2fa
    secret = await _enroll(db_session)
    async with _client(app_2fa) as c:
        await _password_login(c)
        monkeypatch.setattr(admin_2fa, "PENDING_TTL_SECONDS", -1)
        r = await c.post(
            "/admin/login/2fa",
            data={"code": pyotp.TOTP(secret).now()},
            follow_redirects=False,
        )
        assert r.headers["location"] == "/admin/login"
        assert await _dashboard_status(c) == 302


async def test_2fa_wrong_codes_ban_ip(app_2fa, db_session):
    await _enroll(db_session)
    async with _client(app_2fa) as c:
        await _password_login(c)
        statuses = []
        for _ in range(5):
            r = await c.post("/admin/login/2fa", data={"code": "000000"}, follow_redirects=False)
            statuses.append(r.status_code)
        assert statuses[-1] == 429
        assert "Troppi tentativi" in r.text
        r = await c.get("/admin/login/2fa")
        assert r.status_code == 429


async def test_2fa_undecryptable_secret_blocks_login(app_2fa, db_session):
    db_session.add(AdminTotp(id=1, secret_enc="garbage", confirmed_at=datetime.now(timezone.utc)))
    await db_session.commit()
    msg = "Secret 2FA non decifrabile (SESSION_SECRET cambiato?). Esegui il reset 2FA da console."
    async with _client(app_2fa) as c:
        r = await _password_login(c)
        assert r.headers["location"] == "/admin/login/2fa"
        page = await c.get("/admin/login/2fa")
        assert msg in page.text
        r = await c.post("/admin/login/2fa", data={"code": "123456"}, follow_redirects=False)
        assert msg in r.text
        r = await c.get("/admin/login/setup", follow_redirects=False)
        assert r.headers["location"] == "/admin/login/2fa"
        assert await _dashboard_status(c) == 302


# --- 2FA disattivato --------------------------------------------------------

async def test_disabled_password_only_and_routes_redirect(app_2fa, db_session, monkeypatch):
    await _enroll(db_session)
    monkeypatch.setenv("ADMIN_2FA_ENABLED", "false")
    async with _client(app_2fa) as c:
        r = await _password_login(c)
        assert r.headers["location"] == "/admin/"
        assert await _dashboard_status(c) == 200
        for path in ("/admin/login/2fa", "/admin/login/setup"):
            r = await c.get(path, follow_redirects=False)
            assert r.headers["location"] == "/admin/login"


# --- banner -----------------------------------------------------------------

BANNER_DISABLED = "2FA disattivato (ADMIN_2FA_ENABLED=false)"
BANNER_RESET = "ADMIN_2FA_RESET attivo"


async def test_banner_when_2fa_disabled(app_2fa, monkeypatch):
    monkeypatch.setenv("ADMIN_2FA_ENABLED", "false")
    async with _client(app_2fa) as c:
        await _password_login(c)
        page = await c.get("/admin/")
    assert BANNER_DISABLED in page.text


async def test_banner_when_reset_env_active(app_2fa, monkeypatch):
    monkeypatch.setenv("ADMIN_2FA_ENABLED", "false")
    monkeypatch.setenv("ADMIN_2FA_RESET", "true")
    async with _client(app_2fa) as c:
        await _password_login(c)
        page = await c.get("/admin/")
    assert BANNER_RESET in page.text


async def test_no_banner_when_2fa_enabled(app_2fa, db_session):
    secret = await _enroll(db_session)
    async with _client(app_2fa) as c:
        await _password_login(c)
        await c.post("/admin/login/2fa", data={"code": pyotp.TOTP(secret).now()})
        page = await c.get("/admin/")
    assert page.status_code == 200
    assert BANNER_DISABLED not in page.text
    assert BANNER_RESET not in page.text
