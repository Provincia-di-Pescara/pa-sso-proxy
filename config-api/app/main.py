import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.database import AsyncSessionLocal
from app.metadata_watcher import run_metadata_watcher
from app.routes import dashboard, clients, idps, settings, certs
from app.spid_seeder import seed_spid_idps

SESSION_SECRET = os.environ.get("SESSION_SECRET", "changeme")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as session:
        await seed_spid_idps(session)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_metadata_watcher, CronTrigger(hour=2, minute=0))
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/admin/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router, prefix="/admin")
app.include_router(clients.router, prefix="/admin")
app.include_router(idps.router, prefix="/admin")
app.include_router(settings.router, prefix="/admin")
app.include_router(certs.router, prefix="/admin")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html.j2", {"error": None})


@app.post("/admin/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        request.session["user"] = username
        return RedirectResponse("/admin/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html.j2",
        {"error": "Credenziali non valide"},
        status_code=200,
    )


@app.post("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)
