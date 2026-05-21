import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, OIDCClient, SpidCert, SpidIdP

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

SATOSA_INTERNAL_URL = os.environ.get("SATOSA_INTERNAL_URL", "http://satosa:8080")


async def _satosa_status() -> str:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.get(SATOSA_INTERNAL_URL)
        return "running"
    except Exception:
        return "unreachable"


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/admin/login", status_code=302)

    clients_total = (await db.execute(select(func.count()).select_from(OIDCClient))).scalar()
    clients_enabled = (await db.execute(select(func.count()).select_from(OIDCClient).where(OIDCClient.enabled == True))).scalar()

    idps_total = (await db.execute(select(func.count()).select_from(SpidIdP))).scalar()
    idps_enabled = (await db.execute(select(func.count()).select_from(SpidIdP).where(SpidIdP.enabled == True))).scalar()

    cert_row = (await db.execute(select(SpidCert).order_by(SpidCert.created_at.desc()).limit(1))).scalar_one_or_none()
    cert_days = None
    if cert_row:
        cert_days = (cert_row.not_valid_after - datetime.now(timezone.utc)).days

    settings = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()

    return templates.TemplateResponse(request, "dashboard.html.j2", {
        "user": user,
        "clients_total": clients_total,
        "clients_enabled": clients_enabled,
        "idps_total": idps_total,
        "idps_enabled": idps_enabled,
        "cert": cert_row,
        "cert_days": cert_days,
        "settings": settings,
        "satosa_status": await _satosa_status(),
    })
