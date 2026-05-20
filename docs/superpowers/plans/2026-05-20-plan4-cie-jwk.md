# pa-sso-proxy — Plan 4: CIE OIDC JWK Management + Entity Configuration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WebUI per generare e gestire chiavi JWK EC P-256 per CIE OIDC, configurare CieConfig (id=1 singleton), e scrivere i JWKS file nel volume SATOSA.

**Architecture:** `jwk_generator.py` genera EC P-256 keypair serializzato come JWK dict (senza dipendenze extra — solo `cryptography` già in requirements.txt). `cie_jwks_writer.py` serializza i JwkKey come JWKS JSON pubblico+privato sul volume SATOSA (stesso pattern di `satosa_generator.py`). Router `routes/cie.py` gestisce form CieConfig + CRUD chiavi JWK con auth guard.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, cryptography 43.0 (già presente), Jinja2/Bootstrap 5. Nessuna nuova dipendenza.

---

## File Map

```
config-api/
  app/
    jwk_generator.py         New: generate_jwk(name, use) -> JwkKey (EC P-256, not committed)
    cie_jwks_writer.py       New: write_jwks_files(keys: list[JwkKey]) -> None
    routes/
      cie.py                 New: GET /cie, POST /cie, POST /cie/generate-jwk/{use}, POST /cie/delete-jwk/{id}
    templates/
      cie/
        config.html.j2       New: CIE config form + JWK keys table
  tests/
    test_jwk_generator.py    New: 3 tests
    test_cie_jwks_writer.py  New: 2 tests
    test_cie.py              New: 5 tests
  main.py                    Modify: aggiunge import cie + app.include_router(cie.router)
```

**Modelli già esistenti (non modificare):**

`JwkKey` (`config-api/app/models/key.py`):
```
id (PK), name (String 64, unique), use (String 16: "federation"|"sig"|"enc"),
private_jwk (JSONB), public_jwk (JSONB), created_at
```

`CieConfig` (`config-api/app/models/cie.py`):
```
id (PK, sempre 1), saml_metadata_url (Text),
oidc_federation_enabled (Boolean, default False),
jwk_federation_id (FK → jwk_keys.id, nullable),
jwk_core_sig_id (FK → jwk_keys.id, nullable),
jwk_core_enc_id (FK → jwk_keys.id, nullable)
```

Entrambi esportati da `config-api/app/models/__init__.py`.

**Nota sui test:** `conftest.py` fa monkey-patch di `pg_dialect.JSONB = JSON` prima di importare i modelli. `JwkKey.private_jwk` e `public_jwk` sono `JSONB` → in SQLite test vengono gestiti come `JSON`. Valori dict funzionano correttamente in round-trip.

---

## Task 1: jwk_generator.py + tests

**Files:**
- Create: `config-api/app/jwk_generator.py`
- Create: `config-api/tests/test_jwk_generator.py`

- [ ] **Step 1: Write failing tests**

Create `config-api/tests/test_jwk_generator.py`:

```python
from app.models import JwkKey


def test_generate_jwk_returns_jwk_key_instance():
    from app.jwk_generator import generate_jwk
    key = generate_jwk("test-key", "sig")
    assert isinstance(key, JwkKey)
    assert key.name == "test-key"
    assert key.use == "sig"


def test_generate_jwk_public_jwk_format():
    from app.jwk_generator import generate_jwk
    key = generate_jwk("test-sig", "sig")
    pub = key.public_jwk
    assert pub["kty"] == "EC"
    assert pub["crv"] == "P-256"
    assert "x" in pub
    assert "y" in pub
    assert "kid" in pub
    assert pub["use"] == "sig"
    assert "d" not in pub


def test_generate_jwk_private_jwk_has_d():
    from app.jwk_generator import generate_jwk
    key = generate_jwk("test-enc", "enc")
    assert "d" in key.private_jwk
    assert key.private_jwk["kty"] == "EC"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd config-api && PYTHONPATH=. python -m pytest tests/test_jwk_generator.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'app.jwk_generator'`

- [ ] **Step 3: Create `config-api/app/jwk_generator.py`**

```python
import base64
import uuid

from cryptography.hazmat.primitives.asymmetric import ec

from app.models import JwkKey


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_int(n: int, length: int = 32) -> str:
    return _b64url(n.to_bytes(length, byteorder="big"))


def generate_jwk(name: str, use: str) -> JwkKey:
    """Generate EC P-256 keypair as JWK. Returns unsaved JwkKey instance."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pub = private_key.public_key().public_numbers()
    priv = private_key.private_numbers()
    kid = str(uuid.uuid4())

    public_jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_int(pub.x),
        "y": _b64url_int(pub.y),
        "use": use,
        "kid": kid,
    }
    private_jwk = {**public_jwk, "d": _b64url_int(priv.private_value)}

    return JwkKey(name=name, use=use, private_jwk=private_jwk, public_jwk=public_jwk)
```

- [ ] **Step 4: Run tests — must pass (3/3)**

```bash
cd config-api && PYTHONPATH=. python -m pytest tests/test_jwk_generator.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Run full suite**

```bash
cd config-api && PYTHONPATH=. python -m pytest -v --tb=short
```

Expected: 46 preesistenti + 3 nuovi = 49 PASS.

- [ ] **Step 6: Commit**

```bash
git add config-api/app/jwk_generator.py config-api/tests/test_jwk_generator.py
git commit -m "feat: JWK generator — EC P-256 keypair per CIE OIDC"
```

---

## Task 2: cie_jwks_writer.py + tests

**Files:**
- Create: `config-api/app/cie_jwks_writer.py`
- Create: `config-api/tests/test_cie_jwks_writer.py`

- [ ] **Step 1: Write failing tests**

Create `config-api/tests/test_cie_jwks_writer.py`:

```python
import json
from app.models import JwkKey


def test_write_jwks_creates_files(tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    keys = [
        JwkKey(
            name="k1", use="sig",
            public_jwk={"kty": "EC", "kid": "abc", "use": "sig"},
            private_jwk={"kty": "EC", "kid": "abc", "use": "sig", "d": "xxx"},
        ),
    ]

    from app.cie_jwks_writer import write_jwks_files
    write_jwks_files(keys)

    pub_path = tmp_path / "cie_jwks_public.json"
    priv_path = tmp_path / "cie_jwks_private.json"
    assert pub_path.exists()
    assert priv_path.exists()

    pub_data = json.loads(pub_path.read_text())
    priv_data = json.loads(priv_path.read_text())
    assert pub_data == {"keys": [{"kty": "EC", "kid": "abc", "use": "sig"}]}
    assert priv_data == {"keys": [{"kty": "EC", "kid": "abc", "use": "sig", "d": "xxx"}]}


def test_write_jwks_empty_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))

    from app.cie_jwks_writer import write_jwks_files
    write_jwks_files([])

    pub_data = json.loads((tmp_path / "cie_jwks_public.json").read_text())
    assert pub_data == {"keys": []}
```

- [ ] **Step 2: Run to verify failure**

```bash
cd config-api && PYTHONPATH=. python -m pytest tests/test_cie_jwks_writer.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'app.cie_jwks_writer'`

- [ ] **Step 3: Create `config-api/app/cie_jwks_writer.py`**

```python
import json
import os

from app.models import JwkKey

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")


def write_jwks_files(keys: list[JwkKey]) -> None:
    """Write public and private JWKS JSON to SATOSA volume."""
    conf_dir = os.environ.get("SATOSA_CONF_DIR", SATOSA_CONF_DIR)
    os.makedirs(conf_dir, exist_ok=True)
    public_jwks = {"keys": [k.public_jwk for k in keys]}
    private_jwks = {"keys": [k.private_jwk for k in keys]}
    with open(os.path.join(conf_dir, "cie_jwks_public.json"), "w") as f:
        json.dump(public_jwks, f)
    with open(os.path.join(conf_dir, "cie_jwks_private.json"), "w") as f:
        json.dump(private_jwks, f)
```

- [ ] **Step 4: Run tests — must pass (2/2)**

```bash
cd config-api && PYTHONPATH=. python -m pytest tests/test_cie_jwks_writer.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Run full suite**

```bash
cd config-api && PYTHONPATH=. python -m pytest -v --tb=short
```

Expected: 49 + 2 = 51 PASS.

- [ ] **Step 6: Commit**

```bash
git add config-api/app/cie_jwks_writer.py config-api/tests/test_cie_jwks_writer.py
git commit -m "feat: cie_jwks_writer — scrive JWKS pubblico/privato nel volume SATOSA"
```

---

## Task 3: CIE routes + template + register in main.py

**Files:**
- Create: `config-api/app/templates/cie/config.html.j2`
- Create: `config-api/app/routes/cie.py`
- Create: `config-api/tests/test_cie.py`
- Modify: `config-api/app/main.py`

- [ ] **Step 1: Read `config-api/app/templates/base.html.j2`**

Verifica i nomi dei block (`title`, `content`) prima di creare il template.

- [ ] **Step 2: Create `config-api/app/templates/cie/config.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}CIE OIDC — PA SSO Proxy{% endblock %}
{% block content %}
<h2>CIE OIDC</h2>

<h5 class="mt-4">Configurazione</h5>
<form method="post" action="/admin/cie" style="max-width:640px">
  <div class="mb-3">
    <label class="form-label">URL Metadata SAML CIE</label>
    <input type="url" name="saml_metadata_url" class="form-control" required
           value="{{ cfg.saml_metadata_url if cfg else 'https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata' }}">
  </div>
  <div class="mb-3 form-check">
    <input type="checkbox" class="form-check-input" id="oidc_fed" name="oidc_federation_enabled" value="1"
           {% if cfg and cfg.oidc_federation_enabled %}checked{% endif %}>
    <label class="form-check-label" for="oidc_fed">Abilita OIDC Federation</label>
  </div>
  <div class="mb-3">
    <label class="form-label">JWK Federation</label>
    <select name="jwk_federation_id" class="form-select">
      <option value="">— nessuna —</option>
      {% for k in jwk_keys if k.use == 'federation' %}
      <option value="{{ k.id }}" {% if cfg and cfg.jwk_federation_id == k.id %}selected{% endif %}>
        {{ k.name }} ({{ k.public_jwk.kid[:8] }}…)
      </option>
      {% endfor %}
    </select>
  </div>
  <div class="mb-3">
    <label class="form-label">JWK Core Signature</label>
    <select name="jwk_core_sig_id" class="form-select">
      <option value="">— nessuna —</option>
      {% for k in jwk_keys if k.use == 'sig' %}
      <option value="{{ k.id }}" {% if cfg and cfg.jwk_core_sig_id == k.id %}selected{% endif %}>
        {{ k.name }} ({{ k.public_jwk.kid[:8] }}…)
      </option>
      {% endfor %}
    </select>
  </div>
  <div class="mb-3">
    <label class="form-label">JWK Core Encryption</label>
    <select name="jwk_core_enc_id" class="form-select">
      <option value="">— nessuna —</option>
      {% for k in jwk_keys if k.use == 'enc' %}
      <option value="{{ k.id }}" {% if cfg and cfg.jwk_core_enc_id == k.id %}selected{% endif %}>
        {{ k.name }} ({{ k.public_jwk.kid[:8] }}…)
      </option>
      {% endfor %}
    </select>
  </div>
  <button type="submit" class="btn btn-primary">Salva</button>
</form>

<h5 class="mt-5">Chiavi JWK</h5>
<div class="mb-2">
  <form method="post" action="/admin/cie/generate-jwk/federation" class="d-inline">
    <button class="btn btn-sm btn-outline-secondary">+ Federation</button>
  </form>
  <form method="post" action="/admin/cie/generate-jwk/sig" class="d-inline ms-1">
    <button class="btn btn-sm btn-outline-secondary">+ Sig</button>
  </form>
  <form method="post" action="/admin/cie/generate-jwk/enc" class="d-inline ms-1">
    <button class="btn btn-sm btn-outline-secondary">+ Enc</button>
  </form>
</div>
{% if jwk_keys %}
<table class="table table-sm table-hover">
  <thead>
    <tr><th>Nome</th><th>Use</th><th>KID</th><th>Creato</th><th></th></tr>
  </thead>
  <tbody>
    {% for k in jwk_keys %}
    <tr>
      <td>{{ k.name }}</td>
      <td><span class="badge bg-secondary">{{ k.use }}</span></td>
      <td><code>{{ k.public_jwk.kid[:16] }}…</code></td>
      <td><small>{{ k.created_at.strftime('%Y-%m-%d') }}</small></td>
      <td>
        <form method="post" action="/admin/cie/delete-jwk/{{ k.id }}" class="d-inline">
          <button class="btn btn-sm btn-outline-danger">Elimina</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p class="text-muted">Nessuna chiave JWK. Generane una con i pulsanti sopra.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Write failing tests**

Create `config-api/tests/test_cie.py`:

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch

from app.database import get_db
from app.models import CieConfig, JwkKey


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-plan4")
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


async def test_cie_form_shows_empty(auth_client):
    response = await auth_client.get("/admin/cie")
    assert response.status_code == 200
    assert "CIE OIDC" in response.text


async def test_cie_unauthenticated_redirects():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/cie", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


async def test_cie_save_creates_config(auth_client, db_session):
    from sqlalchemy import select
    with patch("app.routes.cie.write_jwks_files"):
        response = await auth_client.post(
            "/admin/cie",
            data={
                "saml_metadata_url": "https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
                "oidc_federation_enabled": "",
                "jwk_federation_id": "",
                "jwk_core_sig_id": "",
                "jwk_core_enc_id": "",
            },
            follow_redirects=False,
        )
    assert response.status_code == 302
    result = await db_session.execute(select(CieConfig).where(CieConfig.id == 1))
    cfg = result.scalar_one_or_none()
    assert cfg is not None
    assert "servizicie" in cfg.saml_metadata_url


async def test_cie_generate_jwk_creates_key(auth_client, db_session):
    from sqlalchemy import select
    with patch("app.routes.cie.write_jwks_files"):
        response = await auth_client.post(
            "/admin/cie/generate-jwk/sig",
            follow_redirects=False,
        )
    assert response.status_code == 302
    result = await db_session.execute(select(JwkKey).where(JwkKey.use == "sig"))
    keys = result.scalars().all()
    assert len(keys) == 1
    assert keys[0].public_jwk["kty"] == "EC"


async def test_cie_delete_jwk_removes_key(auth_client, db_session):
    from sqlalchemy import select
    key = JwkKey(
        name="del-test",
        use="sig",
        public_jwk={"kty": "EC", "kid": "test-kid-abc", "use": "sig"},
        private_jwk={"kty": "EC", "kid": "test-kid-abc", "use": "sig", "d": "xxx"},
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)

    with patch("app.routes.cie.write_jwks_files"):
        response = await auth_client.post(
            f"/admin/cie/delete-jwk/{key.id}",
            follow_redirects=False,
        )
    assert response.status_code == 302
    result = await db_session.execute(select(JwkKey).where(JwkKey.id == key.id))
    assert result.scalar_one_or_none() is None
```

- [ ] **Step 4: Run to verify failure**

```bash
cd config-api && PYTHONPATH=. python -m pytest tests/test_cie.py -v 2>&1 | head -20
```

Expected: FAIL — route not registered (404) o ImportError.

- [ ] **Step 5: Create `config-api/app/routes/cie.py`**

```python
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cie_jwks_writer import write_jwks_files
from app.database import get_db
from app.jwk_generator import generate_jwk
from app.models import CieConfig, JwkKey

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/cie", response_class=HTMLResponse)
async def cie_config_form(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    cfg = result.scalar_one_or_none()
    keys_result = await db.execute(select(JwkKey).order_by(JwkKey.created_at.desc()))
    jwk_keys = keys_result.scalars().all()
    return templates.TemplateResponse(request, "cie/config.html.j2", {"cfg": cfg, "jwk_keys": jwk_keys})


@router.post("/cie")
async def cie_config_save(
    request: Request,
    saml_metadata_url: str = Form(...),
    oidc_federation_enabled: str = Form(default=""),
    jwk_federation_id: str = Form(default=""),
    jwk_core_sig_id: str = Form(default=""),
    jwk_core_enc_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        cfg = CieConfig(id=1)
        db.add(cfg)
    cfg.saml_metadata_url = saml_metadata_url
    cfg.oidc_federation_enabled = oidc_federation_enabled == "1"
    cfg.jwk_federation_id = int(jwk_federation_id) if jwk_federation_id else None
    cfg.jwk_core_sig_id = int(jwk_core_sig_id) if jwk_core_sig_id else None
    cfg.jwk_core_enc_id = int(jwk_core_enc_id) if jwk_core_enc_id else None
    await db.commit()
    keys_result = await db.execute(select(JwkKey))
    write_jwks_files(keys_result.scalars().all())
    return RedirectResponse("/admin/cie", status_code=302)


@router.post("/cie/generate-jwk/{use}")
async def cie_generate_jwk(request: Request, use: str, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    if use not in ("federation", "sig", "enc"):
        return RedirectResponse("/admin/cie", status_code=302)
    key = generate_jwk(f"cie-{use}-{uuid.uuid4().hex[:8]}", use)
    db.add(key)
    await db.commit()
    keys_result = await db.execute(select(JwkKey))
    write_jwks_files(keys_result.scalars().all())
    return RedirectResponse("/admin/cie", status_code=302)


@router.post("/cie/delete-jwk/{jwk_id}")
async def cie_delete_jwk(request: Request, jwk_id: int, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    cfg_result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    cfg = cfg_result.scalar_one_or_none()
    if cfg:
        if cfg.jwk_federation_id == jwk_id:
            cfg.jwk_federation_id = None
        if cfg.jwk_core_sig_id == jwk_id:
            cfg.jwk_core_sig_id = None
        if cfg.jwk_core_enc_id == jwk_id:
            cfg.jwk_core_enc_id = None
        await db.commit()
    key_result = await db.execute(select(JwkKey).where(JwkKey.id == jwk_id))
    key = key_result.scalar_one_or_none()
    if key:
        await db.delete(key)
        await db.commit()
    keys_result = await db.execute(select(JwkKey))
    write_jwks_files(keys_result.scalars().all())
    return RedirectResponse("/admin/cie", status_code=302)
```

- [ ] **Step 6: Update `config-api/app/main.py`**

Read current `main.py`. Applica solo queste due modifiche:

1. Riga imports routes — cambia:
```python
from app.routes import dashboard, clients, idps, settings, certs
```
in:
```python
from app.routes import dashboard, clients, idps, settings, certs, cie
```

2. Dopo `app.include_router(certs.router, prefix="/admin")` aggiungi:
```python
app.include_router(cie.router, prefix="/admin")
```

- [ ] **Step 7: Run tests — must pass (5/5)**

```bash
cd config-api && PYTHONPATH=. python -m pytest tests/test_cie.py -v
```

Expected: 5 PASS.

- [ ] **Step 8: Run full suite**

```bash
cd config-api && PYTHONPATH=. python -m pytest -v --tb=short
```

Expected: 51 + 5 = 56 PASS.

- [ ] **Step 9: Commit**

```bash
git add config-api/app/routes/cie.py config-api/app/templates/cie/ \
        config-api/app/main.py config-api/tests/test_cie.py
git commit -m "feat: CIE OIDC — WebUI JWK management + configurazione entity"
```

---

## Self-Review

**Spec coverage:**
- ✅ JWK EC P-256 generation — Task 1
- ✅ JWKS file scritti su volume SATOSA (pubblico + privato) — Task 2
- ✅ CieConfig upsert id=1 — Task 3
- ✅ Toggle OIDC federation — Task 3
- ✅ Selezione JWK per use (federation/sig/enc) — Task 3
- ✅ Genera nuova chiave JWK per use — Task 3
- ✅ Elimina chiave JWK (svuota FK in CieConfig prima) — Task 3
- ⏭ Generazione entity statement JWT firmato → Plan 5
- ⏭ Endpoint pubblico JWKS (`/admin/cie/jwks.json`) → Plan 5 (SATOSA lo serve direttamente)

**Placeholder scan:** nessun TBD o TODO.

**Type consistency:**
- `generate_jwk(name: str, use: str) -> JwkKey` — Task 1, usata in Task 3 `cie.py` ✅
- `write_jwks_files(keys: list[JwkKey]) -> None` — Task 2, usata in Task 3 `cie.py` ✅
- `CieConfig.jwk_federation_id` è `Optional[int]` — assegnato `int(jwk_federation_id) if jwk_federation_id else None` ✅
- Template usa `k.public_jwk.kid` (dict access via Jinja2 dot notation) — equivalente a `k.public_jwk['kid']` in Jinja2 ✅
- `write_jwks_files` è sync (solo file I/O, no DB) — chiamata diretta senza `asyncio.to_thread` (OK per admin app) ✅

**Nota per Plan 5:** i file `cie_jwks_public.json` e `cie_jwks_private.json` nel volume SATOSA saranno usati dal plugin CIE OIDC di SATOSA per firmare i JWT. Il path `/satosa-conf/cie_jwks_private.json` andrà nella configurazione SATOSA backend.
