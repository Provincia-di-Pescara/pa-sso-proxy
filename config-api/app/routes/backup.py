"""
Backup & Ripristino — /admin/backup
====================================
GET  /admin/backup          → pagina HTML
GET  /admin/backup/export   → scarica bundle JSON con tutta la configurazione
POST /admin/backup/import   → carica bundle JSON e ripristina la configurazione
"""
import io
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jinja_templates import templates
from app.models import CieConfig, EnteSettings, JwkKey, OIDCClient, SpidCert, SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

logger = logging.getLogger(__name__)

router = APIRouter()

BACKUP_VERSION = "1"

# ---------------------------------------------------------------------------
# Helper auth
# ---------------------------------------------------------------------------

def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


# ---------------------------------------------------------------------------
# Serializzatori per tabella
# ---------------------------------------------------------------------------

def _row_to_dict(obj, exclude: set[str] | None = None) -> dict:
    """Converte un'istanza SQLAlchemy in dizionario JSON-serializable."""
    exclude = exclude or set()
    result = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        elif isinstance(val, (list, dict)):
            pass  # già JSON-serializable
        result[col.name] = val
    return result


async def _export_bundle(db: AsyncSession) -> dict:
    """Legge tutte le tabelle e costruisce il bundle JSON."""

    # ente_settings
    res = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    settings = res.scalar_one_or_none()
    settings_dict = _row_to_dict(settings) if settings else {}

    # oidc_clients
    res = await db.execute(select(OIDCClient).order_by(OIDCClient.id))
    clients = [_row_to_dict(c) for c in res.scalars().all()]

    # spid_idps — inclusi metadata_cache/hash/last_updated per evitare rifederazione
    res = await db.execute(select(SpidIdP).order_by(SpidIdP.id))
    idps = [_row_to_dict(idp) for idp in res.scalars().all()]

    # cie_config
    res = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    cie = res.scalar_one_or_none()
    cie_dict = _row_to_dict(cie) if cie else {}

    # jwk_keys
    res = await db.execute(select(JwkKey).order_by(JwkKey.id))
    keys = [_row_to_dict(k) for k in res.scalars().all()]

    # spid_cert (più recente)
    res = await db.execute(select(SpidCert).order_by(SpidCert.id.desc()))
    cert = res.scalars().first()
    cert_dict = _row_to_dict(cert) if cert else {}

    return {
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "ente_settings": settings_dict,
        "oidc_clients": clients,
        "spid_idps": idps,
        "cie_config": cie_dict,
        "jwk_keys": keys,
        "spid_cert": cert_dict,
    }


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

async def _restore_bundle(bundle: dict, db: AsyncSession) -> None:
    """Ripristina tutte le tabelle dal bundle in una transazione."""

    version = bundle.get("version")
    if version != BACKUP_VERSION:
        raise ValueError(f"Versione bundle non supportata: {version!r}")

    # Ordine di delete: prima chi ha FK verso altre tabelle
    await db.execute(delete(CieConfig))
    await db.execute(delete(SpidCert))
    await db.execute(delete(OIDCClient))
    await db.execute(delete(SpidIdP))
    await db.execute(delete(JwkKey))
    await db.execute(delete(EnteSettings))
    await db.flush()

    # ente_settings
    if bundle.get("ente_settings"):
        db.add(EnteSettings(**_clean(bundle["ente_settings"], EnteSettings)))

    # jwk_keys (prima di cie_config per rispettare FK)
    for row in bundle.get("jwk_keys", []):
        db.add(JwkKey(**_clean(row, JwkKey)))

    # oidc_clients
    for row in bundle.get("oidc_clients", []):
        db.add(OIDCClient(**_clean(row, OIDCClient)))

    # spid_idps
    for row in bundle.get("spid_idps", []):
        db.add(SpidIdP(**_clean(row, SpidIdP)))

    # cie_config
    if bundle.get("cie_config"):
        db.add(CieConfig(**_clean(bundle["cie_config"], CieConfig)))

    # spid_cert
    if bundle.get("spid_cert"):
        db.add(SpidCert(**_clean(bundle["spid_cert"], SpidCert)))

    await db.commit()


def _clean(row: dict, model_class) -> dict:
    """Rimuove campi non presenti nel modello e converte tipi se necessario."""
    from sqlalchemy import DateTime
    cols = {c.name: c for c in model_class.__table__.columns}
    result = {}
    for k, v in row.items():
        if k not in cols:
            continue
        col = cols[k]
        # Converti stringhe ISO → datetime per colonne DateTime
        if isinstance(col.type, DateTime) and isinstance(v, str):
            try:
                v = datetime.fromisoformat(v)
            except (ValueError, TypeError):
                v = None
        result[k] = v
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/backup", response_class=HTMLResponse)
async def backup_page(request: Request):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    msg = request.session.pop("backup_msg", None)
    err = request.session.pop("backup_err", None)
    return templates.TemplateResponse(
        request, "backup/index.html.j2", {"msg": msg, "err": err}
    )


@router.get("/backup/export")
async def backup_export(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    try:
        bundle = await _export_bundle(db)
    except Exception as e:
        logger.error("Errore durante l'export backup: %s", e, exc_info=True)
        request.session["backup_err"] = f"Export fallito: {e}"
        return RedirectResponse("/admin/backup", status_code=302)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"pa-sso-proxy-backup-{ts}.json"
    content = json.dumps(bundle, ensure_ascii=False, indent=2)

    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/backup/import")
async def backup_import(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    try:
        raw = await file.read()
        bundle = json.loads(raw.decode("utf-8"))
    except Exception as e:
        request.session["backup_err"] = f"File non valido: {e}"
        return RedirectResponse("/admin/backup", status_code=302)

    try:
        await _restore_bundle(bundle, db)
    except Exception as e:
        logger.error("Errore durante il restore backup: %s", e, exc_info=True)
        request.session["backup_err"] = f"Ripristino fallito: {e}"
        return RedirectResponse("/admin/backup", status_code=302)

    # Rigenera config SATOSA e triggera reload
    try:
        async with db:
            await generate_and_write(db)
        await reload_satosa()
    except Exception as e:
        logger.warning("Rigenera config post-restore fallita: %s", e, exc_info=True)

    request.session["backup_msg"] = (
        "Ripristino completato. Configurazione SATOSA rigenerata."
    )
    return RedirectResponse("/admin/backup", status_code=302)
