"""Scope e claim chiesti dagli applicativi ma tolti dal filtro per client.

Il frontend OIDC di SATOSA (oidc_frontend_ext.py generato) toglie dalla
richiesta gli scope e i claim fuori dagli `allowed_scopes` del client e lo
segnala qui (POST /internal/scope-rejected). La dashboard mostra un avviso:
un applicativo che chiede `legal_entity` senza averlo consentito fa login
come persona fisica senza nessun errore visibile.

Stato in memoria del processo (config-api gira con un solo worker, come le
sessioni admin): si perde al riavvio e ricompare alla richiesta successiva.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

WINDOW = timedelta(days=7)
_MAX_CLIENTS = 200
_MAX_ITEMS_PER_CLIENT = 50
_MAX_NAMES_PER_REPORT = 20
_MAX_LEN = 64

_lock = threading.Lock()
# client_id -> {(tipo, nome): {"count": int, "last_seen": datetime}}
_store: dict[str, dict[tuple[str, str], dict]] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(values) -> list[str]:
    out: list[str] = []
    for value in (values or [])[:_MAX_NAMES_PER_REPORT]:
        if isinstance(value, str) and value.strip():
            out.append(value.strip()[:_MAX_LEN])
    return out


def _prune(now: datetime) -> None:
    limit = now - WINDOW
    for client_id in list(_store):
        items = _store[client_id]
        for key in [k for k, v in items.items() if v["last_seen"] < limit]:
            del items[key]
        if not items:
            del _store[client_id]


def record(client_id: str, scopes, claims, now: datetime | None = None) -> None:
    now = now or _now()
    client_id = (client_id or "").strip()[:256]
    entries = [("scope", s) for s in _clean(scopes)] + [("claim", c) for c in _clean(claims)]
    if not client_id or not entries:
        return
    with _lock:
        _prune(now)
        if client_id not in _store and len(_store) >= _MAX_CLIENTS:
            return
        items = _store.setdefault(client_id, {})
        for key in entries:
            if key not in items and len(items) >= _MAX_ITEMS_PER_CLIENT:
                continue
            item = items.setdefault(key, {"count": 0, "last_seen": now})
            item["count"] += 1
            item["last_seen"] = now


def recent(now: datetime | None = None) -> list[dict]:
    """Client con scope/claim tolti negli ultimi 7 giorni, il più recente prima."""
    now = now or _now()
    with _lock:
        _prune(now)
        result = []
        for client_id, items in _store.items():
            rows = sorted(
                ({"kind": k, "name": n, **v} for (k, n), v in items.items()),
                key=lambda r: (r["kind"] != "scope", r["name"]),
            )
            result.append({
                "client_id": client_id,
                "items": rows,
                "last_seen": max(r["last_seen"] for r in rows),
            })
    return sorted(result, key=lambda r: r["last_seen"], reverse=True)


def clear(client_id: str) -> None:
    """Dopo il salvataggio del client: l'avviso ricompare solo se il problema resta."""
    with _lock:
        _store.pop(client_id, None)


def reset() -> None:
    with _lock:
        _store.clear()
