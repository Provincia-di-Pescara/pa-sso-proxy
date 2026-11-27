"""Pannello admin IT-Wallet (verifier OpenID4VP): configurazione, chiavi, onboarding, trust mark.

Rigenerare le chiavi non cancella le vecchie: restano in `jwk_keys` (nome
`itwallet-<ruolo>-<suffisso>`) come storico e si riattivano da pannello, quindi
chiavi e attivazione chiedono solo una conferma. Ogni modifica che cambia la
config generata rigenera e ricarica SATOSA come eIDAS. Il generatore applica comunque
`itwallet_ready`: un wallet acceso ma incompleto non produce config rotta.
"""
import asyncio
import base64
import binascii
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import itwallet_backend_config as itw
from app.database import get_db
from app.itwallet_csr import CsrError, build_csr
from app.jinja_templates import templates
from app.jwk_generator import generate_ec_jwk
from app.models import EnteSettings, ItWalletConfig, JwkKey
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

logger = logging.getLogger(__name__)

router = APIRouter()

PANEL = "/admin/itwallet"
KEY_FK = {"federation": "jwk_federation_id", "sig": "jwk_sig_id", "enc": "jwk_enc_id"}
KEY_NAME_PREFIX = "itwallet-"
PUBLIC_EC_MEMBERS = ("kty", "crv", "x", "y", "kid", "use", "alg")
PRIVATE_JWK_MEMBERS = ("d", "p", "q", "dp", "dq", "qi", "k", "oth")
ENVIRONMENT_LABELS = {
    "collaudo": "Collaudo",
    "produzione": "Produzione",
    "personalizzato": "Personalizzato (lab)",
}
MAX_TRUST_MARK_LEN = 16 * 1024
MAX_JWKS_LEN = 64 * 1024
MAX_URL_LEN = 2048
_URL_FORBIDDEN = frozenset('\\<>"\'`')
EC_FETCH_TIMEOUT = 3.0

_FLASH_KEYS = ("itwallet_ok", "itwallet_err", "itwallet_warn")


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


def _redirect(tab: str) -> RedirectResponse:
    return RedirectResponse(f"{PANEL}#{tab}", status_code=302)


def _flash(request: Request, kind: str, message: str, tab: str) -> RedirectResponse:
    request.session[f"itwallet_{kind}"] = message
    return _redirect(tab)


async def _get_config(db: AsyncSession) -> ItWalletConfig | None:
    return (await db.execute(select(ItWalletConfig).where(ItWalletConfig.id == 1))).scalar_one_or_none()


async def _get_or_create_config(db: AsyncSession) -> ItWalletConfig:
    cfg = await _get_config(db)
    if cfg is None:
        cfg = ItWalletConfig(id=1, enabled=False)
        db.add(cfg)
    return cfg


async def _get_settings(db: AsyncSession) -> EnteSettings | None:
    return (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()


def _hostname(settings: EnteSettings | None) -> str:
    return (settings.proxy_hostname if settings else "") or os.environ.get("PROXY_HOSTNAME", "")


def _absolute_url(value: str, hostname: str) -> str:
    """URL dei dati ente per i metadata del verifier: un path relativo diventa https://<host>/path."""
    value = (value or "").strip()
    if value.startswith("/") and not value.startswith("//") and hostname:
        return f"https://{hostname}{value}"
    return value


async def _load_keys(db: AsyncSession, cfg: ItWalletConfig | None) -> dict[str, JwkKey]:
    keys: dict[str, JwkKey] = {}
    if cfg is None:
        return keys
    for role, attr in KEY_FK.items():
        key_id = getattr(cfg, attr)
        if key_id:
            row = (await db.execute(select(JwkKey).where(JwkKey.id == key_id))).scalar_one_or_none()
            if row is not None:
                keys[role] = row
    return keys


def _key_set_parts(name: str) -> tuple[str, str] | None:
    """`itwallet-<ruolo>-<suffisso>` -> (ruolo, suffisso); il suffisso identifica il set generato insieme."""
    if not name.startswith(KEY_NAME_PREFIX):
        return None
    role, sep, suffix = name[len(KEY_NAME_PREFIX):].rpartition("-")
    return (role, suffix) if sep and role in KEY_FK and suffix else None


async def _archived_key_sets(db: AsyncSession, cfg: ItWalletConfig | None) -> list[dict]:
    """Set completi di chiavi IT-Wallet non in uso, dal più recente: [{suffix, created_at, kid, keys}]."""
    current = {getattr(cfg, attr) for attr in KEY_FK.values()} if cfg else set()
    rows = (await db.execute(
        select(JwkKey).where(JwkKey.name.startswith(KEY_NAME_PREFIX))
    )).scalars().all()
    sets: dict[str, dict[str, JwkKey]] = {}
    for row in rows:
        parts = _key_set_parts(row.name)
        if parts is None or row.id in current:
            continue
        role, suffix = parts
        sets.setdefault(suffix, {})[role] = row
    result = []
    for suffix, keys in sets.items():
        if set(keys) != set(KEY_FK):
            continue
        fed = keys["federation"]
        result.append({
            "suffix": suffix,
            "created_at": fed.created_at,
            "kid": (fed.public_jwk or {}).get("kid", ""),
            "keys": keys,
        })
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    result.sort(key=lambda s: s["created_at"] or epoch, reverse=True)
    return result


def _public_federation_jwks(keys: dict[str, JwkKey]) -> dict:
    fed = keys.get("federation")
    if fed is None or not fed.public_jwk:
        return {"keys": []}
    return {"keys": [{m: fed.public_jwk[m] for m in PUBLIC_EC_MEMBERS if m in fed.public_jwk}]}


async def _regenerate(db: AsyncSession) -> None:
    try:
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    except Exception:
        logger.warning("generate_and_write fallito dopo modifica IT-Wallet", exc_info=True)


# --- JWT (trust mark, entity configuration): decodifica senza verifica ---------

def _b64url_json(segment: str) -> dict:
    padded = segment + "=" * (-len(segment) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("payload non è un oggetto JSON")
    return value


def _decode_jws(token: str) -> tuple[dict, dict]:
    """(header, payload) di un JWS compatto. ValueError se non valido. Firma NON verificata."""
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError("non è un JWT (servono tre parti separate da punto)")
    try:
        return _b64url_json(parts[0]), _b64url_json(parts[1])
    except (ValueError, UnicodeError, binascii.Error) as e:
        raise ValueError("header o payload non decodificabili") from e


def _trust_mark_view(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        header, payload = _decode_jws(token)
    except ValueError as e:
        return {"error": str(e)}
    view = {
        "header_json": json.dumps(header, indent=2, ensure_ascii=False),
        "payload_json": json.dumps(payload, indent=2, ensure_ascii=False),
        "id": payload.get("id") or payload.get("trust_mark_id") or "",
        "iss": payload.get("iss") or "",
        "sub": payload.get("sub") or "",
        "exp": None,
        "expired": False,
    }
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and not isinstance(exp, bool):
        try:
            exp_dt = datetime.fromtimestamp(exp, timezone.utc)
        except (OverflowError, OSError, ValueError):
            exp_dt = None
        if exp_dt is not None:
            view["exp"] = exp_dt
            view["expired"] = exp_dt <= datetime.now(timezone.utc)
    return view


async def _fetch_entity_configuration() -> str:
    """JWT della Entity Configuration servita da SATOSA (rete interna)."""
    satosa_url = os.environ.get("SATOSA_INTERNAL_URL", "http://satosa:8080").rstrip("/")
    async with httpx.AsyncClient(timeout=EC_FETCH_TIMEOUT) as client:
        resp = await client.get(f"{satosa_url}{itw.entity_configuration_path()}")
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code} da SATOSA")
    return resp.text.strip()


async def _entity_configuration_preview(cfg: ItWalletConfig | None) -> dict:
    if cfg is None or not cfg.enabled:
        return {"error": "IT-Wallet non attivo: la Entity Configuration non è pubblicata."}
    try:
        token = await _fetch_entity_configuration()
        header, payload = _decode_jws(token)
    except Exception as e:
        logger.info("anteprima Entity Configuration IT-Wallet non disponibile: %s", e)
        return {"error": "Entity Configuration non disponibile al momento (SATOSA non raggiungibile "
                         "o backend non ancora caricato). Riprova tra qualche secondo."}
    return {
        "header_json": json.dumps(header, indent=2, ensure_ascii=False),
        "payload_json": json.dumps(payload, indent=2, ensure_ascii=False),
        "iss": payload.get("iss") or "",
    }


# --- validazione form ------------------------------------------------------------

def _valid_url(value: str, allow_http: bool = False) -> bool:
    if len(value) > MAX_URL_LEN or any(c.isspace() or c in _URL_FORBIDDEN for c in value):
        return False
    try:
        parts = urlsplit(value)
        parts.port  # noqa: B018 - solleva ValueError su porta non valida
    except ValueError:
        return False
    schemes = ("https", "http") if allow_http else ("https",)
    return parts.scheme in schemes and bool(parts.hostname) and not parts.username and not parts.password


def _valid_email(value: str) -> bool:
    if len(value) > 256 or any(c.isspace() or c in _URL_FORBIDDEN for c in value):
        return False
    local, sep, domain = value.partition("@")
    return bool(sep and local and "." in domain and "@" not in domain)


def _parse_trust_anchor_jwks(raw: str) -> dict | None:
    """None se vuoto, {"keys": [...]} se valido; ValueError col motivo altrimenti."""
    raw = raw.strip()
    if not raw:
        return None
    if len(raw) > MAX_JWKS_LEN:
        raise ValueError("JWKS del trust anchor troppo lungo")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("JWKS del trust anchor non è JSON valido") from e
    keys = value.get("keys") if isinstance(value, dict) else value
    if not isinstance(keys, list) or not keys:
        raise ValueError('JWKS del trust anchor: serve una lista di chiavi o {"keys": [...]}')
    for key in keys:
        if not isinstance(key, dict) or not isinstance(key.get("kty"), str):
            raise ValueError("JWKS del trust anchor: ogni chiave deve essere un oggetto con \"kty\"")
        if any(m in key for m in PRIVATE_JWK_MEMBERS):
            raise ValueError("JWKS del trust anchor: contiene parti private, servono solo chiavi pubbliche")
    return {"keys": keys}


# --- pagina ---------------------------------------------------------------------

@router.get("/itwallet", response_class=HTMLResponse)
async def itwallet_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    flash = {k.removeprefix("itwallet_"): request.session.pop(k, None) for k in _FLASH_KEYS}
    cfg = await _get_config(db)
    settings = await _get_settings(db)
    keys = await _load_keys(db, cfg)
    hostname = _hostname(settings)
    ready, reason = itw.itwallet_ready(cfg, {r: k.private_jwk for r, k in keys.items()})

    s = settings
    defaults = {
        "organization_name": (cfg.organization_name if cfg else None) or (s.org_name if s else ""),
        "client_name": (cfg.client_name if cfg else None) or (s and (s.org_display_name or s.org_name)) or "",
        "homepage_uri": (cfg.homepage_uri if cfg else None) or (s.org_url if s else ""),
        "policy_uri": (cfg.policy_uri if cfg else None) or (s.privacy_url if s else ""),
        "tos_uri": (cfg.tos_uri if cfg else None) or (s.legal_notes_url if s else ""),
        "logo_uri": (cfg.logo_uri if cfg else None) or _absolute_url(s.logo_url if s else "", hostname),
        "contact_email": (cfg.contact_email if cfg else None) or (s.contact_email if s else ""),
    }
    csr_missing = [label for attr, label in (("org_name", "nome ente"), ("ipa_code", "codice IPA"),
                                              ("org_city", "città"))
                   if not (s and getattr(s, attr, ""))]

    return templates.TemplateResponse(request, "itwallet/config.html.j2", {
        "config": cfg,
        "flash": flash,
        "ready": ready,
        "ready_reason": reason,
        "hostname": hostname,
        "entity_id": itw.entity_id(hostname) if hostname else "",
        "client_id": itw.federation_client_id(hostname) if hostname else "",
        "ec_url": itw.entity_configuration_url(hostname) if hostname else "",
        "keys": keys,
        "key_roles": list(KEY_FK),
        "federation_jwks_json": json.dumps(_public_federation_jwks(keys), indent=2),
        "trust_anchor_jwks_json": json.dumps(cfg.trust_anchor_jwks, indent=2) if cfg and cfg.trust_anchor_jwks else "",
        "defaults": defaults,
        "environments": ENVIRONMENT_LABELS,
        "trust_mark": _trust_mark_view(cfg.trust_mark if cfg else None),
        "production_without_trust_mark": bool(cfg and cfg.environment == "produzione" and not cfg.trust_mark),
        "ec_preview": await _entity_configuration_preview(cfg),
        "csr_missing": csr_missing,
        "archived_key_sets": await _archived_key_sets(db, cfg),
    })


# --- impostazioni ---------------------------------------------------------------

@router.post("/itwallet/settings")
async def itwallet_settings(
    request: Request,
    environment: str = Form(default=""),
    trust_anchor_url: str = Form(default=""),
    authority_hint_url: str = Form(default=""),
    trust_anchor_jwks: str = Form(default=""),
    organization_name: str = Form(default=""),
    client_name: str = Form(default=""),
    homepage_uri: str = Form(default=""),
    policy_uri: str = Form(default=""),
    tos_uri: str = Form(default=""),
    logo_uri: str = Form(default=""),
    contact_email: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    tab = "configurazione"
    environment = environment.strip()
    if environment and environment not in itw.ENVIRONMENTS:
        return _flash(request, "err", "Ambiente non valido.", tab)
    allow_http = environment == "personalizzato"

    values = {
        "trust_anchor_url": trust_anchor_url.strip(),
        "authority_hint_url": authority_hint_url.strip(),
        "homepage_uri": homepage_uri.strip(),
        "policy_uri": policy_uri.strip(),
        "tos_uri": tos_uri.strip(),
        "logo_uri": logo_uri.strip(),
    }
    labels = {
        "trust_anchor_url": "URL trust anchor", "authority_hint_url": "URL authority hint",
        "homepage_uri": "Homepage", "policy_uri": "Informativa privacy",
        "tos_uri": "Termini di servizio", "logo_uri": "Logo",
    }
    for field, value in values.items():
        federation_url = field in ("trust_anchor_url", "authority_hint_url")
        if value and not _valid_url(value, allow_http=allow_http and federation_url):
            hint = " (https; http solo in ambiente personalizzato)" if federation_url else " (https)"
            return _flash(request, "err", f"{labels[field]}: URL non valido{hint}.", tab)

    contact_email = contact_email.strip()
    if contact_email and not _valid_email(contact_email):
        return _flash(request, "err", "Contatto (PEC): indirizzo email non valido.", tab)
    organization_name = organization_name.strip()[:256]
    client_name = client_name.strip()[:256]

    try:
        ta_jwks = _parse_trust_anchor_jwks(trust_anchor_jwks)
    except ValueError as e:
        return _flash(request, "err", str(e), tab)

    cfg = await _get_or_create_config(db)
    previous_env = cfg.environment
    cfg.environment = environment or None
    for field, value in values.items():
        setattr(cfg, field, value or None)
    cfg.trust_anchor_jwks = ta_jwks
    cfg.organization_name = organization_name or None
    cfg.client_name = client_name or None
    cfg.contact_email = contact_email or None
    await db.commit()
    await _regenerate(db)

    request.session["itwallet_ok"] = "Configurazione IT-Wallet salvata."
    if previous_env and previous_env != cfg.environment:
        request.session["itwallet_warn"] = (
            f"Ambiente cambiato da «{ENVIRONMENT_LABELS.get(previous_env, previous_env)}» a "
            f"«{ENVIRONMENT_LABELS.get(cfg.environment, cfg.environment or 'nessuno')}»: "
            "onboarding da rifare per il nuovo ambiente (stesse chiavi, nuova registrazione e nuovo trust mark)."
        )
    return _redirect(tab)


# --- chiavi -----------------------------------------------------------------------

@router.post("/itwallet/keys/generate")
async def itwallet_keys_generate(
    request: Request,
    confirm_regenerate: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    tab = "chiavi"
    cfg = await _get_config(db)
    old_ids = [getattr(cfg, attr) for attr in KEY_FK.values() if getattr(cfg, attr)] if cfg else []
    if old_ids and confirm_regenerate != "yes":
        return _flash(request, "err",
                      "Rigenerazione non confermata: spunta la conferma (le chiavi nuove invalidano l'onboarding).",
                      tab)
    cfg = await _get_or_create_config(db)
    suffix = uuid4().hex[:8]
    new_keys = {role: generate_ec_jwk(f"itwallet-{role}-{suffix}", role) for role in KEY_FK}
    db.add_all(new_keys.values())
    await db.flush()
    for role, attr in KEY_FK.items():
        setattr(cfg, attr, new_keys[role].id)
    # Le chiavi precedenti NON si cancellano: restano nello storico e si riattivano.
    await db.commit()
    await _regenerate(db)

    if old_ids:
        request.session["itwallet_warn"] = (
            "Chiavi rigenerate: l'onboarding va rifatto (nuovo JWKS e nuova CSR). "
            "Le chiavi precedenti sono nello storico e si possono riattivare."
        )
    request.session["itwallet_ok"] = "Chiavi IT-Wallet generate."
    return _redirect(tab)


@router.post("/itwallet/keys/restore")
async def itwallet_keys_restore(
    request: Request,
    suffix: str = Form(default=""),
    confirmed: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    tab = "chiavi"
    if confirmed != "yes":
        return _flash(request, "err", "Riattivazione non confermata.", tab)
    cfg = await _get_config(db)
    target = next((s for s in await _archived_key_sets(db, cfg) if s["suffix"] == suffix), None)
    if target is None:
        return _flash(request, "err", "Set di chiavi non trovato nello storico.", tab)

    cfg = await _get_or_create_config(db)
    for role, attr in KEY_FK.items():
        setattr(cfg, attr, target["keys"][role].id)
    await db.commit()
    await _regenerate(db)

    request.session["itwallet_ok"] = f"Chiavi riattivate (federation kid {target['kid']})."
    request.session["itwallet_warn"] = (
        "Le chiavi in uso prima sono nello storico. JWKS e CSR sono di nuovo quelli di questo set: "
        "vale la registrazione (e il trust mark) ottenuta con queste chiavi."
    )
    return _redirect(tab)


# --- attivazione ------------------------------------------------------------------

@router.post("/itwallet/toggle")
async def itwallet_toggle(
    request: Request,
    enabled: str = Form(default=""),
    confirmed: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    tab = "stato"
    enable = enabled == "yes"
    cfg = await _get_config(db)
    if enable:
        if confirmed != "yes":
            return _flash(request, "err", "Attivazione non confermata.", tab)
        keys = await _load_keys(db, cfg)
        ready, reason = itw.itwallet_ready(cfg, {r: k.private_jwk for r, k in keys.items()})
        if not ready:
            return _flash(request, "err", f"Impossibile attivare IT-Wallet: {reason}.", tab)
    elif cfg is None or not cfg.enabled:
        return _redirect(tab)

    cfg.enabled = enable
    await db.commit()
    await _regenerate(db)

    if enable:
        request.session["itwallet_ok"] = "IT-Wallet attivato."
        if cfg.environment == "produzione" and not cfg.trust_mark:
            request.session["itwallet_warn"] = (
                "IT-Wallet attivo in produzione senza trust mark: i wallet possono rifiutare il verifier."
            )
    else:
        request.session["itwallet_ok"] = "IT-Wallet disattivato."
    return _redirect(tab)


# --- trust mark -------------------------------------------------------------------

@router.post("/itwallet/trust-mark")
async def itwallet_trust_mark(
    request: Request,
    trust_mark: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    tab = "trust-mark"
    token = "".join(trust_mark.split())
    if len(token) > MAX_TRUST_MARK_LEN:
        return _flash(request, "err", "Trust mark troppo lungo.", tab)
    trust_mark_id = None
    if token:
        try:
            _, payload = _decode_jws(token)
        except ValueError as e:
            return _flash(request, "err", f"Trust mark non valido: {e}.", tab)
        trust_mark_id = payload.get("id") or payload.get("trust_mark_id")
        if trust_mark_id is not None and not isinstance(trust_mark_id, str):
            return _flash(request, "err", "Trust mark non valido: il claim id non è una stringa.", tab)

    cfg = await _get_or_create_config(db)
    cfg.trust_mark = token or None
    cfg.trust_mark_id = trust_mark_id or None
    await db.commit()
    await _regenerate(db)
    request.session["itwallet_ok"] = "Trust mark salvato." if token else "Trust mark rimosso."
    return _redirect(tab)


# --- onboarding: JWKS e CSR ------------------------------------------------------

@router.get("/itwallet/jwks.json")
async def itwallet_jwks(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    keys = await _load_keys(db, await _get_config(db))
    return JSONResponse(_public_federation_jwks(keys), headers={"Cache-Control": "no-store"})


@router.get("/itwallet/csr")
async def itwallet_csr(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    tab = "onboarding"
    keys = await _load_keys(db, await _get_config(db))
    fed = keys.get("federation")
    if fed is None:
        return _flash(request, "err", "CSR non disponibile: genera prima le chiavi.", tab)
    settings = await _get_settings(db)
    if settings is None:
        return _flash(request, "err", "CSR non disponibile: impostazioni ente assenti.", tab)
    try:
        pem = await asyncio.to_thread(build_csr, fed.private_jwk, _hostname(settings), settings)
    except CsrError as e:
        return _flash(request, "err", f"{e} (vedi Impostazioni).", tab)
    return Response(
        content=pem,
        media_type="application/pkcs10",
        headers={
            "Content-Disposition": 'attachment; filename="itwallet-federation.csr"',
            "Cache-Control": "no-store",
        },
    )
