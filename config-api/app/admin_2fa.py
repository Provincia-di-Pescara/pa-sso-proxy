"""2FA TOTP per l'admin WebUI.

Logica pura (niente FastAPI): flag da env letti a runtime, cifratura del secret,
verifica codici con anti-replay, gestione della riga singleton admin_totp.
"""
import base64
import hmac
import logging
import os
import time
from datetime import datetime, timezone

import pyotp
import segno
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminTotp

logger = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 300
_HKDF_INFO = b"pa-sso-proxy admin-totp"
_VALID_WINDOW = 1


class TotpSecretError(Exception):
    """Il secret salvato non è decifrabile (SESSION_SECRET cambiato o dato corrotto)."""


def is_2fa_enabled() -> bool:
    return os.environ.get("ADMIN_2FA_ENABLED", "true").strip().lower() != "false"


def is_2fa_reset_requested() -> bool:
    return os.environ.get("ADMIN_2FA_RESET", "false").strip().lower() == "true"


def _fernet() -> Fernet:
    session_secret = os.environ.get("SESSION_SECRET", "changeme").encode()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO).derive(session_secret)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise TotpSecretError("secret TOTP non decifrabile") from exc


def pending_is_valid(pending: object, now: float | None = None) -> bool:
    if not isinstance(pending, dict):
        return False
    user, ts = pending.get("user"), pending.get("ts")
    if not user or not isinstance(ts, int):
        return False
    now = time.time() if now is None else now
    return 0 <= now - ts <= PENDING_TTL_SECONDS


async def get_totp(db: AsyncSession) -> AdminTotp | None:
    res = await db.execute(select(AdminTotp).where(AdminTotp.id == 1))
    return res.scalar_one_or_none()


async def get_or_create_pending(db: AsyncSession) -> tuple[AdminTotp, str]:
    """Secret per l'enrollment: riusa la riga non confermata (reload pagina = stesso QR).

    Una riga non confermata ma non decifrabile viene rigenerata: non è mai stata
    valida per il login, quindi rimpiazzarla non indebolisce nulla.
    """
    row = await get_totp(db)
    if row is not None and row.confirmed_at is not None:
        raise ValueError("TOTP admin già confermato")
    if row is not None:
        try:
            return row, decrypt_secret(row.secret_enc)
        except TotpSecretError:
            pass
    secret = pyotp.random_base32()
    if row is None:
        row = AdminTotp(id=1, secret_enc=encrypt_secret(secret))
        db.add(row)
    else:
        row.secret_enc = encrypt_secret(secret)
        row.last_used_counter = None
    await db.commit()
    return row, secret


def _matching_counter(secret: str, code: str, now: float) -> int | None:
    totp = pyotp.TOTP(secret)
    current = int(now // totp.interval)
    for counter in range(current - _VALID_WINDOW, current + _VALID_WINDOW + 1):
        if hmac.compare_digest(totp.generate_otp(counter), code):
            return counter
    return None


async def verify_code(db: AsyncSession, row: AdminTotp, code: str, now: float | None = None) -> bool:
    code = "".join(code.split())
    if len(code) != 6 or not code.isdigit():
        return False
    secret = decrypt_secret(row.secret_enc)
    counter = _matching_counter(secret, code, time.time() if now is None else now)
    if counter is None:
        return False
    if row.last_used_counter is not None and counter <= row.last_used_counter:
        return False
    row.last_used_counter = counter
    if row.confirmed_at is None:
        row.confirmed_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def reset_totp(db: AsyncSession) -> bool:
    res = await db.execute(delete(AdminTotp).execution_options(synchronize_session=False))
    await db.commit()
    db.expunge_all()
    return (res.rowcount or 0) > 0


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def qr_svg(uri: str) -> str:
    return segno.make(uri, error="m").svg_inline(scale=5)


async def apply_startup_flags(db: AsyncSession) -> None:
    if not is_2fa_enabled():
        logger.warning("ADMIN_2FA_ENABLED=false: 2FA admin DISATTIVATO — usare solo in sviluppo locale")
    if is_2fa_reset_requested():
        await reset_totp(db)
        logger.warning("ADMIN_2FA_RESET attivo: 2FA admin azzerato. Rimuovere la variabile.")
