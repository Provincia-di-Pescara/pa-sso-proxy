# pa-sso-proxy — Plan 3: SPID IdP Management + Cert + Metadata Watcher

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WebUI per gestire IdP SPID (toggle abilitazione, aggiorna metadata), metadata watcher automatico notturno, form impostazioni ente, generazione certificato SPID-compliant AgID.

**Architecture:** `spid_seeder.py` seed 11 IdP ufficiali al boot. `metadata_watcher.py` fa fetch HTTP dei metadata XML → SHA-256 → se cambiato aggiorna DB → reload SATOSA. APScheduler `AsyncIOScheduler` in lifespan, cron 02:00. `spid_cert.py` genera RSA 2048 + X.509 con SubjectDN AgID-compliant dalla `EnteSettings`, restituisce istanza non-committed. Tre nuovi router: `idps`, `settings`, `certs`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, httpx 0.27, APScheduler 3.10 (AsyncIOScheduler + CronTrigger), cryptography 43.0, Jinja2/Bootstrap 5. Tutti già in `requirements.txt`.

---

## File Map

```
config-api/
  app/
    spid_seeder.py              New: SPID_IDPS list + seed_spid_idps(db) — idempotent by alias
    metadata_watcher.py         New: fetch_idp_metadata(db, idp) + fetch_all_enabled(db) + run_metadata_watcher()
    spid_cert.py                New: generate_spid_cert(settings) -> SpidCert (sync, not committed)
    routes/
      idps.py                   New: GET /idps, POST /idps/{id}/toggle, POST /idps/{id}/refresh
      settings.py               New: GET /settings, POST /settings (upsert id=1)
      certs.py                  New: GET /certs, POST /certs/generate
    templates/
      idps/
        list.html.j2            New: table IdP con stato metadata e bottoni
      settings/
        form.html.j2            New: form impostazioni ente
      certs/
        status.html.j2          New: stato cert + bottone rigenera
  tests/
    test_spid_seeder.py         New: 3 tests
    test_metadata_watcher.py    New: 4 tests
    test_idps.py                New: 4 tests
    test_settings.py            New: 3 tests
    test_spid_cert.py           New: 3 tests (sync)
    test_certs.py               New: 3 tests
  main.py                       Modify: lifespan (seeder + scheduler), 3 nuovi router
```

---

## Task 1: spid_seeder.py + lifespan seeding

**Files:**
- Create: `config-api/app/spid_seeder.py`
- Create: `config-api/tests/test_spid_seeder.py`
- Modify: `config-api/app/main.py`

- [ ] **Step 1: Write failing tests**

Create `config-api/tests/test_spid_seeder.py`:

```python
import pytest
from sqlalchemy import select
from app.models import SpidIdP


async def test_seed_inserts_all_idps(db_session):
    from app.spid_seeder import seed_spid_idps, SPID_IDPS
    await seed_spid_idps(db_session)
    result = await db_session.execute(select(SpidIdP))
    rows = result.scalars().all()
    assert len(rows) == len(SPID_IDPS)
    aliases = {r.alias for r in rows}
    assert "spid-aruba" in aliases
    assert "spid-poste" in aliases


async def test_seed_is_idempotent(db_session):
    from app.spid_seeder import seed_spid_idps, SPID_IDPS
    await seed_spid_idps(db_session)
    await seed_spid_idps(db_session)
    result = await db_session.execute(select(SpidIdP))
    rows = result.scalars().all()
    assert len(rows) == len(SPID_IDPS)


async def test_seeded_idps_disabled_by_default(db_session):
    from app.spid_seeder import seed_spid_idps
    await seed_spid_idps(db_session)
    result = await db_session.execute(select(SpidIdP).where(SpidIdP.enabled == True))
    enabled = result.scalars().all()
    assert len(enabled) == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_spid_seeder.py -v 2>&1 | head -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.spid_seeder'`

- [ ] **Step 3: Create `config-api/app/spid_seeder.py`**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SpidIdP

SPID_IDPS = [
    {"alias": "spid-aruba",      "display_name": "Aruba PEC",         "metadata_url": "https://loginspid.aruba.it/metadata"},
    {"alias": "spid-infocert",   "display_name": "InfoCert ID",        "metadata_url": "https://identity.infocert.it/metadata/metadata.xml"},
    {"alias": "spid-intesa",     "display_name": "Intesa Sanpaolo",    "metadata_url": "https://spid.intesaid.com/saml2/idp/metadata"},
    {"alias": "spid-lepida",     "display_name": "Lepida ID",          "metadata_url": "https://id.lepida.it/idp/shibboleth"},
    {"alias": "spid-namirial",   "display_name": "Namirial ID",        "metadata_url": "https://idp.namirialtsp.com/idp/metadata"},
    {"alias": "spid-poste",      "display_name": "Poste ID",           "metadata_url": "https://posteid.poste.it/jod-fs/metadata/idp"},
    {"alias": "spid-register",   "display_name": "Register.it",        "metadata_url": "https://spid.register.it/login/metadata"},
    {"alias": "spid-sielte",     "display_name": "Sielte",             "metadata_url": "https://identity.sielte.it/idp/shibboleth"},
    {"alias": "spid-tim",        "display_name": "TIM Personal ID",    "metadata_url": "https://login.id.tim.it/affwebservices/public/saml2sso"},
    {"alias": "spid-teamsystem", "display_name": "TeamSystem ID",      "metadata_url": "https://spid.teamsystem.com/idp/saml2/metadata"},
    {"alias": "spid-trust",      "display_name": "Trust Technologies", "metadata_url": "https://idp.trusttechnologies.it/saml2/idp/metadata"},
]


async def seed_spid_idps(db: AsyncSession) -> None:
    """Insert SPID IdPs not yet in DB. Idempotent by alias."""
    result = await db.execute(select(SpidIdP.alias))
    existing = {row[0] for row in result.all()}
    for data in SPID_IDPS:
        if data["alias"] not in existing:
            db.add(SpidIdP(
                alias=data["alias"],
                display_name=data["display_name"],
                metadata_url=data["metadata_url"],
                enabled=False,
            ))
    await db.commit()
```

- [ ] **Step 4: Run tests — must pass**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_spid_seeder.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 5: Update `config-api/app/main.py` — add seeder to lifespan**

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.database import AsyncSessionLocal
from app.routes import dashboard, clients
from app.spid_seeder import seed_spid_idps

SESSION_SECRET = os.environ.get("SESSION_SECRET", "changeme")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as session:
        await seed_spid_idps(session)
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/admin/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router, prefix="/admin")
app.include_router(clients.router, prefix="/admin")


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
```

- [ ] **Step 6: Run full suite**

```bash
cd config-api
PYTHONPATH=. pytest -v --tb=short
```

Expected: 25 preesistenti + 3 nuovi = 28 PASS.

- [ ] **Step 7: Commit**

```bash
git add config-api/app/spid_seeder.py config-api/tests/test_spid_seeder.py config-api/app/main.py
git commit -m "feat: SPID IdP seeder — 11 IdP ufficiali AgID seedati al boot"
```

---

## Task 2: metadata_watcher.py + tests

**Files:**
- Create: `config-api/app/metadata_watcher.py`
- Create: `config-api/tests/test_metadata_watcher.py`

- [ ] **Step 1: Write failing tests**

Create `config-api/tests/test_metadata_watcher.py`:

```python
import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import SpidIdP


async def test_fetch_updates_when_content_changes(db_session):
    idp = SpidIdP(
        alias="spid-test",
        display_name="Test IdP",
        metadata_url="https://test.example/metadata",
        enabled=True,
        metadata_hash="old-hash",
        metadata_cache="<old/>",
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    new_xml = "<EntityDescriptor>new content</EntityDescriptor>"
    mock_resp = MagicMock()
    mock_resp.text = new_xml
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=mock_client):
        from app.metadata_watcher import fetch_idp_metadata
        result = await fetch_idp_metadata(db_session, idp)

    assert result is True
    await db_session.refresh(idp)
    assert idp.metadata_cache == new_xml
    assert idp.metadata_hash == hashlib.sha256(new_xml.encode()).hexdigest()
    assert idp.last_updated is not None


async def test_fetch_skips_when_unchanged(db_session):
    xml = "<EntityDescriptor>stable</EntityDescriptor>"
    current_hash = hashlib.sha256(xml.encode()).hexdigest()

    idp = SpidIdP(
        alias="spid-stable",
        display_name="Stable IdP",
        metadata_url="https://stable.example/metadata",
        enabled=True,
        metadata_cache=xml,
        metadata_hash=current_hash,
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    mock_resp = MagicMock()
    mock_resp.text = xml
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=mock_client):
        from app.metadata_watcher import fetch_idp_metadata
        result = await fetch_idp_metadata(db_session, idp)

    assert result is False


async def test_fetch_handles_http_error(db_session):
    idp = SpidIdP(
        alias="spid-broken",
        display_name="Broken IdP",
        metadata_url="https://broken.example/metadata",
        enabled=True,
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.metadata_watcher.httpx.AsyncClient", return_value=mock_client):
        from app.metadata_watcher import fetch_idp_metadata
        # should raise — caller (fetch_all_enabled) handles the exception
        with pytest.raises(Exception):
            await fetch_idp_metadata(db_session, idp)


async def test_fetch_all_enabled_counts_updates(db_session):
    idp1 = SpidIdP(alias="spid-a", display_name="A", metadata_url="https://a.example/metadata", enabled=True, metadata_hash="hash-a")
    idp2 = SpidIdP(alias="spid-b", display_name="B", metadata_url="https://b.example/metadata", enabled=True, metadata_hash="hash-b")
    idp3 = SpidIdP(alias="spid-c", display_name="C", metadata_url="https://c.example/metadata", enabled=False)
    db_session.add_all([idp1, idp2, idp3])
    await db_session.commit()

    # fetch_idp_metadata returns True for idp1, False for idp2; idp3 disabled so skipped
    async def mock_fetch(db, idp):
        return idp.alias == "spid-a"

    with patch("app.metadata_watcher.fetch_idp_metadata", side_effect=mock_fetch), \
         patch("app.metadata_watcher.generate_and_write", new_callable=AsyncMock), \
         patch("app.metadata_watcher.reload_satosa", return_value=True):
        from app.metadata_watcher import fetch_all_enabled
        count = await fetch_all_enabled(db_session)

    assert count == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_metadata_watcher.py -v 2>&1 | head -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.metadata_watcher'`

- [ ] **Step 3: Create `config-api/app/metadata_watcher.py`**

```python
import asyncio
import hashlib
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

logger = logging.getLogger(__name__)


async def fetch_idp_metadata(db: AsyncSession, idp: SpidIdP) -> bool:
    """Fetch metadata XML for one IdP. Returns True if content changed and DB was updated."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(idp.metadata_url)
        resp.raise_for_status()
    content = resp.text
    new_hash = hashlib.sha256(content.encode()).hexdigest()
    if new_hash == idp.metadata_hash:
        return False
    idp.metadata_cache = content
    idp.metadata_hash = new_hash
    idp.last_updated = datetime.now(timezone.utc)
    await db.commit()
    return True


async def fetch_all_enabled(db: AsyncSession) -> int:
    """Fetch metadata for all enabled IdPs. Calls generate+reload if any updated. Returns update count."""
    result = await db.execute(select(SpidIdP).where(SpidIdP.enabled == True))
    idps = result.scalars().all()
    updated = 0
    for idp in idps:
        try:
            if await fetch_idp_metadata(db, idp):
                updated += 1
        except Exception as exc:
            logger.warning("Metadata fetch failed for %s: %s", idp.alias, exc)
    if updated > 0:
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    return updated


async def run_metadata_watcher() -> None:
    """Scheduler entry point. Creates its own DB session."""
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        count = await fetch_all_enabled(session)
        logger.info("Metadata watcher: %d IdP aggiornati", count)
```

- [ ] **Step 4: Run tests — must pass**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_metadata_watcher.py -v
```

Expected: 4/4 PASS.

- [ ] **Step 5: Run full suite**

```bash
cd config-api
PYTHONPATH=. pytest -v --tb=short
```

Expected: 28 + 4 = 32 PASS.

- [ ] **Step 6: Commit**

```bash
git add config-api/app/metadata_watcher.py config-api/tests/test_metadata_watcher.py
git commit -m "feat: metadata_watcher — fetch + SHA-256 + reload per IdP SPID"
```

---

## Task 3: IdP routes + template + scheduler in lifespan

**Files:**
- Create: `config-api/app/templates/idps/list.html.j2`
- Create: `config-api/app/routes/idps.py`
- Modify: `config-api/app/main.py`
- Create: `config-api/tests/test_idps.py`

- [ ] **Step 1: Create `config-api/app/templates/idps/list.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}Provider SPID — PA SSO Proxy{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h2>Provider SPID</h2>
</div>
<table class="table table-sm table-hover">
  <thead>
    <tr>
      <th>Nome</th><th>Alias</th><th>URL Metadata</th><th>Stato</th><th>Ultimo aggiornamento</th><th>Azioni</th>
    </tr>
  </thead>
  <tbody>
    {% for idp in idps %}
    <tr>
      <td>{{ idp.display_name }}</td>
      <td><code>{{ idp.alias }}</code></td>
      <td><small><a href="{{ idp.metadata_url }}" target="_blank" rel="noopener">{{ idp.metadata_url[:60] }}{% if idp.metadata_url|length > 60 %}…{% endif %}</a></small></td>
      <td>
        {% if idp.enabled %}<span class="badge bg-success">Abilitato</span>
        {% else %}<span class="badge bg-secondary">Disabilitato</span>{% endif %}
        {% if idp.metadata_cache %}<span class="badge bg-info text-dark ms-1">Metadata OK</span>
        {% else %}<span class="badge bg-warning text-dark ms-1">Nessun metadata</span>{% endif %}
      </td>
      <td><small>{% if idp.last_updated %}{{ idp.last_updated.strftime('%Y-%m-%d %H:%M') }}{% else %}—{% endif %}</small></td>
      <td>
        <form method="post" action="/admin/idps/{{ idp.id }}/toggle" class="d-inline">
          <button class="btn btn-sm btn-outline-warning">{% if idp.enabled %}Disabilita{% else %}Abilita{% endif %}</button>
        </form>
        <form method="post" action="/admin/idps/{{ idp.id }}/refresh" class="d-inline">
          <button class="btn btn-sm btn-outline-info">Aggiorna metadata</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 2: Write failing tests**

Create `config-api/tests/test_idps.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.database import get_db
from app.models import SpidIdP


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-plan3")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")


@pytest_asyncio.fixture
async def auth_client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/login", data={"username": "admin", "password": "secret"})
        yield client

    app.dependency_overrides.clear()


async def test_idps_list_shows_idps(auth_client, db_session):
    idp = SpidIdP(
        alias="spid-test",
        display_name="Test IdP",
        metadata_url="https://test.example/metadata",
        enabled=False,
    )
    db_session.add(idp)
    await db_session.commit()

    response = await auth_client.get("/admin/idps")
    assert response.status_code == 200
    assert "Test IdP" in response.text
    assert "spid-test" in response.text


async def test_idps_list_unauthenticated():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/idps", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


async def test_idp_toggle_enables(auth_client, db_session):
    idp = SpidIdP(
        alias="spid-toggle",
        display_name="Toggle IdP",
        metadata_url="https://toggle.example/metadata",
        enabled=False,
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    with patch("app.routes.idps.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.idps.reload_satosa", return_value=True):
        response = await auth_client.post(f"/admin/idps/{idp.id}/toggle", follow_redirects=False)

    assert response.status_code == 302
    await db_session.refresh(idp)
    assert idp.enabled is True


async def test_idp_force_refresh_calls_fetch(auth_client, db_session):
    idp = SpidIdP(
        alias="spid-refresh",
        display_name="Refresh IdP",
        metadata_url="https://refresh.example/metadata",
        enabled=True,
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)

    with patch("app.routes.idps.fetch_idp_metadata", new_callable=AsyncMock, return_value=True), \
         patch("app.routes.idps.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.idps.reload_satosa", return_value=True):
        response = await auth_client.post(f"/admin/idps/{idp.id}/refresh", follow_redirects=False)

    assert response.status_code == 302
```

- [ ] **Step 3: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_idps.py -v 2>&1 | head -20
```

Expected: FAIL — routes not registered.

- [ ] **Step 4: Create `config-api/app/routes/idps.py`**

```python
import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metadata_watcher import fetch_idp_metadata
from app.models import SpidIdP
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/idps", response_class=HTMLResponse)
async def idps_list(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidIdP).order_by(SpidIdP.display_name))
    idps = result.scalars().all()
    return templates.TemplateResponse(request, "idps/list.html.j2", {"idps": idps})


@router.post("/idps/{idp_id}/toggle")
async def idps_toggle(request: Request, idp_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidIdP).where(SpidIdP.id == idp_id))
    idp = result.scalar_one_or_none()
    if idp:
        idp.enabled = not idp.enabled
        await db.commit()
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    return RedirectResponse("/admin/idps", status_code=302)


@router.post("/idps/{idp_id}/refresh")
async def idps_refresh(request: Request, idp_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidIdP).where(SpidIdP.id == idp_id))
    idp = result.scalar_one_or_none()
    if idp:
        try:
            updated = await fetch_idp_metadata(db, idp)
            if updated:
                await generate_and_write(db)
                await asyncio.to_thread(reload_satosa)
        except Exception:
            pass
    return RedirectResponse("/admin/idps", status_code=302)
```

- [ ] **Step 5: Update `config-api/app/main.py` — add scheduler + idps router**

```python
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
from app.routes import dashboard, clients, idps
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
```

- [ ] **Step 6: Run tests — must pass**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_idps.py -v
```

Expected: 4/4 PASS.

- [ ] **Step 7: Run full suite**

```bash
cd config-api
PYTHONPATH=. pytest -v --tb=short
```

Expected: 32 + 4 = 36 PASS.

- [ ] **Step 8: Commit**

```bash
git add config-api/app/routes/idps.py config-api/app/templates/idps/ \
        config-api/app/main.py config-api/tests/test_idps.py
git commit -m "feat: IdP SPID list/toggle/refresh + scheduler metadata watcher 02:00"
```

---

## Task 4: Ente settings routes + template

**Files:**
- Create: `config-api/app/templates/settings/form.html.j2`
- Create: `config-api/app/routes/settings.py`
- Modify: `config-api/app/main.py`
- Create: `config-api/tests/test_settings.py`

- [ ] **Step 1: Create `config-api/app/templates/settings/form.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}Impostazioni Ente — PA SSO Proxy{% endblock %}
{% block content %}
<h2>Impostazioni Ente</h2>
{% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
{% if saved %}<div class="alert alert-success">Impostazioni salvate.</div>{% endif %}
<form method="post" class="mt-3" style="max-width:640px">
  <div class="mb-3">
    <label class="form-label">Nome visualizzato (org_display_name)</label>
    <input type="text" name="org_display_name" class="form-control" value="{{ s.org_display_name if s else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">Nome ente (org_name) <small class="text-muted">es. Provincia di Pescara</small></label>
    <input type="text" name="org_name" class="form-control" required value="{{ s.org_name if s else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">URL ente (org_url)</label>
    <input type="url" name="org_url" class="form-control" value="{{ s.org_url if s else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">Hostname proxy (proxy_hostname) <small class="text-muted">es. sso.ente.it</small></label>
    <input type="text" name="proxy_hostname" class="form-control" required value="{{ s.proxy_hostname if s else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">Codice IPA (ipa_code)</label>
    <input type="text" name="ipa_code" class="form-control" required value="{{ s.ipa_code if s else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">Email contatto (contact_email)</label>
    <input type="email" name="contact_email" class="form-control" value="{{ s.contact_email if s else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">Telefono contatto (contact_phone)</label>
    <input type="text" name="contact_phone" class="form-control" value="{{ s.contact_phone if s else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">Città (org_city) <small class="text-muted">per SubjectDN cert SPID</small></label>
    <input type="text" name="org_city" class="form-control" required value="{{ s.org_city if s else '' }}">
  </div>
  <button type="submit" class="btn btn-primary">Salva</button>
</form>
{% endblock %}
```

- [ ] **Step 2: Write failing tests**

Create `config-api/tests/test_settings.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.models import EnteSettings


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-plan3")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")


@pytest_asyncio.fixture
async def auth_client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/login", data={"username": "admin", "password": "secret"})
        yield client

    app.dependency_overrides.clear()


async def test_settings_form_shows_empty(auth_client):
    response = await auth_client.get("/admin/settings")
    assert response.status_code == 200
    assert "Impostazioni Ente" in response.text


async def test_settings_save_creates_row(auth_client, db_session):
    response = await auth_client.post(
        "/admin/settings",
        data={
            "org_display_name": "Ente Test",
            "org_name": "Ente Test",
            "org_url": "https://test.it",
            "proxy_hostname": "sso.test.it",
            "ipa_code": "TEST",
            "contact_email": "test@test.it",
            "contact_phone": "+39000",
            "org_city": "Pescara",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    result = await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()
    assert s is not None
    assert s.org_name == "Ente Test"
    assert s.proxy_hostname == "sso.test.it"


async def test_settings_save_updates_existing(auth_client, db_session):
    existing = EnteSettings(
        id=1, org_display_name="Old", org_name="Old Ente",
        org_url="https://old.it", proxy_hostname="old.it",
        ipa_code="OLD", contact_email="old@old.it", contact_phone="+39",
        org_city="Roma",
    )
    db_session.add(existing)
    await db_session.commit()

    await auth_client.post(
        "/admin/settings",
        data={
            "org_display_name": "New",
            "org_name": "New Ente",
            "org_url": "https://new.it",
            "proxy_hostname": "new.it",
            "ipa_code": "NEW",
            "contact_email": "new@new.it",
            "contact_phone": "+39111",
            "org_city": "Milano",
        },
        follow_redirects=False,
    )

    await db_session.refresh(existing)
    assert existing.org_name == "New Ente"
    assert existing.org_city == "Milano"
```

- [ ] **Step 3: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_settings.py -v 2>&1 | head -20
```

Expected: FAIL — routes not registered.

- [ ] **Step 4: Create `config-api/app/routes/settings.py`**

```python
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/settings", response_class=HTMLResponse)
async def settings_form(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()
    return templates.TemplateResponse(request, "settings/form.html.j2", {"s": s, "error": None, "saved": False})


@router.post("/settings")
async def settings_save(
    request: Request,
    org_display_name: str = Form(default=""),
    org_name: str = Form(...),
    org_url: str = Form(default=""),
    proxy_hostname: str = Form(...),
    ipa_code: str = Form(...),
    contact_email: str = Form(default=""),
    contact_phone: str = Form(default=""),
    org_city: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()
    if s is None:
        s = EnteSettings(id=1)
        db.add(s)
    s.org_display_name = org_display_name
    s.org_name = org_name
    s.org_url = org_url
    s.proxy_hostname = proxy_hostname
    s.ipa_code = ipa_code
    s.contact_email = contact_email
    s.contact_phone = contact_phone
    s.org_city = org_city
    await db.commit()
    return RedirectResponse("/admin/settings", status_code=302)
```

- [ ] **Step 5: Update `config-api/app/main.py` — register settings router**

```python
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
from app.routes import dashboard, clients, idps, settings
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
```

- [ ] **Step 6: Run tests — must pass**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_settings.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 7: Run full suite**

```bash
cd config-api
PYTHONPATH=. pytest -v --tb=short
```

Expected: 36 + 3 = 39 PASS.

- [ ] **Step 8: Commit**

```bash
git add config-api/app/routes/settings.py config-api/app/templates/settings/ \
        config-api/app/main.py config-api/tests/test_settings.py
git commit -m "feat: impostazioni ente — GET/POST /admin/settings con upsert id=1"
```

---

## Task 5: spid_cert.py + certs routes + template

**Files:**
- Create: `config-api/app/spid_cert.py`
- Create: `config-api/app/templates/certs/status.html.j2`
- Create: `config-api/app/routes/certs.py`
- Modify: `config-api/app/main.py`
- Create: `config-api/tests/test_spid_cert.py`
- Create: `config-api/tests/test_certs.py`

- [ ] **Step 1: Create `config-api/app/templates/certs/status.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}Certificato SPID — PA SSO Proxy{% endblock %}
{% block content %}
<h2>Certificato SPID</h2>
{% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
{% if cert %}
  {% set days_left = (cert.not_valid_after - now).days %}
  {% if days_left < 90 %}
  <div class="alert alert-warning">
    Il certificato scade tra <strong>{{ days_left }} giorni</strong> ({{ cert.not_valid_after.strftime('%Y-%m-%d') }}). Rigenera il certificato.
  </div>
  {% else %}
  <div class="alert alert-success">
    Certificato valido fino al <strong>{{ cert.not_valid_after.strftime('%Y-%m-%d') }}</strong> ({{ days_left }} giorni rimanenti).
  </div>
  {% endif %}
  <dl class="row mt-3">
    <dt class="col-sm-3">Subject DN</dt>
    <dd class="col-sm-9"><code>{{ cert.subject_dn }}</code></dd>
    <dt class="col-sm-3">Generato il</dt>
    <dd class="col-sm-9">{{ cert.created_at.strftime('%Y-%m-%d %H:%M') }}</dd>
  </dl>
{% else %}
<div class="alert alert-warning">Nessun certificato SPID configurato. Configura le impostazioni ente e genera il certificato.</div>
{% endif %}
<form method="post" action="/admin/certs/generate" class="mt-3">
  <button type="submit" class="btn btn-primary">
    {% if cert %}Rigenera certificato{% else %}Genera certificato{% endif %}
  </button>
</form>
{% endblock %}
```

- [ ] **Step 2: Write failing tests for spid_cert.py**

Create `config-api/tests/test_spid_cert.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta
from cryptography import x509
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import NameOID

from app.models import EnteSettings, SpidCert


def make_settings(**overrides):
    defaults = dict(
        proxy_hostname="login.test.it",
        org_name="Ente Test",
        org_display_name="Ente Test",
        org_url="https://test.it",
        ipa_code="TEST",
        contact_email="test@test.it",
        contact_phone="+39",
        org_city="Pescara",
    )
    defaults.update(overrides)
    return EnteSettings(**defaults)


def test_generate_cert_returns_spid_cert_instance():
    from app.spid_cert import generate_spid_cert
    settings = make_settings()
    cert = generate_spid_cert(settings)
    assert isinstance(cert, SpidCert)
    assert cert.certificate_pem.startswith("-----BEGIN CERTIFICATE-----")
    assert cert.private_key_pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert "login.test.it" in cert.subject_dn


def test_generate_cert_expires_in_10_years():
    from app.spid_cert import generate_spid_cert
    settings = make_settings()
    cert = generate_spid_cert(settings)
    now = datetime.now(timezone.utc)
    delta = cert.not_valid_after - now
    assert 3640 < delta.days < 3660


def test_generate_cert_missing_fields_raises():
    from app.spid_cert import generate_spid_cert
    settings = make_settings(proxy_hostname="")
    with pytest.raises(ValueError, match="proxy_hostname"):
        generate_spid_cert(settings)
```

- [ ] **Step 3: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_spid_cert.py -v 2>&1 | head -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.spid_cert'`

- [ ] **Step 4: Create `config-api/app/spid_cert.py`**

```python
from datetime import datetime, timezone, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509 import NameAttribute, ObjectIdentifier
from cryptography.x509.extensions import BasicConstraints, KeyUsage

from app.models import EnteSettings, SpidCert

OID_ENTITY_ID = ObjectIdentifier("2.5.4.83")
OID_ORG_IDENTIFIER = ObjectIdentifier("2.5.4.97")
OID_AGID_ROOT = ObjectIdentifier("1.3.76.16")
OID_AGID_CERT = ObjectIdentifier("1.3.76.16.6")
OID_CERT_SP_PUB = ObjectIdentifier("1.3.76.16.4.2.1")


def generate_spid_cert(settings: EnteSettings) -> SpidCert:
    """Generate RSA 2048 + X.509 with AgID-compliant SubjectDN. Returns SpidCert (not committed)."""
    missing = [f for f in ("proxy_hostname", "org_name", "ipa_code", "org_city") if not getattr(settings, f, "")]
    if missing:
        raise ValueError(f"Impostazioni ente incomplete: {', '.join(missing)} obbligatori per generare il certificato")

    privkey = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = x509.Name([
        NameAttribute(x509.oid.NameOID.COMMON_NAME, settings.proxy_hostname),
        NameAttribute(x509.oid.NameOID.ORGANIZATION_NAME, settings.org_name),
        NameAttribute(OID_ENTITY_ID, f"https://{settings.proxy_hostname}"),
        NameAttribute(OID_ORG_IDENTIFIER, f"PA:IT-{settings.ipa_code}"),
        NameAttribute(x509.oid.NameOID.COUNTRY_NAME, "IT"),
        NameAttribute(x509.oid.NameOID.LOCALITY_NAME, settings.org_city),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(privkey.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(seconds=60))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(BasicConstraints(ca=False, path_length=None), critical=False)
        .add_extension(
            KeyUsage(
                digital_signature=True, content_commitment=True,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.CertificatePolicies([
                x509.PolicyInformation(OID_AGID_ROOT, None),
                x509.PolicyInformation(OID_AGID_CERT, None),
                x509.PolicyInformation(OID_CERT_SP_PUB, None),
            ]),
            critical=False,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(privkey.public_key()), critical=False)
        .sign(privkey, hashes.SHA256())
    )

    return SpidCert(
        certificate_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
        private_key_pem=privkey.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
        not_valid_after=cert.not_valid_after_utc,
        subject_dn=cert.subject.rfc4514_string(),
    )
```

- [ ] **Step 5: Run spid_cert tests — must pass**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_spid_cert.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 6: Write failing tests for certs routes**

Create `config-api/tests/test_certs.py`:

```python
import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch

from app.database import get_db
from app.models import EnteSettings, SpidCert


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-plan3")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")


@pytest_asyncio.fixture
async def auth_client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/admin/login", data={"username": "admin", "password": "secret"})
        yield client

    app.dependency_overrides.clear()


async def test_certs_status_no_cert(auth_client):
    response = await auth_client.get("/admin/certs")
    assert response.status_code == 200
    assert "Nessun certificato" in response.text


async def test_certs_generate_without_settings_returns_400(auth_client):
    response = await auth_client.post("/admin/certs/generate", follow_redirects=False)
    assert response.status_code == 400


async def test_certs_generate_with_settings_creates_cert(auth_client, db_session):
    s = EnteSettings(
        id=1,
        org_display_name="Test", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="t@t.it", contact_phone="+39",
        org_city="Pescara",
    )
    db_session.add(s)
    await db_session.commit()

    mock_cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=sso.test.it",
    )
    with patch("app.routes.certs.generate_spid_cert", return_value=mock_cert):
        response = await auth_client.post("/admin/certs/generate", follow_redirects=False)

    assert response.status_code == 302
    assert "/admin/certs" in response.headers["location"]
```

- [ ] **Step 7: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_certs.py -v 2>&1 | head -20
```

Expected: FAIL — routes not registered.

- [ ] **Step 8: Create `config-api/app/routes/certs.py`**

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, SpidCert
from app.spid_cert import generate_spid_cert

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/certs", response_class=HTMLResponse)
async def certs_status(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).order_by(SpidCert.created_at.desc()).limit(1))
    cert = result.scalar_one_or_none()
    return templates.TemplateResponse(
        request, "certs/status.html.j2",
        {"cert": cert, "error": None, "now": datetime.now(timezone.utc)},
    )


@router.post("/certs/generate")
async def certs_generate(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()
    missing = not s or not all([s.proxy_hostname, s.org_name, s.ipa_code, s.org_city])
    if missing:
        return templates.TemplateResponse(
            request, "certs/status.html.j2",
            {
                "cert": None,
                "error": "Configura prima le impostazioni ente (proxy_hostname, org_name, ipa_code, org_city).",
                "now": datetime.now(timezone.utc),
            },
            status_code=400,
        )
    try:
        cert_obj = generate_spid_cert(s)
    except ValueError as exc:
        return templates.TemplateResponse(
            request, "certs/status.html.j2",
            {"cert": None, "error": str(exc), "now": datetime.now(timezone.utc)},
            status_code=400,
        )
    db.add(cert_obj)
    await db.commit()
    return RedirectResponse("/admin/certs", status_code=302)
```

- [ ] **Step 9: Update `config-api/app/main.py` — register certs router**

```python
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
```

- [ ] **Step 10: Run all new tests**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_spid_cert.py tests/test_certs.py -v
```

Expected: 6/6 PASS.

- [ ] **Step 11: Run full suite**

```bash
cd config-api
PYTHONPATH=. pytest -v --tb=short
```

Expected: 39 + 6 = 45 PASS.

- [ ] **Step 12: Commit**

```bash
git add config-api/app/spid_cert.py config-api/app/routes/certs.py \
        config-api/app/templates/certs/ config-api/app/main.py \
        config-api/tests/test_spid_cert.py config-api/tests/test_certs.py
git commit -m "feat: certificato SPID — generazione RSA 2048 X.509 AgID-compliant + WebUI"
```

---

## Self-Review

**Spec coverage:**
- ✅ Provider SPID — lista IdP, toggle enabled, stato metadata, aggiorna metadata
- ✅ Certificati — stato cert SPID, rigenera
- ✅ Impostazioni Ente — form con tutti i campi richiesti dal DB
- ✅ Metadata watcher — APScheduler cron 02:00, fetch + SHA-256 + reload
- ✅ Seeder — 11 IdP ufficiali AgID seedati idempotentemente al boot
- ⏭ Config generator SPID section (scrive metadata XML + SPID backend config in volume) → Plan 5
- ⏭ CIE OIDC JWK management → Plan 4

**Placeholder scan:** nessun TBD o TODO.

**Type consistency:**
- `seed_spid_idps(db: AsyncSession) -> None` — definita Task 1, usata in main.py ✅
- `fetch_idp_metadata(db: AsyncSession, idp: SpidIdP) -> bool` — definita Task 2, usata in idps.py Task 3 ✅
- `fetch_all_enabled(db: AsyncSession) -> int` — definita Task 2, usata in test_metadata_watcher.py ✅
- `run_metadata_watcher() -> None` — definita Task 2, usata in main.py Task 3 ✅
- `generate_spid_cert(settings: EnteSettings) -> SpidCert` — definita Task 5, usata in certs.py Task 5 ✅
- `SpidCert.not_valid_after` è `datetime` (timezone-aware) — `cert.not_valid_after_utc` in Python cryptography 43.x ✅
- Template `certs/status.html.j2` usa `now` passato dalla route → corretto ✅

**Nota per Plan 4:** CIE OIDC JWK generation.
**Nota per Plan 5:** `generate_and_write` esteso per scrivere sezione SPID (metadata XML + backend config SATOSA).
