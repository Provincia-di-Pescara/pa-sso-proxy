"""Backup cifrato: formato, rifiuto dei backup in chiaro, riautenticazione."""
import base64
import json
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from app import backup_crypto
from app.backup_crypto import BackupCryptoError, decrypt_bundle, encrypt_bundle
from app.database import get_db
from app.models import AdminTotp, OIDCClient

PASS = "una-passphrase-abbastanza-lunga"
BUNDLE = {"version": "1", "oidc_clients": [{"client_id": "x", "client_secret_plain": "s3cr3t"}]}


# --- formato ------------------------------------------------------------------

def test_round_trip_and_no_plaintext():
    raw = encrypt_bundle(BUNDLE, PASS)
    assert b"s3cr3t" not in raw
    env = json.loads(raw)
    assert env["format"] == "pa-sso-proxy-backup" and env["kdf"]["name"] == "scrypt"
    assert decrypt_bundle(raw, PASS) == BUNDLE


def test_wrong_passphrase():
    raw = encrypt_bundle(BUNDLE, PASS)
    with pytest.raises(BackupCryptoError, match="Passphrase errata"):
        decrypt_bundle(raw, PASS + "x")


def test_tampered_ciphertext_and_header():
    env = json.loads(encrypt_bundle(BUNDLE, PASS))
    ct = bytearray(base64.b64decode(env["ciphertext"]))
    ct[0] ^= 1
    bad = dict(env, ciphertext=base64.b64encode(bytes(ct)).decode())
    with pytest.raises(BackupCryptoError):
        decrypt_bundle(json.dumps(bad).encode(), PASS)
    # header autenticato: parametro KDF cambiato (ma lecito) → chiave diversa / AAD diverso
    bad = dict(env, kdf=dict(env["kdf"], p=2))
    with pytest.raises(BackupCryptoError):
        decrypt_bundle(json.dumps(bad).encode(), PASS)


def test_plaintext_backup_rejected():
    raw = json.dumps(BUNDLE).encode()
    with pytest.raises(BackupCryptoError, match="in chiaro"):
        decrypt_bundle(raw, PASS)


@pytest.mark.parametrize("kdf", [
    {"name": "scrypt", "n": 2 ** 24, "r": 8, "p": 1},
    {"name": "scrypt", "n": 1000, "r": 8, "p": 1},
    {"name": "scrypt", "n": 2 ** 14, "r": 64, "p": 1},
    {"name": "scrypt", "n": 2 ** 14, "r": 8, "p": 100},
    {"name": "pbkdf2", "n": 2 ** 14, "r": 8, "p": 1},
])
def test_kdf_limits(kdf):
    env = json.loads(encrypt_bundle(BUNDLE, PASS))
    env["kdf"] = dict(kdf, salt=env["kdf"]["salt"])
    with pytest.raises(BackupCryptoError):
        decrypt_bundle(json.dumps(env).encode(), PASS)


@pytest.mark.parametrize("passphrase,confirm", [("corta", "corta"), (PASS, PASS + "!")])
def test_check_passphrase(passphrase, confirm):
    with pytest.raises(BackupCryptoError):
        backup_crypto.check_passphrase(passphrase, confirm)


# --- route ---------------------------------------------------------------------

@pytest.fixture
def app_backup(db_session, monkeypatch):
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


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _login(c):
    await c.post("/admin/login", data={"username": "admin", "password": "secret"})


async def _flash_error(c) -> str:
    return (await c.get("/admin/backup")).text


async def test_get_export_does_not_download(app_backup):
    async with _client(app_backup) as c:
        await _login(c)
        r = await c.get("/admin/backup/export", follow_redirects=False)
        assert r.status_code == 302
        assert "attachment" not in r.headers.get("content-disposition", "")


@pytest.mark.parametrize("form,err", [
    ({"passphrase": PASS, "passphrase_confirm": PASS, "password": "sbagliata"}, "Password non valida"),
    ({"passphrase": "corta", "passphrase_confirm": "corta", "password": "secret"}, "almeno"),
    ({"passphrase": PASS, "passphrase_confirm": PASS + "x", "password": "secret"}, "non coincidono"),
])
async def test_export_rejected(app_backup, form, err):
    async with _client(app_backup) as c:
        await _login(c)
        r = await c.post("/admin/backup/export", data=form, follow_redirects=False)
        assert r.status_code == 302
        assert err in await _flash_error(c)


async def test_export_is_encrypted(app_backup, db_session):
    db_session.add(OIDCClient(client_id="c1", client_secret_hash="h", client_secret_plain="segreto-client",
                              name="C1", redirect_uris=["https://a.example/cb"], allowed_scopes=["openid"]))
    await db_session.commit()
    async with _client(app_backup) as c:
        await _login(c)
        r = await c.post("/admin/backup/export",
                         data={"passphrase": PASS, "passphrase_confirm": PASS, "password": "secret"})
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"
        assert b"segreto-client" not in r.content
        assert decrypt_bundle(r.content, PASS)["oidc_clients"][0]["client_secret_plain"] == "segreto-client"


async def test_import_requires_step_up_and_rejects_plaintext(app_backup):
    with patch("app.routes.backup._restore_bundle", new_callable=AsyncMock) as restore:
        async with _client(app_backup) as c:
            await _login(c)
            # password errata: nessun ripristino, anche con file e passphrase giusti
            await c.post("/admin/backup/import",
                         files={"file": ("b.json", encrypt_bundle(BUNDLE, PASS), "application/json")},
                         data={"passphrase": PASS, "password": "sbagliata"})
            assert "Password non valida" in await _flash_error(c)
            # backup in chiaro
            await c.post("/admin/backup/import",
                         files={"file": ("b.json", json.dumps(BUNDLE).encode(), "application/json")},
                         data={"passphrase": PASS, "password": "secret"})
            assert "in chiaro" in await _flash_error(c)
            # passphrase errata
            await c.post("/admin/backup/import",
                         files={"file": ("b.json", encrypt_bundle(BUNDLE, PASS), "application/json")},
                         data={"passphrase": "altra-passphrase-lunga", "password": "secret"})
            assert "Passphrase errata" in await _flash_error(c)
        restore.assert_not_called()


async def test_step_up_requires_fresh_totp(app_backup, db_session, monkeypatch):
    from app import admin_2fa
    monkeypatch.setenv("ADMIN_2FA_ENABLED", "true")
    secret = pyotp.random_base32()
    db_session.add(AdminTotp(id=1, secret_enc=admin_2fa.encrypt_secret(secret),
                             confirmed_at=datetime.now(timezone.utc)))
    await db_session.commit()
    form = {"passphrase": PASS, "passphrase_confirm": PASS, "password": "secret"}
    async with _client(app_backup) as c:
        await c.post("/admin/login", data={"username": "admin", "password": "secret"})
        code = pyotp.TOTP(secret).now()
        await c.post("/admin/login/2fa", data={"code": code})
        # stesso codice del login: rifiutato (replay)
        r = await c.post("/admin/backup/export", data=dict(form, code=code), follow_redirects=False)
        assert r.status_code == 302
        # senza codice: rifiutato
        r = await c.post("/admin/backup/export", data=form, follow_redirects=False)
        assert r.status_code == 302
        # codice della finestra successiva: accettato
        import time
        nxt = pyotp.TOTP(secret).at(time.time() + 30)
        r = await c.post("/admin/backup/export", data=dict(form, code=nxt))
        assert r.status_code == 200
        assert decrypt_bundle(r.content, PASS)["version"] == "1"
