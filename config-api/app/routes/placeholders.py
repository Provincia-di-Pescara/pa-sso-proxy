from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.jinja_templates import templates

router = APIRouter()


def _auth_check(request: Request):
    return request.session.get("user")


@router.get("/eidas", response_class=HTMLResponse)
async def eidas_page(request: Request):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    return templates.TemplateResponse(request, "placeholders/coming_soon.html.j2", {
        "title": "eIDAS",
        "description": "Supporto per autenticazione tramite identità digitale europea (eIDAS / European Digital Identity Wallet).",
    })


@router.get("/itwallet", response_class=HTMLResponse)
async def itwallet_page(request: Request):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    return templates.TemplateResponse(request, "placeholders/coming_soon.html.j2", {
        "title": "IT Wallet",
        "description": "Supporto per IT Wallet — portafoglio digitale italiano (D.Lgs. 36/2025).",
    })
