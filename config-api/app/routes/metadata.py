import asyncio
import os
from urllib.parse import quote

from defusedxml import ElementTree
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metadata_profile import (
    CertConfirmationRequired,
    CertMissing,
    create_validated_profile,
    metadata_fingerprint,
    override_path,
    restore_profile,
)
from app.models import SpidMetadataProfile, SpidMetadataVersion
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()

_TAB = "#gestione-metadata"


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


def _redirect(error: str | None = None, warning: str | None = None, info: str | None = None) -> RedirectResponse:
    params = []
    if error:
        params.append(f"metadata_error={quote(error)}")
    if warning:
        params.append(f"metadata_warning={quote(warning)}")
    if info:
        params.append(f"metadata_info={quote(info)}")
    query = ("?" + "&".join(params)) if params else ""
    return RedirectResponse(f"/admin/idps{query}{_TAB}", status_code=303)


async def _regenerate(db: AsyncSession) -> None:
    try:
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    except Exception:
        pass


@router.get("/metadata")
async def metadata_history_redirect(request: Request):
    """Pagina dedicata rimossa: lo storico metadata ora vive come tab di /admin/idps."""
    return RedirectResponse("/admin/idps#gestione-metadata", status_code=301)


@router.post("/metadata/regenerate")
async def metadata_regenerate(request: Request, db: AsyncSession = Depends(get_db)):
    """Forza un reload SATOSA (senza toccare le chiavi) per ottenere uno snapshot
    di metadata fresco firmato con il certificato attivo corrente."""
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    await _regenerate(db)
    return RedirectResponse("/admin/idps#gestione-metadata", status_code=303)


# --- Profilo validato ---------------------------------------------------------

@router.post("/metadata/profile/validate")
async def metadata_profile_validate(request: Request, label: str = Form(default=""), db: AsyncSession = Depends(get_db)):
    """Segna validato: fotografa la configurazione ATTUALE (parametri + ultimo metadata)."""
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    await create_validated_profile(db, label)
    return _redirect(info="Configurazione attuale segnata come validata da AgID.")


@router.post("/metadata/profile/{profile_id}/restore")
async def metadata_profile_restore(
    profile_id: int,
    request: Request,
    confirm_cert: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Riapplica i parametri del profilo e rigenera il metadata (nessun file di override)."""
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    profile = (
        await db.execute(select(SpidMetadataProfile).where(SpidMetadataProfile.id == profile_id))
    ).scalar_one_or_none()
    if profile is None:
        return _redirect(error="Profilo non trovato.")
    try:
        cert_changed = await restore_profile(db, profile, confirm_cert == "yes")
    except CertConfirmationRequired:
        return _redirect(
            error="Il ripristino riattiva un certificato diverso da quello attivo: serve la conferma."
        )
    except CertMissing:
        return _redirect(
            error="Il certificato del profilo non esiste più (eliminato o non incluso nel backup): ripristino non possibile."
        )
    except ValueError as exc:
        return _redirect(error=str(exc))
    await _regenerate(db)
    msg = "Configurazione ripristinata"
    if cert_changed:
        msg += f", certificato #{profile.cert_id} riattivato"
    return _redirect(info=msg + ". SATOSA rigenera il metadata: ricarica la pagina tra qualche secondo per la verifica.")


# --- Metadata caricato a mano (unico uso del file di override) -----------------

def _write_override(xml_content: str) -> None:
    path = override_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Scrittura atomica: una richiesta pubblica a /spidSaml2/metadata non deve
    # mai leggere un file a metà.
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
    os.replace(tmp_path, path)


@router.post("/metadata/{version_id}/expose")
async def metadata_expose(version_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Pubblica un metadata caricato a mano al posto di quello generato (emergenza).

    Le righe generate non si espongono più: per tornare a una configurazione
    validata si usa "Ripristina validato", che rigenera il metadata.
    """
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    version = (
        await db.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == version_id))
    ).scalar_one_or_none()
    if version is None:
        return _redirect(error="Versione non trovata.")
    if version.source != "uploaded":
        return _redirect(error="Si possono esporre solo i metadata caricati a mano.")
    for v in (await db.execute(select(SpidMetadataVersion))).scalars():
        v.is_exposed = v.id == version_id
    await db.commit()
    _write_override(version.xml_content)
    return _redirect(warning="Metadata caricato a mano pubblicato: le modifiche di configurazione non vengono pubblicate finché resta attivo.")


@router.post("/metadata/override/clear")
async def metadata_override_clear(request: Request, db: AsyncSession = Depends(get_db)):
    """Torna al metadata generato da SATOSA."""
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    path = override_path()
    if os.path.exists(path):
        os.remove(path)
    for v in (await db.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.is_exposed == True))).scalars():  # noqa: E712
        v.is_exposed = False
    await db.commit()
    return _redirect(info="Pubblicato di nuovo il metadata generato da SATOSA.")


@router.post("/metadata/upload")
async def metadata_upload(request: Request, db: AsyncSession = Depends(get_db), file: UploadFile = File(...)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    raw = await file.read()
    try:
        xml_text = raw.decode("utf-8")
        root = ElementTree.fromstring(xml_text)
    except Exception:
        return _redirect(error="File non valido: XML non ben formato.")
    if not root.tag.endswith("}EntityDescriptor") and root.tag != "EntityDescriptor":
        return _redirect(error="File non valido: root deve essere EntityDescriptor.")

    content_hash = metadata_fingerprint(xml_text)
    dup_result = await db.execute(
        select(SpidMetadataVersion)
        .where(SpidMetadataVersion.source == "uploaded")
        .where(SpidMetadataVersion.content_hash == content_hash)
        .limit(1)
    )
    if dup_result.scalar_one_or_none() is not None:
        return _redirect(error="Questa versione di metadata è già stata caricata in precedenza.")
    db.add(SpidMetadataVersion(source="uploaded", xml_content=xml_text, content_hash=content_hash, is_exposed=False))
    await db.commit()
    return RedirectResponse("/admin/idps#gestione-metadata", status_code=303)


@router.get("/metadata/{version_id}/download")
async def metadata_download(version_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == version_id))
    version = result.scalar_one_or_none()
    if not version:
        return _redirect(error="Versione non trovata.")
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
        return _redirect(error="Versione non trovata.")
    if version.is_exposed:
        return _redirect(error="Impossibile eliminare il metadata pubblicato.")
    in_profile = (
        await db.execute(
            select(SpidMetadataProfile.id).where(SpidMetadataProfile.metadata_version_id == version_id).limit(1)
        )
    ).scalar_one_or_none()
    if in_profile is not None:
        return _redirect(error="Impossibile eliminare il metadata di un profilo validato o archiviato.")
    await db.delete(version)
    await db.commit()
    return RedirectResponse("/admin/idps#gestione-metadata", status_code=303)
