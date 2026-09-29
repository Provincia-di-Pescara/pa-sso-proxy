"""Internazionalizzazione delle pagine utente del proxy.

Fonte unica delle traduzioni: /satosa_proxy/static/i18n/<lang>.json (stessi file
serviti alla discovery page). Modulo senza dipendenze SATOSA: testabile fuori
dal container.

Precedenza lingua (identica in disco.html): cookie sso_lang → ui_locales della
richiesta OIDC → Accept-Language → it.
"""
import json
import logging
import os
import urllib.parse
from functools import lru_cache
from http.cookies import CookieError, SimpleCookie

logger = logging.getLogger(__name__)

SUPPORTED = ("it", "en", "fr", "de", "es")
DEFAULT = "it"
COOKIE_NAME = "sso_lang"
# Lingua salvata nello stato SATOSA a inizio login (GET, cookie presente): sull'ACS
# SPID (POST cross-site dall'IdP) il cookie SameSite=Lax sso_lang non arriva.
STATE_KEY = "sso_i18n_lang"
I18N_DIR = os.environ.get("SSO_I18N_DIR", "/satosa_proxy/static/i18n")


def normalize(tag):
    """Lingua primaria supportata ('fr-CA' → 'fr'), altrimenti None."""
    if not tag:
        return None
    primary = tag.strip().replace("_", "-").split("-", 1)[0].lower()
    return primary if primary in SUPPORTED else None


def parse_accept_language(header):
    """Lingue supportate da Accept-Language, per peso q decrescente, senza duplicati."""
    if not header:
        return []
    weighted = []
    for pos, part in enumerate(header.split(",")):
        tag, _, params = part.strip().partition(";")
        q = 1.0
        params = params.strip()
        if params.startswith("q="):
            try:
                q = float(params[2:])
            except ValueError:
                q = 0.0
        lang = normalize(tag)
        if lang and q > 0:
            weighted.append((-q, pos, lang))
    result = []
    for _q, _pos, lang in sorted(weighted):
        if lang not in result:
            result.append(lang)
    return result


def lang_from_cookie(cookie_header):
    if not cookie_header:
        return None
    try:
        jar = SimpleCookie()
        jar.load(cookie_header)
    except CookieError:
        return None
    morsel = jar.get(COOKIE_NAME)
    return normalize(morsel.value) if morsel else None


def ui_locales_lang(context):
    """Prima lingua supportata in ui_locales della richiesta OIDC nello stato SATOSA."""
    for v in (getattr(context, "state", None) or {}).values():
        if isinstance(v, dict) and "oidc_request" in v:
            try:
                params = urllib.parse.parse_qs(v.get("oidc_request") or "")
            except Exception:
                return None
            for tag in params.get("ui_locales", [""])[0].split():
                lang = normalize(tag)
                if lang:
                    return lang
            return None
    return None


def resolve_lang(context):
    if context is None:
        return DEFAULT
    headers = getattr(context, "http_headers", None) or {}
    cookie = getattr(context, "cookie", None) or headers.get("HTTP_COOKIE")
    state = getattr(context, "state", None) or {}
    lang = lang_from_cookie(cookie) or normalize(state.get(STATE_KEY)) or ui_locales_lang(context)
    if lang:
        return lang
    browser = parse_accept_language(headers.get("HTTP_ACCEPT_LANGUAGE"))
    return browser[0] if browser else DEFAULT


@lru_cache(maxsize=None)
def _load(lang):
    if lang not in SUPPORTED:
        return {}
    try:
        with open(os.path.join(I18N_DIR, f"{lang}.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        logger.error(f"i18n: impossibile caricare {lang}.json: {exc}")
        return {}


def t(lang, key, **params):
    for candidate in (lang, "en", DEFAULT):
        value = _load(candidate).get(key)
        if value:
            return value.format(**params) if params else value
    return key


def template_vars(lang):
    return {"lang": lang, "t": lambda key, **params: t(lang, key, **params)}
