import asyncio
import json
import logging
import os
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cie_jwks_writer import write_jwks_files
from app.database import get_db
from app.jwk_generator import generate_jwk
from app.models import CieConfig, JwkKey
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# URL fissi CIE OIDC per ambiente. Provider URL (lista providers SATOSA) = URL OP,
# assunto uguale all'Authority Hint. Da confermare in fase di test col portale.
CIE_OIDC_ENVIRONMENTS = {
    "collaudo": {
        "provider_url": "https://preproduzione.cie.interno.gov.it/idp/oidc/op",
        "trust_anchor_url": "https://preproduzione.cie.interno.gov.it",
        "authority_hint_url": "https://preproduzione.cie.interno.gov.it/idp/oidc/op",
    },
    "produzione": {
        "provider_url": "https://oidc.idserver.servizicie.interno.gov.it",
        "trust_anchor_url": "https://registry.servizicie.interno.gov.it",
        "authority_hint_url": "https://oidc.idserver.servizicie.interno.gov.it",
    },
}


def _parse_int(val: str) -> Optional[int]:
    return int(val) if val.strip() else None


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


async def _get_all_keys(db: AsyncSession) -> list[JwkKey]:
    result = await db.execute(select(JwkKey).order_by(JwkKey.created_at))
    return list(result.scalars().all())


async def _write_jwks_safe(keys: list[JwkKey]) -> None:
    try:
        await asyncio.to_thread(write_jwks_files, keys)
    except Exception:
        logger.warning("JWKS file write failed", exc_info=True)


@router.get("/cie", response_class=HTMLResponse)
async def cie_config_get(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    config = result.scalar_one_or_none()
    jwk_keys = await _get_all_keys(db)

    public_jwks = {"keys": [k.public_jwk for k in jwk_keys if k.public_jwk]}
    public_jwks_json = json.dumps(public_jwks, indent=4)

    proxy_hostname = os.environ.get("PROXY_HOSTNAME", "")
    derived_client_id = f"https://{proxy_hostname}/CieOidcRp" if proxy_hostname else ""

    return templates.TemplateResponse(
        request,
        "cie/config.html.j2",
        {
            "config": config,
            "jwk_keys": jwk_keys,
            "public_jwks_json": public_jwks_json,
            "environments": CIE_OIDC_ENVIRONMENTS,
            "derived_client_id": derived_client_id,
        },
    )


@router.post("/cie")
async def cie_config_post(
    request: Request,
    saml_metadata_url: str = Form(...),
    jwk_federation_id: str = Form(default=""),
    jwk_core_sig_id: str = Form(default=""),
    jwk_core_enc_id: str = Form(default=""),
    oidc_federation_enabled: str = Form(default=""),
    oidc_environment: str = Form(default=""),
    oidc_provider_url: str = Form(default=""),
    trust_anchor_url: str = Form(default=""),
    authority_hint_url: str = Form(default=""),
    homepage_uri: str = Form(default=""),
    policy_uri: str = Form(default=""),
    logo_uri: str = Form(default=""),
    trust_mark: str = Form(default=""),
    oidc_contact_email: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    config = result.scalar_one_or_none()

    if config is None:
        config = CieConfig(id=1)
        db.add(config)

    config.saml_metadata_url = saml_metadata_url
    config.jwk_federation_id = int(jwk_federation_id) if jwk_federation_id else None
    config.jwk_core_sig_id = int(jwk_core_sig_id) if jwk_core_sig_id else None
    config.jwk_core_enc_id = int(jwk_core_enc_id) if jwk_core_enc_id else None
    config.oidc_federation_enabled = oidc_federation_enabled == "on"
    # Se ambiente selezionato e valido, i tre URL derivano dalla mappa fissa.
    # Altrimenti si usano i valori postati (retrocompat / override manuale).
    env = CIE_OIDC_ENVIRONMENTS.get(oidc_environment)
    if env is not None:
        config.oidc_environment = oidc_environment
        config.oidc_provider_url = env["provider_url"]
        config.trust_anchor_url = env["trust_anchor_url"]
        config.authority_hint_url = env["authority_hint_url"]
    else:
        config.oidc_environment = oidc_environment or None
        config.oidc_provider_url = oidc_provider_url or None
        config.trust_anchor_url = trust_anchor_url or None
        config.authority_hint_url = authority_hint_url or None
    config.homepage_uri = homepage_uri or None
    config.policy_uri = policy_uri or None
    config.logo_uri = logo_uri or None
    config.trust_mark = trust_mark or None
    config.oidc_contact_email = oidc_contact_email or None

    await db.commit()

    try:
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    except Exception:
        logger.warning("generate_and_write failed after CIE config save", exc_info=True)

    return RedirectResponse("/admin/cie", status_code=302)


@router.post("/cie/generate-jwk/{use}")
async def cie_generate_jwk(
    request: Request,
    use: str,
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    if use not in {"federation", "sig", "enc"}:
        return RedirectResponse("/admin/cie", status_code=302)

    name = f"cie-{use}-{uuid4().hex[:8]}"
    key = generate_jwk(name, use)
    db.add(key)
    await db.commit()

    keys = await _get_all_keys(db)
    await _write_jwks_safe(keys)
    await asyncio.to_thread(reload_satosa)

    return RedirectResponse("/admin/cie", status_code=302)


@router.post("/cie/delete-jwk/{jwk_id}")
async def cie_delete_jwk(
    request: Request,
    jwk_id: int,
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    # Clear FK references in CieConfig if they point to this key
    result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    config = result.scalar_one_or_none()
    if config is not None:
        if config.jwk_federation_id == jwk_id:
            config.jwk_federation_id = None
        if config.jwk_core_sig_id == jwk_id:
            config.jwk_core_sig_id = None
        if config.jwk_core_enc_id == jwk_id:
            config.jwk_core_enc_id = None
        await db.commit()

    result = await db.execute(select(JwkKey).where(JwkKey.id == jwk_id))
    key = result.scalar_one_or_none()
    if key is not None:
        await db.delete(key)
        await db.commit()

    keys = await _get_all_keys(db)
    await _write_jwks_safe(keys)
    await asyncio.to_thread(reload_satosa)

    return RedirectResponse("/admin/cie", status_code=302)
