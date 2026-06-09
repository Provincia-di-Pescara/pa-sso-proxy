import asyncio
import os
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metadata_watcher import fetch_idp_metadata
from app.models import SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa
from app.spid_seeder import sync_spid_idps_from_registry

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

SPID_REGISTRY_API_LIST_URL = os.environ.get(
    "SPID_REGISTRY_API_LIST_URL",
    "https://registry.spid.gov.it/entities-idp?output=json&page=1&numMetadata=50",
)
SPID_REGISTRY_API_DETAIL_URL = os.environ.get(
    "SPID_REGISTRY_API_DETAIL_URL",
    "https://registry.spid.gov.it/entities-idp/{entity_id}?output=json",
)


async def _fetch_spid_registry_idps() -> dict:
    request_url = SPID_REGISTRY_API_LIST_URL
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(SPID_REGISTRY_API_LIST_URL, headers={"Accept": "application/json"})
            response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            items = payload.get("Entita") or payload.get("entita") or payload.get("entities") or payload.get("items") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []

        results = []
        for item in items:
            if isinstance(item, dict):
                entity_id = item.get("entity_id") or item.get("entityId") or item.get("sp_entityid") or ""
                results.append({
                    "entity_id": entity_id,
                    "logo_uri": item.get("logo_uri") or "",
                    "organization_name": item.get("organization_name") or "",
                    "lastupdate_date": item.get("lastupdate_date") or "",
                    "disabled": item.get("_disabled") or item.get("disabled") or "",
                    "detail_url": f"/admin/idps/detail?entity_id={quote(entity_id, safe='')}",
                })
            else:
                entity_id = str(item)
                results.append({
                    "entity_id": entity_id,
                    "logo_uri": "",
                    "organization_name": "",
                    "lastupdate_date": "",
                    "disabled": "",
                    "detail_url": f"/admin/idps/detail?entity_id={quote(entity_id, safe='')}",
                })

        return {
            "request_url": request_url,
            "ok": True,
            "headers": {
                "tot_metadata": response.headers.get("Tot-Metadata"),
                "tot_pages": response.headers.get("Tot-Pages"),
                "current_page": response.headers.get("Current-Page"),
            },
            "results": results,
        }
    except Exception as exc:
        return {
            "request_url": request_url,
            "ok": False,
            "error": str(exc),
            "headers": {},
            "results": [],
        }


async def _fetch_spid_registry_idp_detail(entity_id: str) -> dict:
    encoded_entity_id = quote(entity_id, safe="")
    request_url = SPID_REGISTRY_API_DETAIL_URL.format(entity_id=encoded_entity_id)
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(request_url, headers={"Accept": "application/json"})
            response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            payload = payload[0] if payload else {}
        if not isinstance(payload, dict):
            payload = {}

        return {
            "request_url": request_url,
            "ok": True,
            "headers": {
                "tot_metadata": response.headers.get("Tot-Metadata"),
                "tot_pages": response.headers.get("Tot-Pages"),
                "current_page": response.headers.get("Current-Page"),
                "last_modified": response.headers.get("Last-Modified"),
            },
            "detail": payload,
        }
    except Exception as exc:
        return {
            "request_url": request_url,
            "ok": False,
            "error": str(exc),
            "headers": {},
            "detail": {},
        }


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/idps", response_class=HTMLResponse)
async def idps_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidIdP).where(SpidIdP.registry_entity_id != None).order_by(SpidIdP.registry_organization_name))
    idps = list(result.scalars().all())
    sync_status = request.query_params.get("sync")
    sync_inserted = request.query_params.get("inserted")
    sync_error = request.query_params.get("error")
    last_sync_result = await db.execute(select(func.max(SpidIdP.registry_synced_at)))
    last_sync_at = last_sync_result.scalar_one_or_none()

    demo_result = await db.execute(select(SpidIdP).where(SpidIdP.alias == "spid-demo"))
    demo_idp = demo_result.scalar_one_or_none()

    validator_result = await db.execute(select(SpidIdP).where(SpidIdP.alias == "spid-validator"))
    validator_idp = validator_result.scalar_one_or_none()

    return templates.TemplateResponse(
        request,
        "idps/list.html.j2",
        {
            "idps": idps,
            "sync_status": sync_status,
            "sync_inserted": sync_inserted,
            "sync_error": sync_error,
            "last_sync_at": last_sync_at,
            "demo_idp": demo_idp,
            "validator_idp": validator_idp,
        },
    )


@router.post("/idps/sync")
async def idps_sync(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    try:
        inserted = await sync_spid_idps_from_registry(db)
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
        return RedirectResponse(f"/admin/idps?sync=ok&inserted={inserted}", status_code=302)
    except Exception:
        return RedirectResponse("/admin/idps?sync=error&error=registry_sync_failed", status_code=302)


@router.get("/idps/detail", response_class=HTMLResponse)
async def idps_detail(request: Request, entity_id: str):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    detail_call = await _fetch_spid_registry_idp_detail(entity_id)
    return templates.TemplateResponse(request, "idps/detail.html.j2", {"detail_call": detail_call})


@router.post("/idps/{idp_id}/toggle")
async def idps_toggle(request: Request, idp_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidIdP).where(SpidIdP.id == idp_id))
    idp = result.scalar_one_or_none()
    if idp:
        idp.enabled = not idp.enabled
        
        # Enforce mutual exclusion for demo and validator testing environments
        if idp.enabled:
            if idp.alias == "spid-demo":
                v_res = await db.execute(select(SpidIdP).where(SpidIdP.alias == "spid-validator"))
                v_idp = v_res.scalar_one_or_none()
                if v_idp:
                    v_idp.enabled = False
            elif idp.alias == "spid-validator":
                d_res = await db.execute(select(SpidIdP).where(SpidIdP.alias == "spid-demo"))
                d_idp = d_res.scalar_one_or_none()
                if d_idp:
                    d_idp.enabled = False
                    
        await db.commit()
        try:
            await generate_and_write(db)
            await asyncio.to_thread(reload_satosa)
        except Exception:
            pass
    return RedirectResponse("/admin/idps", status_code=302)


@router.post("/idps/{idp_id}/refresh")
async def idps_refresh(request: Request, idp_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidIdP).where(SpidIdP.id == idp_id))
    idp = result.scalar_one_or_none()
    if idp:
        try:
            updated = await fetch_idp_metadata(db, idp)
            if updated:
                await generate_and_write(db)
                await asyncio.to_thread(reload_satosa)
        except Exception:
            pass
    return RedirectResponse("/admin/idps", status_code=302)
