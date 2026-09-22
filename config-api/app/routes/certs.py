from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, SpidCert
from app.spid_cert import generate_spid_cert
from app.spid_cert_writer import write_spid_cert
from app.satosa_generator import generate_and_write

from urllib.parse import quote

router = APIRouter()


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/certs", response_class=HTMLResponse)
async def certs_history(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).order_by(SpidCert.created_at.desc()))
    certs = result.scalars().all()
    return templates.TemplateResponse(
        request,
        "certs/status.html.j2",
        {
            "certs": certs,
            "now": datetime.now(timezone.utc),
            "cert_error": request.query_params.get("cert_error"),
        },
    )


@router.get("/certs/{cert_id}/download/cert")
async def certs_download_cert(cert_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).where(SpidCert.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404)
    return PlainTextResponse(
        cert.certificate_pem,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="spid_sp_cert_{cert_id}.pem"'},
    )


@router.get("/certs/{cert_id}/download/key")
async def certs_download_key(cert_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).where(SpidCert.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404)
    return PlainTextResponse(
        cert.private_key_pem,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="spid_sp_key_{cert_id}.pem"'},
    )


@router.post("/certs/{cert_id}/activate")
async def certs_activate(cert_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).where(SpidCert.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404)

    all_certs = await db.execute(select(SpidCert))
    for c in all_certs.scalars().all():
        c.is_active = c.id == cert_id
    await db.commit()

    import asyncio
    try:
        await asyncio.to_thread(write_spid_cert, cert)
        await generate_and_write(db)
    except Exception:
        pass
    return RedirectResponse("/admin/certs", status_code=303)


@router.post("/certs/{cert_id}/delete")
async def certs_delete(cert_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).where(SpidCert.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404)
    if cert.is_active:
        return RedirectResponse(
            f"/admin/certs?cert_error={quote('Impossibile eliminare il certificato attivo.')}",
            status_code=303,
        )
    await db.delete(cert)
    await db.commit()
    return RedirectResponse("/admin/certs", status_code=303)


@router.post("/certs/generate")
async def certs_generate(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()

    redirect_to = request.query_params.get("redirect_to", "/admin/idps")

    missing = not s or not all([s.proxy_hostname, s.org_name, s.ipa_code, s.org_city])
    if missing:
        err_msg = "Configura prima le impostazioni ente (proxy_hostname, org_name, ipa_code, org_city)."
        return RedirectResponse(f"{redirect_to}?cert_error={quote(err_msg)}", status_code=303)
    try:
        cert_obj = generate_spid_cert(s)
    except ValueError as exc:
        return RedirectResponse(f"{redirect_to}?cert_error={quote(str(exc))}", status_code=303)

    existing = await db.execute(select(SpidCert))
    for c in existing.scalars().all():
        c.is_active = False
    cert_obj.is_active = True
    db.add(cert_obj)
    await db.commit()

    import asyncio
    try:
        await asyncio.to_thread(write_spid_cert, cert_obj)
        await generate_and_write(db)
    except Exception:
        pass
    return RedirectResponse(redirect_to, status_code=303)
