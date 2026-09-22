import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import SpidCert, SpidMetadataVersion

router = APIRouter()


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/metadata", response_class=HTMLResponse)
async def metadata_history(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidMetadataVersion).order_by(SpidMetadataVersion.created_at.desc()))
    versions = result.scalars().all()

    active_cert_result = await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))
    active_cert = active_cert_result.scalar_one_or_none()

    return templates.TemplateResponse(
        request,
        "metadata/history.html.j2",
        {
            "versions": versions,
            "active_cert_id": active_cert.id if active_cert else None,
            "error": request.query_params.get("error"),
            "warning": request.query_params.get("warning"),
        },
    )


def _override_path() -> str:
    conf_dir = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")
    return os.path.join(conf_dir, "spid_sp_metadata_override.xml")


@router.post("/metadata/{version_id}/expose")
async def metadata_expose(version_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    result = await db.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == version_id))
    version = result.scalar_one_or_none()
    if not version:
        return RedirectResponse(
            f"/admin/metadata?error={quote('Versione non trovata.')}", status_code=303
        )

    latest_generated_result = await db.execute(
        select(SpidMetadataVersion)
        .where(SpidMetadataVersion.source == "generated")
        .order_by(SpidMetadataVersion.created_at.desc(), SpidMetadataVersion.id.desc())
        .limit(1)
    )
    latest_generated = latest_generated_result.scalar_one_or_none()

    all_versions = await db.execute(select(SpidMetadataVersion))
    for v in all_versions.scalars().all():
        v.is_exposed = v.id == version_id
    await db.commit()

    override_path = _override_path()
    if latest_generated is not None and version.id == latest_generated.id:
        if os.path.exists(override_path):
            os.remove(override_path)
    else:
        os.makedirs(os.path.dirname(override_path), exist_ok=True)
        with open(override_path, "w", encoding="utf-8") as f:
            f.write(version.xml_content)

    warning = None
    if version.cert_id is not None:
        active_cert_result = await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))
        active_cert = active_cert_result.scalar_one_or_none()
        if active_cert is None or active_cert.id != version.cert_id:
            warning = quote(
                "Attenzione: questa versione di metadata è firmata con un certificato diverso "
                "da quello attualmente attivo. Il metadata esposto potrebbe non corrispondere "
                "al certificato in uso su SATOSA."
            )

    redirect_url = "/admin/metadata"
    if warning:
        redirect_url += f"?warning={warning}"
    return RedirectResponse(redirect_url, status_code=303)
