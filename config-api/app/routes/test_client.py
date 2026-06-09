import asyncio
import base64
import hashlib
import json
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, OIDCClient
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()


TEST_CLIENT_ID = "__admin_test__"
SATOSA_INTERNAL_URL = os.environ.get("SATOSA_INTERNAL_URL", "http://satosa:8080")


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


def _public_base(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    proto = request.headers.get("x-forwarded-proto", "http")
    return f"{proto}://{host}"


def _callback_uri(request: Request) -> str:
    return f"{_public_base(request)}/admin/test-client/callback"


async def _get_test_client(db: AsyncSession) -> OIDCClient | None:
    result = await db.execute(select(OIDCClient).where(OIDCClient.client_id == TEST_CLIENT_ID))
    return result.scalar_one_or_none()


async def _satosa_base(db: AsyncSession) -> str:
    override = os.environ.get("PROXY_BASE_URL", "").rstrip("/")
    if override:
        return override
    settings = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()
    hostname = settings.proxy_hostname if settings else "localhost"
    return f"https://{hostname}"


@router.get("/test-client", response_class=HTMLResponse)
async def test_client_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    client = await _get_test_client(db)
    return templates.TemplateResponse(request, "test_client/index.html.j2", {
        "client": client,
        "callback_uri": _callback_uri(request),
        "test_client_id": TEST_CLIENT_ID,
        "has_secret": bool(request.session.get("test_client_secret")),
    })


@router.post("/test-client/setup")
async def test_client_setup(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    callback_uri = _callback_uri(request)
    plaintext_secret = secrets.token_urlsafe(32)

    client = await _get_test_client(db)
    if client is None:
        client = OIDCClient(
            client_id=TEST_CLIENT_ID,
            client_secret_hash=plaintext_secret,
            client_secret_plain=plaintext_secret,
            name="Admin Test Client (interno)",
            redirect_uris=[callback_uri],
            allowed_scopes=["openid", "profile", "email"],
            enabled=True,
        )
        db.add(client)
    else:
        client.client_secret_hash = plaintext_secret
        client.client_secret_plain = plaintext_secret
        client.redirect_uris = [callback_uri]
        client.enabled = True

    await db.commit()
    await generate_and_write(db)
    await asyncio.to_thread(reload_satosa)

    request.session["test_client_secret"] = plaintext_secret
    return RedirectResponse("/admin/test-client", status_code=302)


_SPID_ACR = {
    "1": "https://www.spid.gov.it/SpidL1",
    "2": "https://www.spid.gov.it/SpidL2",
    "3": "https://www.spid.gov.it/SpidL3",
}


@router.get("/test-client/start")
async def test_client_start(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    client = await _get_test_client(db)
    if not client or not request.session.get("test_client_secret"):
        return RedirectResponse("/admin/test-client", status_code=302)

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(16)

    request.session["test_pkce_verifier"] = code_verifier
    request.session["test_pkce_state"] = state

    satosa_base = await _satosa_base(db)
    callback_uri = _callback_uri(request)

    level = request.query_params.get("level", "2")
    acr = _SPID_ACR.get(level, _SPID_ACR["2"])

    auth_url = f"{satosa_base}/OIDC/authorization?" + urlencode({
        "client_id": TEST_CLIENT_ID,
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


@router.get("/test-client/callback")
async def test_client_callback(request: Request):
    """Handles SATOSA redirect. Exchanges code and stores result in session, then redirects to /result."""
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    error = request.query_params.get("error")
    if error:
        request.session["test_result"] = {
            "success": False,
            "error": error,
            "error_description": request.query_params.get("error_description", ""),
        }
        return RedirectResponse("/admin/test-client/result", status_code=302)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    saved_state = request.session.pop("test_pkce_state", None)
    code_verifier = request.session.pop("test_pkce_verifier", None)
    client_secret = request.session.get("test_client_secret")

    if state != saved_state:
        request.session["test_result"] = {
            "success": False,
            "error": "state_mismatch",
            "error_description": f"State atteso: {saved_state!r}, ricevuto: {state!r}",
        }
        return RedirectResponse("/admin/test-client/result", status_code=302)

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                f"{SATOSA_INTERNAL_URL}/OIDC/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _callback_uri(request),
                    "code_verifier": code_verifier or "",
                },
                auth=(TEST_CLIENT_ID, client_secret or ""),
            )
        token_data = resp.json()
    except Exception as exc:
        request.session["test_result"] = {
            "success": False,
            "error": "token_exchange_failed",
            "error_description": str(exc),
        }
        return RedirectResponse("/admin/test-client/result", status_code=302)

    if "error" in token_data:
        request.session["test_result"] = {
            "success": False,
            "error": token_data["error"],
            "error_description": token_data.get("error_description", ""),
            "raw": json.dumps(token_data, indent=2),
        }
        return RedirectResponse("/admin/test-client/result", status_code=302)

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

    request.session["test_id_token"] = id_token
    request.session["test_result"] = {
        "success": True,
        "claims": json.dumps(claims, indent=2, ensure_ascii=False),
        "userinfo": json.dumps(userinfo, indent=2, ensure_ascii=False),
        "token_response": json.dumps(
            {k: v for k, v in token_data.items() if k != "id_token"}, indent=2, ensure_ascii=False
        ),
        "id_token": id_token,
    }
    return RedirectResponse("/admin/test-client/result", status_code=302)


@router.get("/test-client/result", response_class=HTMLResponse)
async def test_client_result(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    result = request.session.pop("test_result", None)
    if result is None:
        return RedirectResponse("/admin/test-client", status_code=302)

    satosa_base = await _satosa_base(db)
    id_token = request.session.get("test_id_token", "")
    callback_base = _public_base(request)
    logout_url = (
        f"{satosa_base}/OIDC/end_session?"
        + urlencode({
            "id_token_hint": id_token,
            "post_logout_redirect_uri": f"{callback_base}/admin/test-client/logout-done",
        })
        if id_token else ""
    )
    result["logout_url"] = logout_url
    return templates.TemplateResponse(request, "test_client/result.html.j2", result)


@router.get("/test-client/logout-done", response_class=HTMLResponse)
async def test_client_logout_done(request: Request):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    request.session.pop("test_id_token", None)
    return RedirectResponse("/admin/test-client", status_code=302)
