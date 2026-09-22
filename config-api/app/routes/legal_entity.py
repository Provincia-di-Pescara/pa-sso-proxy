import asyncio
import os
import xml.etree.ElementTree as ET
import httpx

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jinja_templates import templates
from app.models import EnteSettings
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()


def _auth_check(request: Request):
    return request.session.get("user")


async def check_company_attributes() -> dict:
    """Verifica se il metadata SP pubblicato dichiara gli attributi
    opzionali azienda (companyName) in un qualsiasi AttributeConsumingService
    (l'ACS dedicato persona giuridica non è necessariamente index 0)."""
    satosa_url = os.environ.get("SATOSA_INTERNAL_URL", "http://satosa:8080")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{satosa_url}/spidSaml2/metadata")
        if resp.status_code != 200:
            return {"valid": False, "error": f"HTTP {resp.status_code} dal server SATOSA"}

        root = ET.fromstring(resp.content)
        namespaces = {
            'md': 'urn:oasis:names:tc:SAML:2.0:metadata',
            'saml2': 'urn:oasis:names:tc:SAML:2.0:assertion',
        }
        acs_list = root.findall('.//md:AttributeConsumingService', namespaces)
        has_company = False
        for acs in acs_list:
            attr_names = [
                a.attrib.get('Name')
                for a in acs.findall('md:RequestedAttribute', namespaces)
            ]
            if 'companyName' in attr_names:
                has_company = True
                break
        return {"valid": True, "has_company_attributes": has_company}
    except Exception as e:
        return {"valid": False, "error": f"Errore di connessione a SATOSA: {str(e)}"}


@router.get("/legal-entity", response_class=HTMLResponse)
async def legal_entity_config_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    s = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()

    saved = request.query_params.get("saved") == "1"
    metadata_status = None if saved else await check_company_attributes()

    return templates.TemplateResponse(
        request,
        "legal_entity/config.html.j2",
        {
            "s": s,
            "saved": saved,
            "metadata_status": metadata_status,
        },
    )


@router.post("/legal-entity/toggle")
async def legal_entity_toggle(
    request: Request,
    confirmed: str = Form(default=""),
    legal_entity_enabled: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    s = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()
    if s is None:
        return RedirectResponse("/admin/legal-entity", status_code=302)

    enable = legal_entity_enabled in ("yes", "on", "true", "1")

    if enable and confirmed != "yes":
        return RedirectResponse("/admin/legal-entity?warning=1", status_code=302)

    s.legal_entity_enabled = enable
    await db.commit()

    try:
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    except Exception:
        pass

    return RedirectResponse("/admin/legal-entity?saved=1", status_code=302)
