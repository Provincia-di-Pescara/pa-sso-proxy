import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import AccessLog, CieConfig, EnteSettings, OIDCClient, SpidCert, SpidIdP
from app.satosa_config_generator import _cie_oidc_client_id

router = APIRouter()

SATOSA_INTERNAL_URL = os.environ.get("SATOSA_INTERNAL_URL", "http://satosa:8080")


async def _satosa_status() -> str:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.get(SATOSA_INTERNAL_URL)
        return "running"
    except Exception:
        return "unreachable"


async def _access_stats(db: AsyncSession) -> dict:
    try:
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=6)
        month_start = today_start - timedelta(days=29)

        async def _counts(since):
            total = (await db.execute(
                select(func.count()).select_from(AccessLog).where(AccessLog.timestamp >= since)
            )).scalar() or 0
            success = (await db.execute(
                select(func.count()).select_from(AccessLog)
                .where(AccessLog.timestamp >= since, AccessLog.result == "success")
            )).scalar() or 0
            return total, success

        today_total, today_ok = await _counts(today_start)
        week_total, week_ok = await _counts(week_start)
        month_total, month_ok = await _counts(month_start)

        # Per-provider breakdown (last 30 days)
        prov_rows = (await db.execute(
            select(AccessLog.provider_type, AccessLog.result, func.count().label("cnt"))
            .where(AccessLog.timestamp >= month_start)
            .group_by(AccessLog.provider_type, AccessLog.result)
        )).all()
        by_provider = {}
        for row in prov_rows:
            pt = row.provider_type
            if pt not in by_provider:
                by_provider[pt] = {"success": 0, "failure": 0}
            if row.result == "success":
                by_provider[pt]["success"] += row.cnt
            else:
                by_provider[pt]["failure"] += row.cnt

        # Per-client breakdown (last 30 days)
        cli_rows = (await db.execute(
            select(AccessLog.client_id, AccessLog.result, func.count().label("cnt"))
            .where(AccessLog.timestamp >= month_start)
            .group_by(AccessLog.client_id, AccessLog.result)
        )).all()
        by_client = {}
        for row in cli_rows:
            cid = row.client_id or "(nessuno)"
            if cid not in by_client:
                by_client[cid] = {"total": 0, "success": 0}
            by_client[cid]["total"] += row.cnt
            if row.result == "success":
                by_client[cid]["success"] += row.cnt

        # Recent activity (last 20)
        recent = list((await db.execute(
            select(AccessLog).order_by(AccessLog.timestamp.desc()).limit(20)
        )).scalars().all())

        return {
            "today": {"total": today_total, "success": today_ok, "failure": today_total - today_ok},
            "week": {"total": week_total, "success": week_ok, "failure": week_total - week_ok},
            "month": {"total": month_total, "success": month_ok, "failure": month_total - month_ok},
            "by_provider": by_provider,
            "by_client": by_client,
            "recent": recent,
            "has_data": month_total > 0,
        }
    except Exception:
        return {"has_data": False, "recent": []}


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

    cie_config = (await db.execute(select(CieConfig).where(CieConfig.id == 1))).scalar_one_or_none()
    cie_oidc_client_id = None
    if cie_config and cie_config.oidc_federation_enabled and settings:
        cie_oidc_client_id = _cie_oidc_client_id(settings.proxy_hostname)

    access = await _access_stats(db)

    clients_res = await db.execute(select(OIDCClient.client_id, OIDCClient.name))
    client_name_map = {row.client_id: row.name for row in clients_res.all()}

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
        "cie_config": cie_config,
        "cie_oidc_client_id": cie_oidc_client_id,
        "access": access,
        "client_name_map": client_name_map,
    })
