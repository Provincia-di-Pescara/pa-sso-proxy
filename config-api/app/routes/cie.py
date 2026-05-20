import asyncio
import logging
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

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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

    return templates.TemplateResponse(
        request,
        "cie/config.html.j2",
        {"config": config, "jwk_keys": jwk_keys},
    )


@router.post("/cie")
async def cie_config_post(
    request: Request,
    saml_metadata_url: str = Form(...),
    entity_id: str = Form(default=""),
    client_id: str = Form(default=""),
    jwk_federation_id: str = Form(default=""),
    jwk_core_sig_id: str = Form(default=""),
    jwk_core_enc_id: str = Form(default=""),
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
    config.entity_id = entity_id or None
    config.client_id = client_id or None
    config.jwk_federation_id = _parse_int(jwk_federation_id)
    config.jwk_core_sig_id = _parse_int(jwk_core_sig_id)
    config.jwk_core_enc_id = _parse_int(jwk_core_enc_id)

    await db.commit()

    keys = await _get_all_keys(db)
    await _write_jwks_safe(keys)

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

    return RedirectResponse("/admin/cie", status_code=302)
