import asyncio
import secrets

import bcrypt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, OIDCClient
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()



def _auth_check(request: Request):
    return request.session.get("user") is not None


@router.get("/clients", response_class=HTMLResponse)
async def clients_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(OIDCClient).order_by(OIDCClient.created_at.desc()))
    clients = result.scalars().all()
    return templates.TemplateResponse(request, "clients/list.html.j2", {"clients": clients})


@router.get("/clients/new", response_class=HTMLResponse)
async def clients_new(request: Request):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    return templates.TemplateResponse(request, "clients/form.html.j2", {"client": None, "error": None})


@router.post("/clients/new")
async def clients_create(
    request: Request,
    name: str = Form(...),
    redirect_uris: str = Form(...),
    scopes: list[str] = Form(default=[]),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    uris = [u.strip() for u in redirect_uris.splitlines() if u.strip()]
    if not uris:
        return templates.TemplateResponse(
            request,
            "clients/form.html.j2",
            {"client": None, "error": "Almeno una redirect URI obbligatoria"},
            status_code=400,
        )

    client_id = "client-" + secrets.token_urlsafe(8)
    client_secret = secrets.token_urlsafe(32)
    secret_hash = bcrypt.hashpw(client_secret.encode(), bcrypt.gensalt()).decode()

    c = OIDCClient(
        client_id=client_id,
        client_secret_hash=secret_hash,
        client_secret_plain=client_secret,
        name=name,
        redirect_uris=uris,
        allowed_scopes=scopes or ["openid"],
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)

    await generate_and_write(db)
    await asyncio.to_thread(reload_satosa)

    request.session["reveal_secret"] = client_secret
    request.session["reveal_client_id"] = client_id
    request.session["reveal_is_new"] = True
    return RedirectResponse(f"/admin/clients/{c.id}/reveal", status_code=302)


@router.get("/clients/{client_id}/reveal", response_class=HTMLResponse)
async def clients_reveal(request: Request, client_id: int):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    secret = request.session.pop("reveal_secret", None)
    cid = request.session.pop("reveal_client_id", None)
    is_new = request.session.pop("reveal_is_new", False)
    return templates.TemplateResponse(
        request, "clients/reveal.html.j2", {"client_id": cid, "client_secret": secret, "is_new": is_new}
    )


@router.get("/clients/{client_id}/secret", response_class=HTMLResponse)
async def clients_view_secret(request: Request, client_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(OIDCClient).where(OIDCClient.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        return RedirectResponse("/admin/clients", status_code=302)
    return templates.TemplateResponse(
        request,
        "clients/reveal.html.j2",
        {"client_id": client.client_id, "client_secret": client.client_secret_plain, "is_new": False},
    )


@router.get("/clients/{client_id}/edit", response_class=HTMLResponse)
async def clients_edit_form(request: Request, client_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(OIDCClient).where(OIDCClient.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        return RedirectResponse("/admin/clients", status_code=302)
    settings_result = await db.execute(select(EnteSettings).limit(1))
    settings = settings_result.scalar_one_or_none()
    proxy_hostname = settings.proxy_hostname if settings and settings.proxy_hostname else ""
    return templates.TemplateResponse(
        request,
        "clients/form.html.j2",
        {"client": client, "error": None, "proxy_hostname": proxy_hostname},
    )


@router.post("/clients/{client_id}/edit")
async def clients_update(
    request: Request,
    client_id: int,
    name: str = Form(...),
    redirect_uris: str = Form(...),
    scopes: list[str] = Form(default=[]),
    enabled: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(OIDCClient).where(OIDCClient.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        return RedirectResponse("/admin/clients", status_code=302)

    uris = [u.strip() for u in redirect_uris.splitlines() if u.strip()]
    if not uris:
        return templates.TemplateResponse(
            request,
            "clients/form.html.j2",
            {"client": client, "error": "Almeno una redirect URI obbligatoria"},
            status_code=400,
        )
    client.name = name
    client.redirect_uris = uris
    client.allowed_scopes = scopes or ["openid"]
    client.enabled = enabled == "1"
    await db.commit()

    await generate_and_write(db)
    await asyncio.to_thread(reload_satosa)
    return RedirectResponse("/admin/clients", status_code=302)


@router.post("/clients/{client_id}/toggle")
async def clients_toggle(request: Request, client_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(OIDCClient).where(OIDCClient.id == client_id))
    client = result.scalar_one_or_none()
    if client:
        client.enabled = not client.enabled
        await db.commit()
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    return RedirectResponse("/admin/clients", status_code=302)


@router.post("/clients/{client_id}/delete")
async def clients_delete(request: Request, client_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(OIDCClient).where(OIDCClient.id == client_id))
    client = result.scalar_one_or_none()
    if client:
        await db.delete(client)
        await db.commit()
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    return RedirectResponse("/admin/clients", status_code=302)
