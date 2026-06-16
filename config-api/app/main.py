import logging
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Form, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from app.jinja_templates import templates
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import AsyncSessionLocal, engine, get_db
from app.models import EnteSettings
from app.rate_limiter import is_ip_banned, record_failed_attempt, clear_attempts
from app.metadata_watcher import run_metadata_watcher, run_retention, fetch_spid_aggregate
from app.routes import dashboard, clients, idps, settings, certs, cie, test_client, backup, access_log, internal, placeholders
from app.satosa_generator import generate_and_write
from app.spid_seeder import seed_spid_idps
from app.trust_mark_fetcher import fetch_trust_mark

_CIE_OIDC_COLUMNS = [
    "entity_id",
    "client_id",
    "oidc_provider_url",
    "trust_anchor_url",
    "authority_hint_url",
    "homepage_uri",
    "policy_uri",
    "logo_uri",
    "trust_mark_id",
    "trust_mark",
    "oidc_contact_email",
    "oidc_environment",
]

_SPID_REGISTRY_COLUMNS = {
    "registry_entity_id": "TEXT",
    "registry_logo_uri": "TEXT",
    "registry_organization_name": "TEXT",
    "registry_lastupdate_date": "TEXT",
    "registry_disabled": "BOOLEAN",
    "registry_payload_json": "TEXT",
    "registry_synced_at": "TIMESTAMP WITH TIME ZONE",
}


async def _migrate_cie_oidc_columns() -> None:
    """Add CIE OIDC Federation columns to cie_config if not present (idempotent)."""
    async with engine.begin() as conn:
        has_table = await conn.run_sync(
            lambda c: inspect(c).has_table("cie_config")
        )
        if not has_table:
            return
        existing = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("cie_config")}
        )
        for col in _CIE_OIDC_COLUMNS:
            if col not in existing:
                await conn.execute(text(f"ALTER TABLE cie_config ADD COLUMN {col} TEXT"))


async def _migrate_client_secret_plain() -> None:
    async with engine.begin() as conn:
        has_table = await conn.run_sync(lambda c: inspect(c).has_table("oidc_clients"))
        if not has_table:
            return
        existing = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("oidc_clients")}
        )
        if "client_secret_plain" not in existing:
            await conn.execute(text("ALTER TABLE oidc_clients ADD COLUMN client_secret_plain VARCHAR(256)"))


async def _migrate_spid_registry_columns() -> None:
    """Add SPID registry cache columns to spid_idps if not present (idempotent)."""
    async with engine.begin() as conn:
        has_table = await conn.run_sync(lambda c: inspect(c).has_table("spid_idps"))
        if not has_table:
            return
        existing = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("spid_idps")}
        )
        for col, db_type in _SPID_REGISTRY_COLUMNS.items():
            if col not in existing:
                await conn.execute(text(f"ALTER TABLE spid_idps ADD COLUMN {col} {db_type}"))


from app.version import get_display_version

SESSION_SECRET = os.environ.get("SESSION_SECRET", "changeme")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")




async def _try_fetch_trust_mark(session) -> None:
    """Auto-fetch trust mark from CIE registry if CIE OIDC enabled and trust_mark absent."""
    from sqlalchemy import select
    from app.models import CieConfig
    from app.satosa_config_generator import _cie_oidc_client_id

    try:
        result = await session.execute(select(CieConfig).where(CieConfig.id == 1))
        config = result.scalar_one_or_none()
        if config is None or not config.oidc_federation_enabled:
            return
        if config.trust_mark:
            return  # già presente
        if not config.oidc_provider_url:
            return  # ambiente non ancora configurato

        # Ricava il client_id dal PROXY_HOSTNAME
        proxy_hostname = os.environ.get("PROXY_HOSTNAME", "")
        if not proxy_hostname:
            return
        client_id = _cie_oidc_client_id(proxy_hostname)

        result_tm = await fetch_trust_mark(client_id)
        if result_tm is None:
            return
        _tm_id, tm_jwt = result_tm
        config.trust_mark = tm_jwt
        # trust_mark_id non più in DB, si deriva dal JWT a runtime
        await session.commit()
        logger.info("Trust mark salvato automaticamente per %s", client_id)
    except Exception:
        logger.warning("Auto-fetch trust mark fallito a startup", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _migrate_cie_oidc_columns()
    await _migrate_spid_registry_columns()
    await _migrate_client_secret_plain()
    try:
        await fetch_spid_aggregate()
    except Exception:
        logger.warning("SPID aggregate download failed at startup", exc_info=True)
    async with AsyncSessionLocal() as session:
        await seed_spid_idps(session)
        await _try_fetch_trust_mark(session)
        try:
            await generate_and_write(session)
            from app.satosa_reload import reload_satosa
            reload_satosa()
        except Exception:
            logger.warning("Startup config generation failed (ok on first boot)", exc_info=True)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_metadata_watcher, CronTrigger(hour=2, minute=0))
    scheduler.add_job(run_retention, CronTrigger(day=1, hour=3, minute=0))
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

@app.middleware("http")
async def add_settings_to_state(request: Request, call_next):
    if request.url.path.startswith("/admin"):
        try:
            async with AsyncSessionLocal() as db:
                s = (await db.execute(
                    select(EnteSettings).where(EnteSettings.id == 1)
                )).scalar_one_or_none()
                request.state.s = s
        except Exception:
            request.state.s = None
    response = await call_next(request)
    return response

app.mount("/admin/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router, prefix="/admin")
app.include_router(clients.router, prefix="/admin")
app.include_router(idps.router, prefix="/admin")
app.include_router(settings.router, prefix="/admin")
app.include_router(certs.router, prefix="/admin")
app.include_router(cie.router, prefix="/admin")
app.include_router(test_client.router, prefix="/admin")
app.include_router(backup.router, prefix="/admin")
app.include_router(access_log.router, prefix="/admin")
app.include_router(placeholders.router, prefix="/admin")
app.include_router(internal.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _get_settings(db: AsyncSession) -> EnteSettings | None:
    return (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()


@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    ip_address = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    banned, remaining = await is_ip_banned(db, ip_address)
    error = None
    if banned:
        error = f"Troppi tentativi falliti. Riprova tra {remaining} minut{'o' if remaining == 1 else 'i'}."
    return templates.TemplateResponse(
        request,
        "login.html.j2",
        {"error": error, "banned": banned, "s": await _get_settings(db)},
    )


@app.post("/admin/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    ip_address = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    banned, remaining = await is_ip_banned(db, ip_address)
    if banned:
        error = f"Troppi tentativi falliti. Riprova tra {remaining} minut{'o' if remaining == 1 else 'i'}."
        return templates.TemplateResponse(
            request,
            "login.html.j2",
            {"error": error, "banned": banned, "s": await _get_settings(db)},
            status_code=429,
        )

    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        await clear_attempts(db, ip_address)
        request.session["user"] = username
        return RedirectResponse("/admin/", status_code=302)

    await record_failed_attempt(db, ip_address)
    banned, remaining = await is_ip_banned(db, ip_address)
    if banned:
        error = f"Troppi tentativi falliti. Riprova tra {remaining} minut{'o' if remaining == 1 else 'i'}."
    else:
        error = "Credenziali non valide"

    return templates.TemplateResponse(
        request,
        "login.html.j2",
        {"error": error, "banned": banned, "s": await _get_settings(db)},
        status_code=200 if not banned else 429,
    )


@app.post("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)
