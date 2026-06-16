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
from app.models import EnteSettings, SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()


def _auth_check(request: Request):
    return request.session.get("user")


async def check_sp_metadata() -> dict:
    satosa_url = os.environ.get("SATOSA_INTERNAL_URL", "http://satosa:8080")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{satosa_url}/spidSaml2/metadata")
        if resp.status_code != 200:
            return {"valid": False, "error": f"HTTP {resp.status_code} dal server SATOSA"}
        
        # Parse XML
        root = ET.fromstring(resp.content)
        # Namespaces
        namespaces = {
            'md': 'urn:oasis:names:tc:SAML:2.0:metadata'
        }
        
        # Find all AttributeConsumingService elements
        acs_list = root.findall('.//md:AttributeConsumingService', namespaces)
        indices = [acs.attrib.get('index') for acs in acs_list if 'index' in acs.attrib]
        
        has_spid = '0' in indices or len(indices) > 0
        has_eidas = '99' in indices and '100' in indices
        
        return {
            "valid": True,
            "indices": indices,
            "has_spid": has_spid,
            "has_eidas": has_eidas,
        }
    except Exception as e:
        return {"valid": False, "error": f"Errore di connessione a SATOSA: {str(e)}"}


@router.get("/eidas", response_class=HTMLResponse)
async def eidas_config_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    s = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()
    proxy_hostname = s.proxy_hostname if s else "localhost"
    
    metadata_status = await check_sp_metadata()

    return templates.TemplateResponse(
        request,
        "eidas/config.html.j2",
        {
            "s": s,
            "proxy_hostname": proxy_hostname,
            "metadata_status": metadata_status,
        },
    )


@router.post("/eidas/toggle")
async def eidas_toggle(
    request: Request,
    action: str = Form(...),
    confirmed: str = Form(default=""),
    environment: str = Form(default="prod"),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    s = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()
    if s is None:
        return RedirectResponse("/admin/eidas", status_code=302)

    enable = action == "enable"

    if enable and confirmed != "yes":
        return RedirectResponse("/admin/eidas?eidas_warning=1", status_code=302)

    s.eidas_enabled = enable
    s.eidas_environment = environment

    # Sync IdP records: enable correct one, disable the other
    for alias in ("eidas-qa", "eidas-prod"):
        idp = (await db.execute(select(SpidIdP).where(SpidIdP.alias == alias))).scalar_one_or_none()
        if idp:
            idp.enabled = enable and (
                (alias == "eidas-qa" and environment == "qa") or
                (alias == "eidas-prod" and environment == "prod")
            )

    await db.commit()
    await generate_and_write(db)
    await asyncio.to_thread(reload_satosa)

    return RedirectResponse("/admin/eidas?saved=1", status_code=302)
