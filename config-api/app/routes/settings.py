import asyncio

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()



def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/settings", response_class=HTMLResponse)
async def settings_form(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()
    return templates.TemplateResponse(request, "settings/form.html.j2", {"s": s, "error": None, "saved": False})


@router.post("/settings")
async def settings_save(
    request: Request,
    org_display_name: str = Form(default=""),
    org_name: str = Form(...),
    org_url: str = Form(default=""),
    proxy_hostname: str = Form(...),
    ipa_code: str = Form(...),
    contact_email: str = Form(default=""),
    contact_phone: str = Form(default=""),
    org_city: str = Form(...),
    logo_url: str = Form(default=""),
    favicon_url: str = Form(default=""),
    privacy_url: str = Form(default=""),
    legal_notes_url: str = Form(default=""),
    accessibility_url: str = Form(default=""),
    support_url: str = Form(default=""),
    vat_number: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()
    if s is None:
        s = EnteSettings(id=1)
        db.add(s)
    s.org_display_name = org_display_name
    s.org_name = org_name
    s.org_url = org_url
    s.proxy_hostname = proxy_hostname
    s.ipa_code = ipa_code
    s.contact_email = contact_email
    s.contact_phone = contact_phone
    s.org_city = org_city
    s.logo_url = logo_url
    s.favicon_url = favicon_url
    s.privacy_url = privacy_url
    s.legal_notes_url = legal_notes_url
    s.accessibility_url = accessibility_url
    s.support_url = support_url
    s.vat_number = vat_number
    await db.commit()
    return RedirectResponse("/admin/settings", status_code=302)


