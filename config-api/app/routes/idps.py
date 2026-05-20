import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metadata_watcher import fetch_idp_metadata
from app.models import SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/idps", response_class=HTMLResponse)
async def idps_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidIdP).order_by(SpidIdP.display_name))
    idps = result.scalars().all()
    return templates.TemplateResponse(request, "idps/list.html.j2", {"idps": idps})


@router.post("/idps/{idp_id}/toggle")
async def idps_toggle(request: Request, idp_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidIdP).where(SpidIdP.id == idp_id))
    idp = result.scalar_one_or_none()
    if idp:
        idp.enabled = not idp.enabled
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
