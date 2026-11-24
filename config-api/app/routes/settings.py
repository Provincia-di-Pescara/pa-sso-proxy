import asyncio
import re
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa
from app.url_validation import valid_public_url

router = APIRouter()



def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


# Finiscono come href/src nelle pagine pubbliche (discovery, errore, /verifica)
# e nell'admin: solo http(s) o path locale, mai javascript:/data:/altro.
_URL_FIELDS = {
    "org_url": "Sito ente",
    "logo_url": "Logo",
    "favicon_url": "Favicon",
    "privacy_url": "Privacy",
    "legal_notes_url": "Note legali",
    "accessibility_url": "Accessibilità",
    "support_url": "Supporto",
}
# Va in URL, metadata SPID, DN del certificato e YAML SATOSA: solo hostname[:porta].
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}(:|$))[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*(?::[0-9]{1,5})?$"
)
def validate_settings(values: dict) -> str | None:
    """Messaggio d'errore per il primo campo non valido, None se tutto ok."""
    if not _HOSTNAME_RE.match(values.get("proxy_hostname", "")):
        return "Hostname proxy non valido: solo nome host (es. sso.ente.it), senza schema né percorso."
    for field, label in _URL_FIELDS.items():
        if not valid_public_url(values.get(field, "")):
            return f"{label}: URL non valido (ammessi https://..., http://... o un percorso che inizia con /)."
    return None


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
    values = {k: v.strip() if isinstance(v, str) else v for k, v in dict(
        org_display_name=org_display_name, org_name=org_name, org_url=org_url,
        proxy_hostname=proxy_hostname, ipa_code=ipa_code, contact_email=contact_email,
        contact_phone=contact_phone, org_city=org_city, logo_url=logo_url,
        favicon_url=favicon_url, privacy_url=privacy_url, legal_notes_url=legal_notes_url,
        accessibility_url=accessibility_url, support_url=support_url, vat_number=vat_number,
    ).items()}
    error = validate_settings(values)
    if error:
        return templates.TemplateResponse(
            request, "settings/form.html.j2",
            {"s": SimpleNamespace(**values), "error": error, "saved": False},
            status_code=400,
        )
    (org_display_name, org_name, org_url, proxy_hostname, ipa_code, contact_email,
     contact_phone, org_city, logo_url, favicon_url, privacy_url, legal_notes_url,
     accessibility_url, support_url, vat_number) = values.values()
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


