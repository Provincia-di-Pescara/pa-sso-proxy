import time
from datetime import datetime, timezone

import pyotp
import pytest

from app import admin_2fa
from app.models import AdminTotp


@pytest.fixture(autouse=True)
def _secret_env(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")


# --- flag -------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (None, True), ("true", True), ("1", True), ("", True),
    ("false", False), ("FALSE", False), (" False ", False),
])
def test_is_2fa_enabled(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("ADMIN_2FA_ENABLED", raising=False)
    else:
        monkeypatch.setenv("ADMIN_2FA_ENABLED", value)
    assert admin_2fa.is_2fa_enabled() is expected


@pytest.mark.parametrize("value,expected", [
    (None, False), ("false", False), ("1", False), ("true", True), ("TRUE", True),
])
def test_is_2fa_reset_requested(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("ADMIN_2FA_RESET", raising=False)
    else:
        monkeypatch.setenv("ADMIN_2FA_RESET", value)
    assert admin_2fa.is_2fa_reset_requested() is expected


# --- cifratura --------------------------------------------------------------

def test_encrypt_decrypt_roundtrip():
    token = admin_2fa.encrypt_secret("JBSWY3DPEHPK3PXP")
    assert token != "JBSWY3DPEHPK3PXP"
    assert admin_2fa.decrypt_secret(token) == "JBSWY3DPEHPK3PXP"


def test_decrypt_with_other_session_secret_fails(monkeypatch):
    token = admin_2fa.encrypt_secret("JBSWY3DPEHPK3PXP")
    monkeypatch.setenv("SESSION_SECRET", "another-secret-entirely-different")
    with pytest.raises(admin_2fa.TotpSecretError):
        admin_2fa.decrypt_secret(token)


def test_decrypt_garbage_fails():
    with pytest.raises(admin_2fa.TotpSecretError):
        admin_2fa.decrypt_secret("not-a-token")


# --- pending ----------------------------------------------------------------

def test_pending_is_valid():
    now = 1_000_000.0
    assert admin_2fa.pending_is_valid({"user": "admin", "ts": 1_000_000 - 10}, now=now)
    assert not admin_2fa.pending_is_valid({"user": "admin", "ts": 1_000_000 - 301}, now=now)
    assert not admin_2fa.pending_is_valid({"user": "admin", "ts": 1_000_000 + 5}, now=now)
    assert not admin_2fa.pending_is_valid(None, now=now)
    assert not admin_2fa.pending_is_valid({"ts": 1_000_000}, now=now)
    assert not admin_2fa.pending_is_valid({"user": "admin", "ts": "x"}, now=now)


# --- DB ---------------------------------------------------------------------

async def test_get_or_create_pending_creates_and_reuses(db_session):
    row, secret = await admin_2fa.get_or_create_pending(db_session)
    assert row.id == 1
    assert row.confirmed_at is None
    assert admin_2fa.decrypt_secret(row.secret_enc) == secret

    row2, secret2 = await admin_2fa.get_or_create_pending(db_session)
    assert secret2 == secret


async def test_get_or_create_pending_replaces_undecryptable_unconfirmed(db_session):
    db_session.add(AdminTotp(id=1, secret_enc="garbage"))
    await db_session.commit()
    row, secret = await admin_2fa.get_or_create_pending(db_session)
    assert admin_2fa.decrypt_secret(row.secret_enc) == secret


async def test_get_or_create_pending_refuses_confirmed(db_session):
    db_session.add(AdminTotp(
        id=1,
        secret_enc=admin_2fa.encrypt_secret(pyotp.random_base32()),
        confirmed_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()
    with pytest.raises(ValueError):
        await admin_2fa.get_or_create_pending(db_session)


async def test_verify_code_confirms_and_blocks_replay(db_session):
    row, secret = await admin_2fa.get_or_create_pending(db_session)
    now = time.time()
    code = pyotp.TOTP(secret).at(now)

    assert await admin_2fa.verify_code(db_session, row, code, now=now) is True
    assert row.confirmed_at is not None
    assert row.last_used_counter == int(now // 30)

    # stesso codice → replay rifiutato
    assert await admin_2fa.verify_code(db_session, row, code, now=now) is False


async def test_verify_code_window(db_session):
    row, secret = await admin_2fa.get_or_create_pending(db_session)
    now = time.time()
    totp = pyotp.TOTP(secret)
    assert await admin_2fa.verify_code(db_session, row, totp.at(now - 30), now=now) is True
    row.last_used_counter = None
    assert await admin_2fa.verify_code(db_session, row, totp.at(now - 90), now=now) is False


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 34 5x"])
async def test_verify_code_rejects_malformed(db_session, bad):
    row, _ = await admin_2fa.get_or_create_pending(db_session)
    assert await admin_2fa.verify_code(db_session, row, bad) is False


async def test_verify_code_accepts_spaces(db_session):
    row, secret = await admin_2fa.get_or_create_pending(db_session)
    now = time.time()
    code = pyotp.TOTP(secret).at(now)
    assert await admin_2fa.verify_code(db_session, row, f" {code[:3]} {code[3:]} ", now=now) is True


async def test_verify_code_undecryptable_raises(db_session):
    db_session.add(AdminTotp(id=1, secret_enc="garbage", confirmed_at=datetime.now(timezone.utc)))
    await db_session.commit()
    row = await admin_2fa.get_totp(db_session)
    with pytest.raises(admin_2fa.TotpSecretError):
        await admin_2fa.verify_code(db_session, row, "123456")


async def test_reset_totp(db_session):
    assert await admin_2fa.reset_totp(db_session) is False
    await admin_2fa.get_or_create_pending(db_session)
    assert await admin_2fa.reset_totp(db_session) is True
    assert await admin_2fa.get_totp(db_session) is None


async def test_apply_startup_flags_reset(db_session, monkeypatch, caplog):
    await admin_2fa.get_or_create_pending(db_session)
    monkeypatch.setenv("ADMIN_2FA_RESET", "true")
    await admin_2fa.apply_startup_flags(db_session)
    assert await admin_2fa.get_totp(db_session) is None
    assert "ADMIN_2FA_RESET" in caplog.text


async def test_apply_startup_flags_disabled_keeps_row(db_session, monkeypatch, caplog):
    await admin_2fa.get_or_create_pending(db_session)
    monkeypatch.setenv("ADMIN_2FA_ENABLED", "false")
    monkeypatch.delenv("ADMIN_2FA_RESET", raising=False)
    await admin_2fa.apply_startup_flags(db_session)
    assert await admin_2fa.get_totp(db_session) is not None
    assert "ADMIN_2FA_ENABLED=false" in caplog.text


# --- QR / URI ---------------------------------------------------------------

def test_provisioning_uri_and_qr():
    uri = admin_2fa.provisioning_uri("JBSWY3DPEHPK3PXP", "admin", "Provincia di Pescara")
    assert uri.startswith("otpauth://totp/")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=Provincia%20di%20Pescara" in uri
    svg = admin_2fa.qr_svg(uri)
    assert svg.lstrip().startswith("<svg")
