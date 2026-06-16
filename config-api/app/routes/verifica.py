import base64
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jinja_templates import templates
from app.models import EnteSettings, SpidIdP

router = APIRouter()

VERIFICA_CLIENT_ID = "__spid_verifica__"
SATOSA_INTERNAL_URL = os.environ.get("SATOSA_INTERNAL_URL", "http://satosa:8080")
_TEST_ALIASES = {"spid-demo", "spid-validator"}

_SPID_ACR = {
    "1": "https://www.spid.gov.it/SpidL1",
    "2": "https://www.spid.gov.it/SpidL2",
    "3": "https://www.spid.gov.it/SpidL3",
}


def _verifica_secret() -> str:
    salt = os.environ.get("SATOSA_HASH_SALT", "changeme").encode()
    return hmac.new(salt, b"__spid_verifica__", hashlib.sha256).hexdigest()


def _public_base(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    proto = request.headers.get("x-forwarded-proto", "http")
    return f"{proto}://{host}"


async def _satosa_base(db: AsyncSession) -> str:
    override = os.environ.get("PROXY_BASE_URL", "").rstrip("/")
    if override:
        return override
    settings = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()
    hostname = settings.proxy_hostname if settings else "localhost"
    return f"https://{hostname}"


async def _get_test_idp(db: AsyncSession):
    result = await db.execute(
        select(SpidIdP).where(SpidIdP.alias.in_(_TEST_ALIASES), SpidIdP.enabled == True)
    )
    return result.scalar_one_or_none()


async def _get_settings(db: AsyncSession):
    return (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()


@router.get("/verifica", response_class=HTMLResponse)
async def verifica_page(request: Request, db: AsyncSession = Depends(get_db)):
    test_idp = await _get_test_idp(db)
    if not test_idp:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse(request, "verifica/index.html.j2", {
        "settings": await _get_settings(db),
        "test_idp_name": test_idp.display_name,
    })


@router.get("/verifica/start")
async def verifica_start(request: Request, db: AsyncSession = Depends(get_db)):
    test_idp = await _get_test_idp(db)
    if not test_idp:
        raise HTTPException(status_code=404)

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(16)
    request.session["verifica_pkce_verifier"] = code_verifier
    request.session["verifica_pkce_state"] = state

    satosa_base = await _satosa_base(db)
    callback_uri = f"{satosa_base}/verifica/callback"

    level = request.query_params.get("level", "2")
    acr = _SPID_ACR.get(level, _SPID_ACR["2"])

    auth_url = f"{satosa_base}/OIDC/authorization?" + urlencode({
        "client_id": VERIFICA_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": callback_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "acr_values": acr,
        "claims": json.dumps({
            "userinfo": {
                "fiscal_number": {"essential": True},
                "given_name": None,
                "family_name": None,
                "email": None,
                "https://attributes.eid.gov.it/fiscal_number": {"essential": True},
            }
        }),
    })
    return RedirectResponse(auth_url, status_code=302)


@router.get("/verifica/callback", response_class=HTMLResponse)
async def verifica_callback(request: Request, db: AsyncSession = Depends(get_db)):
    settings = await _get_settings(db)

    error = request.query_params.get("error")
    if error:
        return templates.TemplateResponse(request, "verifica/result.html.j2", {
            "success": False,
            "error": error,
            "error_description": request.query_params.get("error_description", ""),
            "settings": settings,
        })

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    saved_state = request.session.pop("verifica_pkce_state", None)
    code_verifier = request.session.pop("verifica_pkce_verifier", None)

    if state != saved_state:
        return templates.TemplateResponse(request, "verifica/result.html.j2", {
            "success": False,
            "error": "state_mismatch",
            "error_description": f"State atteso: {saved_state!r}, ricevuto: {state!r}",
            "settings": settings,
        })

    satosa_base = await _satosa_base(db)
    callback_uri = f"{satosa_base}/verifica/callback"

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                f"{SATOSA_INTERNAL_URL}/OIDC/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": callback_uri,
                    "code_verifier": code_verifier or "",
                },
                auth=(VERIFICA_CLIENT_ID, _verifica_secret()),
            )
        token_data = resp.json()
    except Exception as exc:
        return templates.TemplateResponse(request, "verifica/result.html.j2", {
            "success": False,
            "error": "token_exchange_failed",
            "error_description": str(exc),
            "settings": settings,
        })

    if "error" in token_data:
        return templates.TemplateResponse(request, "verifica/result.html.j2", {
            "success": False,
            "error": token_data["error"],
            "error_description": token_data.get("error_description", ""),
            "settings": settings,
        })

    id_token = token_data.get("id_token", "")
    access_token = token_data.get("access_token", "")

    claims = {}
    if id_token:
        try:
            payload = id_token.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
        except Exception:
            pass

    userinfo = {}
    if access_token:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                ui_resp = await http.get(
                    f"{SATOSA_INTERNAL_URL}/OIDC/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            userinfo = ui_resp.json()
        except Exception:
            pass

    return templates.TemplateResponse(request, "verifica/result.html.j2", {
        "success": True,
        "claims": claims,
        "userinfo": userinfo,
        "settings": settings,
    })
