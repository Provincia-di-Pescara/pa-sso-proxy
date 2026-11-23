"""Riautenticazione (step-up) per le operazioni più sensibili della WebUI.

Una sessione admin rubata (cookie copiato, postazione lasciata aperta) non
basta per esportare o sostituire chiavi e configurazione: serve di nuovo la
password admin e, con il 2FA attivo, un codice TOTP nuovo (i codici già usati
sono rifiutati, anche quello del login appena fatto).

I fallimenti contano nel ban per IP del login (rate_limiter).
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import admin_2fa
from app.rate_limiter import clear_attempts, is_ip_banned, record_failed_attempt

logger = logging.getLogger(__name__)


def client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


async def verify(request: Request, db: AsyncSession, password: str, code: str, action: str) -> str | None:
    """None se la riautenticazione è valida, altrimenti il messaggio d'errore."""
    ip = client_ip(request)
    user = request.session.get("user") or "?"
    banned, remaining = await is_ip_banned(db, ip)
    if banned:
        return f"Troppi tentativi falliti. Riprova tra {remaining} minuti."

    expected = os.environ.get("ADMIN_PASSWORD", "")
    ok = bool(expected) and hmac.compare_digest(password.encode(), expected.encode())
    if ok and admin_2fa.is_2fa_enabled():
        row = await admin_2fa.get_totp(db)
        try:
            ok = row is not None and row.confirmed_at is not None and await admin_2fa.verify_code(db, row, code)
        except admin_2fa.TotpSecretError:
            ok = False

    if not ok:
        await record_failed_attempt(db, ip)
        logger.warning("step-up fallito: azione=%s utente=%s ip=%s", action, user, ip)
        if admin_2fa.is_2fa_enabled():
            return "Password o codice 2FA non validi (serve un codice nuovo, non quello già usato)."
        return "Password non valida."

    await clear_attempts(db, ip)
    logger.warning("step-up riuscito: azione=%s utente=%s ip=%s", action, user, ip)
    return None
