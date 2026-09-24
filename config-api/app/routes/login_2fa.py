"""Secondo fattore TOTP per il login admin: /admin/login/2fa e /admin/login/setup.

`session["user"]` viene impostato SOLO qui, dopo un codice valido: tutte le route
admin esistenti (che controllano session["user"]) restano protette senza modifiche.
"""
import time

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import admin_2fa
from app.database import get_db
from app.jinja_templates import templates
from app.models import EnteSettings
from app.rate_limiter import clear_attempts, is_ip_banned, record_failed_attempt

router = APIRouter()

DECRYPT_ERROR = "Secret 2FA non decifrabile (SESSION_SECRET cambiato?). Esegui il reset 2FA da console."
DEFAULT_ISSUER = "PA SSO Proxy"


def _client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def _ban_message(remaining: int) -> str:
    return f"Troppi tentativi falliti. Riprova tra {remaining} minut{'o' if remaining == 1 else 'i'}."


async def _settings(db: AsyncSession) -> EnteSettings | None:
    return (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302)


def _pending_user(request: Request) -> str | None:
    pending = request.session.get("pending_2fa")
    return pending["user"] if admin_2fa.pending_is_valid(pending) else None


def _back_to_login(request: Request) -> RedirectResponse:
    request.session.clear()
    return _redirect("/admin/login")


def _complete_login(request: Request, user: str) -> RedirectResponse:
    request.session.clear()
    request.session["user"] = user
    request.session["last_activity"] = int(time.time())
    return _redirect("/admin/")


async def _render(request: Request, db: AsyncSession, template: str, status_code: int = 200, **ctx):
    ctx.setdefault("error", None)
    ctx.setdefault("banned", False)
    ctx.setdefault("blocked", False)
    ctx["s"] = await _settings(db)
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


async def _setup_context(db: AsyncSession, user: str, secret: str) -> dict:
    s = await _settings(db)
    issuer = (s.org_display_name or s.org_name) if s else ""
    uri = admin_2fa.provisioning_uri(secret, user, issuer or DEFAULT_ISSUER)
    return {
        "qr_svg": admin_2fa.qr_svg(uri),
        "secret_display": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
    }


async def _failed_code(request: Request, db: AsyncSession, template: str, **ctx):
    ip = _client_ip(request)
    await record_failed_attempt(db, ip)
    banned, remaining = await is_ip_banned(db, ip)
    if banned:
        return await _render(request, db, template, status_code=429, error=_ban_message(remaining), banned=True, **ctx)
    return await _render(request, db, template, error="Codice non valido", **ctx)


# --- /admin/login/2fa -------------------------------------------------------

@router.get("/login/2fa")
async def twofa_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not admin_2fa.is_2fa_enabled():
        return _redirect("/admin/login")
    user = _pending_user(request)
    if user is None:
        return _back_to_login(request)
    row = await admin_2fa.get_totp(db)
    if row is None or row.confirmed_at is None:
        return _redirect("/admin/login/setup")
    try:
        admin_2fa.decrypt_secret(row.secret_enc)
    except admin_2fa.TotpSecretError:
        return await _render(request, db, "login_2fa.html.j2", error=DECRYPT_ERROR, blocked=True)
    banned, remaining = await is_ip_banned(db, _client_ip(request))
    if banned:
        return await _render(request, db, "login_2fa.html.j2", status_code=429, error=_ban_message(remaining), banned=True)
    return await _render(request, db, "login_2fa.html.j2")


@router.post("/login/2fa")
async def twofa_submit(request: Request, code: str = Form(""), db: AsyncSession = Depends(get_db)):
    if not admin_2fa.is_2fa_enabled():
        return _redirect("/admin/login")
    user = _pending_user(request)
    if user is None:
        return _back_to_login(request)
    row = await admin_2fa.get_totp(db)
    if row is None or row.confirmed_at is None:
        return _redirect("/admin/login/setup")
    ip = _client_ip(request)
    banned, remaining = await is_ip_banned(db, ip)
    if banned:
        return await _render(request, db, "login_2fa.html.j2", status_code=429, error=_ban_message(remaining), banned=True)
    try:
        ok = await admin_2fa.verify_code(db, row, code)
    except admin_2fa.TotpSecretError:
        return await _render(request, db, "login_2fa.html.j2", error=DECRYPT_ERROR, blocked=True)
    if not ok:
        return await _failed_code(request, db, "login_2fa.html.j2")
    await clear_attempts(db, ip)
    return _complete_login(request, user)


# --- /admin/login/setup (enrollment forzato) --------------------------------

@router.get("/login/setup")
async def setup_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not admin_2fa.is_2fa_enabled():
        return _redirect("/admin/login")
    user = _pending_user(request)
    if user is None:
        return _back_to_login(request)
    row = await admin_2fa.get_totp(db)
    if row is not None and row.confirmed_at is not None:
        return _redirect("/admin/login/2fa")
    _, secret = await admin_2fa.get_or_create_pending(db)
    ctx = await _setup_context(db, user, secret)
    banned, remaining = await is_ip_banned(db, _client_ip(request))
    if banned:
        return await _render(request, db, "login_setup.html.j2", status_code=429, error=_ban_message(remaining), banned=True, **ctx)
    return await _render(request, db, "login_setup.html.j2", **ctx)


@router.post("/login/setup")
async def setup_submit(request: Request, code: str = Form(""), db: AsyncSession = Depends(get_db)):
    if not admin_2fa.is_2fa_enabled():
        return _redirect("/admin/login")
    user = _pending_user(request)
    if user is None:
        return _back_to_login(request)
    row = await admin_2fa.get_totp(db)
    if row is not None and row.confirmed_at is not None:
        return _redirect("/admin/login/2fa")
    row, secret = await admin_2fa.get_or_create_pending(db)
    ctx = await _setup_context(db, user, secret)
    ip = _client_ip(request)
    banned, remaining = await is_ip_banned(db, ip)
    if banned:
        return await _render(request, db, "login_setup.html.j2", status_code=429, error=_ban_message(remaining), banned=True, **ctx)
    if not await admin_2fa.verify_code(db, row, code):
        return await _failed_code(request, db, "login_setup.html.j2", **ctx)
    await clear_attempts(db, ip)
    return _complete_login(request, user)
