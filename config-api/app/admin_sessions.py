"""Sessioni admin lato server e controlli trasversali su /admin.

Il cookie di sessione di Starlette è firmato ma NON cifrato e non revocabile:
chi ne ottiene una copia la usa fino a scadenza, e l'inattività registrata nel
cookie stesso si rinnova da sola. Qui il cookie porta solo un `sid` casuale;
validità, ultima attività e durata massima stanno in memoria nel processo.

- logout = revoca immediata (un cookie copiato smette di valere);
- inattività (`SESSION_MAX_AGE`) e durata massima assoluta
  (`ADMIN_SESSION_MAX_LIFETIME`, default 8 h) misurate lato server;
- riavvio di config-api = tutte le sessioni admin chiuse.

Vincolo: config-api gira con UN processo uvicorn (Dockerfile, CMD senza
--workers). Con più worker il registro andrebbe spostato in DB/redis.

`guard_request` è usato dal middleware in `app.main`:
- CSRF: richieste non sicure su /admin da un'altra origine → 403
  (Sec-Fetch-Site, poi Origin, poi Referer; senza nessuno dei tre la richiesta
  non viene da un browser e non può essere CSRF);
- ogni /admin non pubblico senza sessione valida → redirect al login, anche
  se la route si dimentica il proprio controllo.
"""
from __future__ import annotations

import os
import secrets
import time
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


IDLE_TIMEOUT = int(os.environ.get("SESSION_MAX_AGE", 1800))
ABSOLUTE_LIFETIME = int(os.environ.get("ADMIN_SESSION_MAX_LIFETIME", 8 * 3600))

PUBLIC_PREFIXES = ("/admin/login", "/admin/static")
PUBLIC_PATHS = ("/admin/logout",)
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# sid → {"user", "created", "last_seen"}
_SESSIONS: dict[str, dict] = {}


def _now() -> float:
    return time.time()


def start(request: Request, user: str) -> None:
    """Login completato: nuova sessione (sid nuovo, niente fixation)."""
    request.session.clear()
    sid = secrets.token_urlsafe(32)
    now = _now()
    _SESSIONS[sid] = {"user": user, "created": now, "last_seen": now}
    request.session["user"] = user
    request.session["sid"] = sid


def end(request: Request) -> None:
    sid = request.session.get("sid")
    if sid:
        _SESSIONS.pop(sid, None)
    request.session.clear()


def revoke_all() -> None:
    _SESSIONS.clear()


def _validate(request: Request) -> str | None:
    """'ok', 'timeout' o None (nessuna sessione / sessione sconosciuta)."""
    user = request.session.get("user")
    sid = request.session.get("sid")
    if not user or not sid:
        return None
    entry = _SESSIONS.get(sid)
    if entry is None or entry["user"] != user:
        return None
    now = _now()
    if now - entry["last_seen"] > IDLE_TIMEOUT or now - entry["created"] > ABSOLUTE_LIFETIME:
        _SESSIONS.pop(sid, None)
        return "timeout"
    entry["last_seen"] = now
    return "ok"


def _host(url: str) -> str | None:
    try:
        return urlsplit(url).netloc.lower() or None
    except ValueError:
        return None


def _cross_origin(request: Request) -> bool:
    expected = (request.headers.get("host") or "").lower()
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        return True
    origin = request.headers.get("origin")
    if origin is not None:
        # Si confronta solo l'host: dietro il reverse proxy lo schema visto da
        # config-api è http anche se il browser usa https.
        return origin == "null" or _host(origin) != expected
    referer = request.headers.get("referer")
    if referer is not None:
        return _host(referer) != expected
    return False


def guard_request(request: Request) -> Response | None:
    path = request.url.path
    if not path.startswith("/admin"):
        return None
    if request.method in UNSAFE_METHODS and _cross_origin(request):
        return PlainTextResponse("Richiesta da un'altra origine rifiutata", status_code=403)
    if path.startswith(PUBLIC_PREFIXES) or path in PUBLIC_PATHS:
        return None
    state = _validate(request)
    if state == "ok":
        return None
    # Solo le chiavi della sessione autenticata: un login 2FA in corso
    # (pending_2fa) deve sopravvivere a una visita a una pagina protetta.
    request.session.pop("user", None)
    request.session.pop("sid", None)
    target = "/admin/login?timeout=1" if state == "timeout" else "/admin/login"
    return RedirectResponse(target, status_code=302)
