# pa-sso-proxy — Plan 2: OIDC Client CRUD + Config Generator + SATOSA Reload

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WebUI to create/edit/delete/toggle OIDC clients, a config generator that writes the oidcop clients YAML to a shared volume, and a SATOSA reload trigger wired to every client mutation.

**Architecture:** New `satosa_generator.py` reads `oidc_clients WHERE enabled=true` from DB and writes `oidcop_clients.yaml` to a named Docker volume (`proxy_satosa_conf`) shared between config-api and satosa. `satosa_reload.py` calls `docker.from_env().containers.get(...).restart()`. Every client mutation route triggers generate + reload. Client secret is shown exactly once via session flash, then bcrypt hash stored only in DB.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, PyYAML, bcrypt, docker SDK, Jinja2/Bootstrap 5. Tests mock `generate_and_write` and `reload_satosa` at the route layer. Generator tests use tmp_path + SQLite db_session.

---

## File Map

```
docker-compose.yaml                          Modify: add proxy_satosa_conf volume + env vars
config-api/
  app/
    satosa_generator.py                      New: reads DB → YAML → writes to SATOSA_CONF_DIR
    satosa_reload.py                         New: docker SDK restart of satosa container
    routes/
      clients.py                             New: CRUD routes /admin/clients/*
    templates/
      clients/
        list.html.j2                         New: client list table
        form.html.j2                         New: create/edit form (shared)
        reveal.html.j2                       New: one-time secret display
  tests/
    test_satosa_generator.py                 New: unit tests for YAML generation
    test_satosa_reload.py                    New: unit tests for reload (mocked docker)
    test_clients.py                          New: CRUD route tests
  main.py                                    Modify: register clients router
```

---

## Task 1: docker-compose — shared satosa volume + env vars

**Files:**
- Modify: `docker-compose.yaml`

- [ ] **Step 1: Add volume mount and env vars to `config-api` service**

In `docker-compose.yaml`, in the `config-api` service, update `volumes` and `environment`:

```yaml
  config-api:
    build: ./config-api
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgresql+asyncpg://proxy:${POSTGRES_PASSWORD}@postgres:5432/proxy
      - ADMIN_USER=${ADMIN_USER}
      - ADMIN_PASSWORD=${ADMIN_PASSWORD}
      - SESSION_SECRET=${SESSION_SECRET:-changeme-generate-random-32chars}
      - PROXY_HOSTNAME=${PROXY_HOSTNAME}
      - SATOSA_CONF_DIR=/satosa-conf
      - SATOSA_CONTAINER_NAME=pa-sso-proxy-satosa-1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - proxy_satosa_conf:/satosa-conf
    networks:
      - proxy-internal
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 15s
      timeout: 5s
      retries: 5
```

- [ ] **Step 2: Add volume mount to `satosa` service**

In the `satosa` service, add:

```yaml
  satosa:
    image: python:3.12-slim
    restart: unless-stopped
    networks:
      - proxy-internal
    volumes:
      - proxy_satosa_conf:/satosa-conf
    command: >
      sh -c "python3 -c 'import time; print(\"satosa placeholder\"); time.sleep(86400)'"
```

- [ ] **Step 3: Add volume declaration**

In the `volumes:` section at the bottom, add `proxy_satosa_conf`:

```yaml
volumes:
  proxy_db_data:
  proxy_satosa_conf:
```

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yaml
git commit -m "feat: proxy_satosa_conf shared volume + satosa env vars"
```

---

## Task 2: satosa_generator.py + tests

**Files:**
- Create: `config-api/app/satosa_generator.py`
- Create: `config-api/tests/test_satosa_generator.py`

- [ ] **Step 1: Write failing tests**

Create `config-api/tests/test_satosa_generator.py`:

```python
import pytest
import yaml
from app.models import OIDCClient


async def test_generate_writes_yaml(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    c = OIDCClient(
        client_id="myapp",
        client_secret_hash="$2b$12$fakehash",
        name="My App",
        redirect_uris=["https://myapp.test/cb"],
        allowed_scopes=["openid", "profile"],
        enabled=True,
    )
    db_session.add(c)
    await db_session.commit()

    from app.satosa_generator import generate_and_write
    await generate_and_write(db_session)

    out = tmp_path / "oidcop_clients.yaml"
    assert out.exists()
    data = yaml.safe_load(out.read_text())
    assert "myapp" in data["OIDCOP"]["clients"]
    assert data["OIDCOP"]["clients"]["myapp"]["redirect_uris"] == ["https://myapp.test/cb"]
    assert data["OIDCOP"]["clients"]["myapp"]["client_secret"] == "$2b$12$fakehash"


async def test_generate_excludes_disabled_clients(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    c = OIDCClient(
        client_id="disabled-app",
        client_secret_hash="hash",
        name="Disabled",
        redirect_uris=["https://x.test/cb"],
        allowed_scopes=["openid"],
        enabled=False,
    )
    db_session.add(c)
    await db_session.commit()

    from app.satosa_generator import generate_and_write
    await generate_and_write(db_session)

    out = tmp_path / "oidcop_clients.yaml"
    data = yaml.safe_load(out.read_text())
    assert "disabled-app" not in data["OIDCOP"]["clients"]


async def test_generate_empty_clients(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    from app.satosa_generator import generate_and_write
    await generate_and_write(db_session)

    out = tmp_path / "oidcop_clients.yaml"
    data = yaml.safe_load(out.read_text())
    assert data["OIDCOP"]["clients"] == {}
```

- [ ] **Step 2: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_satosa_generator.py -v 2>&1 | head -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.satosa_generator'`

- [ ] **Step 3: Create `config-api/app/satosa_generator.py`**

```python
import os
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OIDCClient

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")


async def generate_and_write(db: AsyncSession) -> None:
    result = await db.execute(select(OIDCClient).where(OIDCClient.enabled == True))
    clients_rows = result.scalars().all()

    clients_dict = {}
    for c in clients_rows:
        clients_dict[c.client_id] = {
            "client_secret": c.client_secret_hash,
            "redirect_uris": list(c.redirect_uris),
            "allowed_scopes": list(c.allowed_scopes),
        }

    config = {"OIDCOP": {"clients": clients_dict}}

    conf_dir = os.environ.get("SATOSA_CONF_DIR", SATOSA_CONF_DIR)
    os.makedirs(conf_dir, exist_ok=True)
    path = os.path.join(conf_dir, "oidcop_clients.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
```

- [ ] **Step 4: Run tests — must pass**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_satosa_generator.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add config-api/app/satosa_generator.py config-api/tests/test_satosa_generator.py
git commit -m "feat: satosa_generator — writes oidcop_clients.yaml from DB"
```

---

## Task 3: satosa_reload.py + tests

**Files:**
- Create: `config-api/app/satosa_reload.py`
- Create: `config-api/tests/test_satosa_reload.py`

- [ ] **Step 1: Write failing tests**

Create `config-api/tests/test_satosa_reload.py`:

```python
from unittest.mock import MagicMock, patch


def test_reload_satosa_success():
    mock_container = MagicMock()
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    with patch("app.satosa_reload.docker.from_env", return_value=mock_client):
        from app.satosa_reload import reload_satosa
        result = reload_satosa()

    assert result is True
    mock_container.restart.assert_called_once_with(timeout=10)


def test_reload_satosa_container_not_found():
    mock_client = MagicMock()
    mock_client.containers.get.side_effect = Exception("container not found")

    with patch("app.satosa_reload.docker.from_env", return_value=mock_client):
        from app.satosa_reload import reload_satosa
        result = reload_satosa()

    assert result is False


def test_reload_satosa_docker_unavailable():
    with patch("app.satosa_reload.docker.from_env", side_effect=Exception("socket not found")):
        from app.satosa_reload import reload_satosa
        result = reload_satosa()

    assert result is False
```

- [ ] **Step 2: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_satosa_reload.py -v 2>&1 | head -20
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.satosa_reload'`

- [ ] **Step 3: Create `config-api/app/satosa_reload.py`**

```python
import os
import docker

SATOSA_CONTAINER_NAME = os.environ.get("SATOSA_CONTAINER_NAME", "pa-sso-proxy-satosa-1")


def reload_satosa() -> bool:
    try:
        client = docker.from_env()
        container = client.containers.get(SATOSA_CONTAINER_NAME)
        container.restart(timeout=10)
        return True
    except Exception:
        return False
```

- [ ] **Step 4: Run tests — must pass**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_satosa_reload.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add config-api/app/satosa_reload.py config-api/tests/test_satosa_reload.py
git commit -m "feat: satosa_reload — docker SDK container restart"
```

---

## Task 4: Client list + create + reveal routes

**Files:**
- Create: `config-api/app/templates/clients/list.html.j2`
- Create: `config-api/app/templates/clients/form.html.j2`
- Create: `config-api/app/templates/clients/reveal.html.j2`
- Create: `config-api/app/routes/clients.py` (list + create + reveal only)
- Modify: `config-api/app/main.py`
- Create: `config-api/tests/test_clients.py` (list + create tests)

- [ ] **Step 1: Create `config-api/app/templates/clients/list.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}Clienti OIDC — PA SSO Proxy{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-3">
  <h2>Clienti OIDC</h2>
  <a href="/admin/clients/new" class="btn btn-primary btn-sm">+ Aggiungi client</a>
</div>
{% if clients %}
<table class="table table-sm table-hover">
  <thead>
    <tr>
      <th>Nome</th><th>Client ID</th><th>Redirect URI</th><th>Scopes</th><th>Stato</th><th>Azioni</th>
    </tr>
  </thead>
  <tbody>
    {% for c in clients %}
    <tr>
      <td>{{ c.name }}</td>
      <td><code>{{ c.client_id }}</code></td>
      <td><small>{{ c.redirect_uris | join('<br>'|safe) }}</small></td>
      <td><small>{{ c.allowed_scopes | join(', ') }}</small></td>
      <td>
        {% if c.enabled %}<span class="badge bg-success">Attivo</span>
        {% else %}<span class="badge bg-secondary">Disabilitato</span>{% endif %}
      </td>
      <td>
        <a href="/admin/clients/{{ c.id }}/edit" class="btn btn-sm btn-outline-secondary">Modifica</a>
        <form method="post" action="/admin/clients/{{ c.id }}/toggle" class="d-inline">
          <button class="btn btn-sm btn-outline-warning">{% if c.enabled %}Disabilita{% else %}Abilita{% endif %}</button>
        </form>
        <form method="post" action="/admin/clients/{{ c.id }}/delete" class="d-inline"
              onsubmit="return confirm('Eliminare {{ c.name }}?')">
          <button class="btn btn-sm btn-outline-danger">Elimina</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p class="text-muted">Nessun client OIDC configurato. <a href="/admin/clients/new">Aggiungi il primo.</a></p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Create `config-api/app/templates/clients/form.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}{% if client %}Modifica client{% else %}Nuovo client{% endif %} — PA SSO Proxy{% endblock %}
{% block content %}
<h2>{% if client %}Modifica {{ client.name }}{% else %}Nuovo client OIDC{% endif %}</h2>
{% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
<form method="post" class="mt-3" style="max-width:600px">
  <div class="mb-3">
    <label class="form-label">Nome applicazione</label>
    <input type="text" name="name" class="form-control" required
           value="{{ client.name if client else '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label">Redirect URI <small class="text-muted">(una per riga)</small></label>
    <textarea name="redirect_uris" class="form-control" rows="3" required>{{ client.redirect_uris | join('\n') if client else '' }}</textarea>
  </div>
  <div class="mb-3">
    <label class="form-label d-block">Scopes</label>
    {% set current_scopes = client.allowed_scopes if client else ['openid'] %}
    {% for scope in ['openid', 'profile', 'email'] %}
    <div class="form-check form-check-inline">
      <input class="form-check-input" type="checkbox" name="scopes" value="{{ scope }}"
             {% if scope in current_scopes %}checked{% endif %}>
      <label class="form-check-label">{{ scope }}</label>
    </div>
    {% endfor %}
  </div>
  {% if client %}
  <div class="mb-3">
    <div class="form-check">
      <input class="form-check-input" type="checkbox" name="enabled" value="1"
             {% if client.enabled %}checked{% endif %}>
      <label class="form-check-label">Abilitato</label>
    </div>
  </div>
  {% endif %}
  <button type="submit" class="btn btn-primary">Salva</button>
  <a href="/admin/clients" class="btn btn-secondary ms-2">Annulla</a>
</form>
{% endblock %}
```

- [ ] **Step 3: Create `config-api/app/templates/clients/reveal.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}Client creato — PA SSO Proxy{% endblock %}
{% block content %}
<div class="alert alert-success">
  <h4 class="alert-heading">Client OIDC creato</h4>
  <p><strong>Attenzione:</strong> il client secret è mostrato una sola volta. Copialo ora — non sarà più visibile.</p>
  <hr>
  {% if client_id %}
  <p class="mb-1"><strong>Client ID:</strong> <code>{{ client_id }}</code></p>
  <p class="mb-0"><strong>Client Secret:</strong> <code>{{ client_secret }}</code></p>
  {% else %}
  <p class="mb-0 text-muted">Secret già visualizzato o sessione scaduta.</p>
  {% endif %}
</div>
<a href="/admin/clients" class="btn btn-primary mt-2">Vai alla lista clienti</a>
{% endblock %}
```

- [ ] **Step 4: Write failing tests**

Create `config-api/tests/test_clients.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch

from app.database import get_db
from app.models import OIDCClient


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-plan2")
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


async def test_clients_list_empty(auth_client):
    response = await auth_client.get("/admin/clients")
    assert response.status_code == 200
    assert "Nessun client" in response.text


async def test_clients_list_unauthenticated():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/clients", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


async def test_client_create_redirects_to_reveal(auth_client):
    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        response = await auth_client.post(
            "/admin/clients/new",
            data={
                "name": "Test App",
                "redirect_uris": "https://app.test/callback",
                "scopes": ["openid", "profile"],
            },
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "/reveal" in response.headers["location"]


async def test_client_create_missing_redirect_uri_returns_400(auth_client):
    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        response = await auth_client.post(
            "/admin/clients/new",
            data={"name": "Test App", "redirect_uris": "   ", "scopes": ["openid"]},
            follow_redirects=False,
        )
    assert response.status_code == 400


async def test_client_reveal_shows_secret_once(auth_client):
    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        create_resp = await auth_client.post(
            "/admin/clients/new",
            data={"name": "Test App", "redirect_uris": "https://app.test/cb", "scopes": ["openid"]},
            follow_redirects=True,
        )
    assert create_resp.status_code == 200
    # Secret shown on first visit
    assert "Client ID" in create_resp.text
    assert "Client Secret" in create_resp.text
```

- [ ] **Step 5: Run failing tests**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_clients.py -v 2>&1 | head -30
```

Expected: FAIL — routes not registered yet.

- [ ] **Step 6: Create `config-api/app/routes/clients.py`** (list + create + reveal only)

```python
import asyncio
import os
import secrets

import bcrypt
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import OIDCClient
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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
    return RedirectResponse(f"/admin/clients/{c.id}/reveal", status_code=302)


@router.get("/clients/{client_id}/reveal", response_class=HTMLResponse)
async def clients_reveal(request: Request, client_id: int):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    secret = request.session.pop("reveal_secret", None)
    cid = request.session.pop("reveal_client_id", None)
    return templates.TemplateResponse(
        request, "clients/reveal.html.j2", {"client_id": cid, "client_secret": secret}
    )
```

- [ ] **Step 7: Register clients router in `config-api/app/main.py`**

Add the import and `include_router` call. The full updated `main.py`:

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.routes import dashboard, clients

SESSION_SECRET = os.environ.get("SESSION_SECRET", "changeme")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

templates = Jinja2Templates(directory="app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
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

- [ ] **Step 8: Run tests — must pass**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_clients.py -v
```

Expected: 5/5 PASS.

- [ ] **Step 9: Run full test suite**

```bash
cd config-api
PYTHONPATH=. pytest -v --tb=short
```

Expected: all existing tests still passing + 5 new.

- [ ] **Step 10: Commit**

```bash
git add config-api/app/satosa_generator.py config-api/app/satosa_reload.py \
        config-api/app/routes/clients.py config-api/app/main.py \
        config-api/app/templates/clients/ config-api/tests/test_clients.py
git commit -m "feat: OIDC client list + create + reveal — with generator + reload"
```

---

## Task 5: Client edit + toggle + delete routes

**Files:**
- Modify: `config-api/app/routes/clients.py`
- Modify: `config-api/tests/test_clients.py`

- [ ] **Step 1: Write failing tests** — add to `config-api/tests/test_clients.py`

Append these tests to the existing `test_clients.py` (after `test_client_reveal_shows_secret_once`):

```python
async def test_client_list_shows_existing(auth_client, db_session):
    c = OIDCClient(
        client_id="existing-app",
        client_secret_hash="hash",
        name="Existing App",
        redirect_uris=["https://existing.test/cb"],
        allowed_scopes=["openid"],
        enabled=True,
    )
    db_session.add(c)
    await db_session.commit()

    response = await auth_client.get("/admin/clients")
    assert response.status_code == 200
    assert "Existing App" in response.text
    assert "existing-app" in response.text


async def test_client_toggle_disables(auth_client, db_session):
    from sqlalchemy import select as sa_select
    c = OIDCClient(
        client_id="to-toggle",
        client_secret_hash="hash",
        name="Toggle Me",
        redirect_uris=["https://x.test/cb"],
        allowed_scopes=["openid"],
        enabled=True,
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)

    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        response = await auth_client.post(
            f"/admin/clients/{c.id}/toggle", follow_redirects=False
        )
    assert response.status_code == 302

    await db_session.refresh(c)
    assert c.enabled is False


async def test_client_delete_removes_record(auth_client, db_session):
    from sqlalchemy import select as sa_select
    c = OIDCClient(
        client_id="to-delete",
        client_secret_hash="hash",
        name="Delete Me",
        redirect_uris=["https://x.test/cb"],
        allowed_scopes=["openid"],
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)

    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        response = await auth_client.post(
            f"/admin/clients/{c.id}/delete", follow_redirects=False
        )
    assert response.status_code == 302

    result = await db_session.execute(sa_select(OIDCClient).where(OIDCClient.id == c.id))
    assert result.scalar_one_or_none() is None


async def test_client_edit_form_shows_prefilled(auth_client, db_session):
    c = OIDCClient(
        client_id="editable-app",
        client_secret_hash="hash",
        name="Editable App",
        redirect_uris=["https://edit.test/cb"],
        allowed_scopes=["openid", "profile"],
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)

    response = await auth_client.get(f"/admin/clients/{c.id}/edit")
    assert response.status_code == 200
    assert "Editable App" in response.text
    assert "https://edit.test/cb" in response.text


async def test_client_edit_updates_record(auth_client, db_session):
    c = OIDCClient(
        client_id="update-app",
        client_secret_hash="hash",
        name="Old Name",
        redirect_uris=["https://old.test/cb"],
        allowed_scopes=["openid"],
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)

    with patch("app.routes.clients.generate_and_write", new_callable=AsyncMock), \
         patch("app.routes.clients.reload_satosa", return_value=True):
        response = await auth_client.post(
            f"/admin/clients/{c.id}/edit",
            data={
                "name": "New Name",
                "redirect_uris": "https://new.test/cb",
                "scopes": ["openid", "email"],
                "enabled": "1",
            },
            follow_redirects=False,
        )
    assert response.status_code == 302

    await db_session.refresh(c)
    assert c.name == "New Name"
    assert c.redirect_uris == ["https://new.test/cb"]
    assert "email" in c.allowed_scopes
```

- [ ] **Step 2: Run to verify failure**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_clients.py::test_client_toggle_disables -v 2>&1 | head -20
```

Expected: FAIL — routes not yet implemented.

- [ ] **Step 3: Add edit + toggle + delete routes to `config-api/app/routes/clients.py`**

Append to the existing `clients.py` (after `clients_reveal`):

```python
@router.get("/clients/{client_id}/edit", response_class=HTMLResponse)
async def clients_edit_form(request: Request, client_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(OIDCClient).where(OIDCClient.id == client_id))
    client = result.scalar_one_or_none()
    if not client:
        return RedirectResponse("/admin/clients", status_code=302)
    return templates.TemplateResponse(request, "clients/form.html.j2", {"client": client, "error": None})


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
```

- [ ] **Step 4: Run all client tests**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_clients.py -v
```

Expected: 10/10 PASS.

- [ ] **Step 5: Run full test suite**

```bash
cd config-api
PYTHONPATH=. pytest -v --tb=short
```

Expected: all tests pass (models + auth + dashboard + generator + reload + clients).

- [ ] **Step 6: Commit**

```bash
git add config-api/app/routes/clients.py config-api/tests/test_clients.py
git commit -m "feat: OIDC client edit/toggle/delete routes — Plan 2 complete"
```

---

## Self-Review

**Spec coverage:**
- ✅ CRUD client OIDC (list, create, edit, delete, toggle enabled)
- ✅ Config generator: legge `oidc_clients WHERE enabled=true` → `oidcop_clients.yaml`
- ✅ SATOSA reload via docker SDK dopo ogni mutazione
- ✅ Client secret: bcrypt hash in DB, plaintext mostrato una sola volta
- ✅ Auth check su tutte le route `/admin/clients*`
- ✅ Volume condiviso `proxy_satosa_conf` tra config-api e satosa
- ⏭ Config generator completo (tutti i backend SATOSA) → Plan 5
- ⏭ Provider SPID → Plan 3
- ⏭ CIE OIDC JWK → Plan 4

**Placeholder scan:** nessun TBD o TODO.

**Type consistency:**
- `generate_and_write(db: AsyncSession)` — definita in Task 2, usata in Tasks 4 e 5 ✅
- `reload_satosa() -> bool` — definita in Task 3, usata in Tasks 4 e 5 ✅
- `OIDCClient.redirect_uris` è `list[str]` (ARRAY → JSON in test) — usato con `list(c.redirect_uris)` in generator ✅
- `_auth_check(request)` — helper definito in Task 4, usato in Task 5 ✅

**Note per Plan 3:**
- Stesso pattern: `generate_and_write` espanderà la sezione SPID del config SATOSA
- `satosa_reload.py` non cambia
