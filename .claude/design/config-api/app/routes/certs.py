from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, SpidCert
from app.spid_cert import generate_spid_cert

router = APIRouter()



def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/certs", response_class=HTMLResponse)
async def certs_status(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).order_by(SpidCert.created_at.desc()).limit(1))
    cert = result.scalar_one_or_none()
    return templates.TemplateResponse(
        request, "certs/status.html.j2",
        {"cert": cert, "error": None, "now": datetime.now(timezone.utc)},
    )


@router.post("/certs/generate")
async def certs_generate(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()
    missing = not s or not all([s.proxy_hostname, s.org_name, s.ipa_code, s.org_city])
    if missing:
        return templates.TemplateResponse(
            request, "certs/status.html.j2",
            {
                "cert": None,
                "error": "Configura prima le impostazioni ente (proxy_hostname, org_name, ipa_code, org_city).",
                "now": datetime.now(timezone.utc),
            },
            status_code=400,
        )
    try:
        cert_obj = generate_spid_cert(s)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "certs/status.html.j2",
            {"cert": None, "error": str(exc), "now": datetime.now(timezone.utc)},
            status_code=400,
        )
    db.add(cert_obj)
    await db.commit()
    import asyncio
    from app.spid_cert_writer import write_spid_cert
    from app.satosa_generator import generate_and_write
    try:
        await asyncio.to_thread(write_spid_cert, cert_obj)
        await generate_and_write(db)
    except Exception:
        pass
    return RedirectResponse("/admin/certs", status_code=302)
