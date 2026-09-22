import hashlib
import os
from urllib.parse import quote

from defusedxml import ElementTree
from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
        # Atomic write: write to a temp file in the same directory then
        # os.replace() (atomic on POSIX) into place, so a concurrent public
        # request to /spidSaml2/metadata never observes a truncated/partial
        # file (this repo only runs on Linux containers for SATOSA/config-api).
        tmp_path = override_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(version.xml_content)
        os.replace(tmp_path, override_path)

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


@router.post("/metadata/{version_id}/validate")
async def metadata_validate(version_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == version_id))
    if not result.scalar_one_or_none():
        return RedirectResponse(f"/admin/metadata?error={quote('Versione non trovata.')}", status_code=303)

    all_versions = await db.execute(select(SpidMetadataVersion))
    for v in all_versions.scalars().all():
        v.is_validated = v.id == version_id
    await db.commit()
    return RedirectResponse("/admin/metadata", status_code=303)


@router.post("/metadata/upload")
async def metadata_upload(request: Request, db: AsyncSession = Depends(get_db), file: UploadFile = File(...)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    raw = await file.read()
    try:
        xml_text = raw.decode("utf-8")
        root = ElementTree.fromstring(xml_text)
    except Exception:
        return RedirectResponse(
            f"/admin/metadata?error={quote('File non valido: XML non ben formato.')}", status_code=303
        )
    if not root.tag.endswith("}EntityDescriptor") and root.tag != "EntityDescriptor":
        return RedirectResponse(
            f"/admin/metadata?error={quote('File non valido: root deve essere EntityDescriptor.')}",
            status_code=303,
        )

    content_hash = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
    row = SpidMetadataVersion(source="uploaded", xml_content=xml_text, content_hash=content_hash, is_exposed=False)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return RedirectResponse(
            f"/admin/metadata?error={quote('Questa versione di metadata è già stata caricata in precedenza.')}",
            status_code=303,
        )
    return RedirectResponse("/admin/metadata", status_code=303)


@router.get("/metadata/{version_id}/download")
async def metadata_download(version_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == version_id))
    version = result.scalar_one_or_none()
    if not version:
        return RedirectResponse(f"/admin/metadata?error={quote('Versione non trovata.')}", status_code=303)
    return PlainTextResponse(
        version.xml_content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="spid_metadata_{version_id}.xml"'},
    )


@router.post("/metadata/{version_id}/delete")
async def metadata_delete(version_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == version_id))
    version = result.scalar_one_or_none()
    if not version:
        return RedirectResponse(f"/admin/metadata?error={quote('Versione non trovata.')}", status_code=303)
    if version.is_exposed or version.is_validated:
        return RedirectResponse(
            f"/admin/metadata?error={quote('Impossibile eliminare una versione esposta o validata.')}",
            status_code=303,
        )
    await db.delete(version)
    await db.commit()
    return RedirectResponse("/admin/metadata", status_code=303)
