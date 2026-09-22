# SPID persona giuridica (Tipo 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettere il login SPID a persone giuridiche (Tipo 4, "uso professionale per la persona giuridica") per i client OIDC che lo richiedono esplicitamente, tramite l'estensione SAML `Purpose=PG` prevista da AgID.

**Architecture:** Un flag ente-wide (`EnteSettings.legal_entity_enabled`) abilita gli attributi azienda opzionali nel metadata SP pubblicato (richiede ri-validazione AgID). Un client OIDC dichiara supporto persona giuridica aggiungendo lo scope `legal_entity` ai propri `allowed_scopes`. Quando un client con quello scope avvia un login, `spidsaml2.py` (già in questo repo) rileva lo scope nella query OIDC originale — stesso meccanismo già usato oggi per `acs_index` — e aggiunge `Purpose=PG` all'`AuthnRequest` SAML, qualunque IdP l'utente scelga dalla discovery page invariata. Nessuna nuova UI, nessun filtro IdP: se l'IdP non supporta ancora Tipo 4, l'errore AgID `nr30` è già gestito con messaggio corretto dal codice esistente.

**Tech Stack:** FastAPI + SQLAlchemy async + Jinja2 (config-api), pysaml2 + SATOSA fork (satosa/plugins), pytest + pytest-asyncio, alembic.

**Spec:** `docs/superpowers/specs/2026-09-21-spid-persona-giuridica-design.md`

## Global Constraints

- Nessuna migrazione distruttiva: nuova colonna `legal_entity_enabled` con `server_default="false"`, pattern identico a `eidas_enabled` (`alembic/versions/012_eidas_settings.py`).
- Attivare il toggle A cambia il metadata SPID pubblicato → richiede ri-validazione AgID (stesso avviso già mostrato per eIDAS, riusare lo stesso pattern `window.confirm()`).
- Il valore `Purpose` costruito è sempre la costante `"PG"` — nessun input esterno finisce raw nell'XML SAML.
- `config-api/.coverage` è binario tracciato in git — non modificarlo/committarlo dopo run locale con `--cov` (`git checkout -- config-api/.coverage` prima di committare).
- Merge solo squash (`gh pr merge --squash --delete-branch`), mai push diretto su `main` — sempre branch + PR.
- Test satosa/plugins richiedono build immagine Docker (vedi `CLAUDE.md` sezione "Test satosa/plugins/") tranne per funzioni pure isolate (pattern `test_redact_pii_xml_*`), che sono unit test normali senza Docker.

---

### Task 1: Modello `legal_entity_enabled` + migrazione

**Files:**
- Modify: `config-api/app/models/settings.py` (aggiungi campo dopo `eidas_environment`, riga 27)
- Create: `config-api/alembic/versions/013_legal_entity_settings.py`
- Test: `config-api/tests/test_satosa_config_generator.py` (verifica indiretta tramite fixture `full_db` — vedi Task 2)

**Interfaces:**
- Produces: `EnteSettings.legal_entity_enabled: bool` (default `False`), letto da Task 2 (`satosa_config_generator.py`) e Task 3 (route WebUI).

- [ ] **Step 1: Aggiungi il campo al modello**

In `config-api/app/models/settings.py`, dopo la riga `eidas_environment`:

```python
    legal_entity_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 2: Crea la migrazione**

Crea `config-api/alembic/versions/013_legal_entity_settings.py`:

```python
"""add legal_entity_enabled to ente_settings

Revision ID: 013
Revises: 012
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='ente_settings'"
    ))}
    if "legal_entity_enabled" not in existing:
        op.add_column("ente_settings", sa.Column("legal_entity_enabled", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    op.drop_column("ente_settings", "legal_entity_enabled")
```

- [ ] **Step 3: Verifica che i test esistenti passino ancora**

Run: `cd config-api && python -m pytest tests/test_satosa_config_generator.py -v`
Expected: PASS (14/14, il nuovo campo ha default `False` quindi non altera i test esistenti)

- [ ] **Step 4: Commit**

```bash
git add config-api/app/models/settings.py config-api/alembic/versions/013_legal_entity_settings.py
git commit -m "feat(settings): aggiunge campo legal_entity_enabled a EnteSettings"
```

---

### Task 2: `optional_attributes` nel metadata SP quando abilitato

**Files:**
- Modify: `config-api/app/satosa_config_generator.py:279` (funzione `_spid_backend_yaml`, blocco `sp_config["service"]["sp"]`)
- Test: `config-api/tests/test_satosa_config_generator.py`

**Interfaces:**
- Consumes: `EnteSettings.legal_entity_enabled` (Task 1)
- Produces: quando `True`, `sp_config["service"]["sp"]["optional_attributes"]` contiene `["companyName", "registeredOffice", "ivaCode"]` — letto da pysaml2 (`entity_descriptor()` in `spidsaml2.py:__create_metadata`, upstream, non modificato) per popolare `AttributeConsumingService[0].requested_attribute` nel metadata SP pubblicato.

- [ ] **Step 1: Scrivi il test che fallisce**

Aggiungi a `config-api/tests/test_satosa_config_generator.py`, dopo `test_spid_backend_yaml_has_idp_metadata`:

```python
async def test_spid_backend_yaml_no_optional_attributes_by_default(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    spid = yaml.safe_load((tmp_path / "spid_backend.yaml").read_text())
    assert "optional_attributes" not in spid["config"]["sp_config"]["service"]["sp"]


async def test_spid_backend_yaml_optional_attributes_when_legal_entity_enabled(full_db, tmp_path, monkeypatch):
    from app.models import EnteSettings
    s = (await full_db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one()
    s.legal_entity_enabled = True
    await full_db.commit()

    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    spid = yaml.safe_load((tmp_path / "spid_backend.yaml").read_text())
    optional = spid["config"]["sp_config"]["service"]["sp"]["optional_attributes"]
    assert optional == ["companyName", "registeredOffice", "ivaCode"]
```

Aggiungi l'import mancante in cima al file se non presente:

```python
from sqlalchemy import select
```

- [ ] **Step 2: Esegui i test per verificare che falliscano**

Run: `cd config-api && python -m pytest tests/test_satosa_config_generator.py -k optional_attributes -v`
Expected: FAIL su `test_spid_backend_yaml_optional_attributes_when_legal_entity_enabled` (KeyError `optional_attributes` assente)

- [ ] **Step 3: Implementa**

In `config-api/app/satosa_config_generator.py`, riga 279, sostituisci:

```python
                "required_attributes": ["spidCode", "name", "familyName", "fiscalNumber", "email"],
```

con:

```python
                "required_attributes": ["spidCode", "name", "familyName", "fiscalNumber", "email"],
                **({"optional_attributes": ["companyName", "registeredOffice", "ivaCode"]}
                   if getattr(settings, "legal_entity_enabled", False) is True
                   else {}),
```

- [ ] **Step 4: Esegui i test per verificare che passino**

Run: `cd config-api && python -m pytest tests/test_satosa_config_generator.py -v`
Expected: PASS (16/16)

- [ ] **Step 5: Commit**

```bash
git add config-api/app/satosa_config_generator.py config-api/tests/test_satosa_config_generator.py
git commit -m "feat(satosa-config): aggiunge optional_attributes azienda al metadata SP quando legal_entity_enabled"
```

---

### Task 3: Pannello impostazioni WebUI

**Files:**
- Create: `config-api/app/routes/legal_entity.py`
- Create: `config-api/app/templates/legal_entity/config.html.j2`
- Modify: `config-api/app/main.py:22` (import), `config-api/app/main.py:229` (include_router)
- Modify: `config-api/app/templates/base.html.j2` (nav link, dopo la voce eIDAS, riga 58)
- Test: `config-api/tests/test_legal_entity.py`

**Interfaces:**
- Consumes: `EnteSettings.legal_entity_enabled` (Task 1)
- Produces: route `GET /admin/legal-entity` (pagina stato), `POST /admin/legal-entity/toggle` (form: `legal_entity_enabled` checkbox, `confirmed` hidden) — nessuna interfaccia consumata da altri task.

- [ ] **Step 1: Scrivi il test che fallisce**

Crea `config-api/tests/test_legal_entity.py`:

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
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-legal-entity")
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


async def test_legal_entity_config_page_loads(auth_client, db_session):
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
    ))
    await db_session.commit()

    response = await auth_client.get("/admin/legal-entity")
    assert response.status_code == 200
    assert "Persona giuridica" in response.text


async def test_legal_entity_enable_flow(auth_client, db_session):
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
        legal_entity_enabled=False,
    ))
    await db_session.commit()

    response = await auth_client.post(
        "/admin/legal-entity/toggle",
        data={"legal_entity_enabled": "yes", "confirmed": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/admin/legal-entity?saved=1" in response.headers["location"]

    s = (await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one()
    assert s.legal_entity_enabled is True


async def test_legal_entity_disable_flow(auth_client, db_session):
    db_session.add(EnteSettings(
        id=1, org_display_name="Test Ente", org_name="Test Ente",
        org_url="https://test.it", proxy_hostname="sso.test.it",
        ipa_code="TEST", contact_email="test@test.it", contact_phone="+39",
        org_city="Pescara",
        legal_entity_enabled=True,
    ))
    await db_session.commit()

    response = await auth_client.post(
        "/admin/legal-entity/toggle",
        data={"confirmed": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    s = (await db_session.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one()
    assert s.legal_entity_enabled is False
```

- [ ] **Step 2: Esegui i test per verificare che falliscano**

Run: `cd config-api && python -m pytest tests/test_legal_entity.py -v`
Expected: FAIL (404, route non esiste)

- [ ] **Step 3: Crea la route**

Crea `config-api/app/routes/legal_entity.py`:

```python
import asyncio
import os
import xml.etree.ElementTree as ET
import httpx

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.jinja_templates import templates
from app.models import EnteSettings
from app.satosa_generator import generate_and_write
from app.satosa_reload import reload_satosa

router = APIRouter()


def _auth_check(request: Request):
    return request.session.get("user")


async def check_company_attributes() -> dict:
    """Verifica se il metadata SP pubblicato dichiara gli attributi
    opzionali azienda (companyName) nell'AttributeConsumingService index 0."""
    satosa_url = os.environ.get("SATOSA_INTERNAL_URL", "http://satosa:8080")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{satosa_url}/spidSaml2/metadata")
        if resp.status_code != 200:
            return {"valid": False, "error": f"HTTP {resp.status_code} dal server SATOSA"}

        root = ET.fromstring(resp.content)
        namespaces = {
            'md': 'urn:oasis:names:tc:SAML:2.0:metadata',
            'saml2': 'urn:oasis:names:tc:SAML:2.0:assertion',
        }
        acs0 = root.find('.//md:AttributeConsumingService[@index="0"]', namespaces)
        has_company = False
        if acs0 is not None:
            attr_names = [
                a.attrib.get('Name')
                for a in acs0.findall('md:RequestedAttribute', namespaces)
            ]
            has_company = 'companyName' in attr_names
        return {"valid": True, "has_company_attributes": has_company}
    except Exception as e:
        return {"valid": False, "error": f"Errore di connessione a SATOSA: {str(e)}"}


@router.get("/legal-entity", response_class=HTMLResponse)
async def legal_entity_config_page(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    s = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()

    saved = request.query_params.get("saved") == "1"
    metadata_status = None if saved else await check_company_attributes()

    return templates.TemplateResponse(
        request,
        "legal_entity/config.html.j2",
        {
            "s": s,
            "saved": saved,
            "metadata_status": metadata_status,
        },
    )


@router.post("/legal-entity/toggle")
async def legal_entity_toggle(
    request: Request,
    confirmed: str = Form(default=""),
    legal_entity_enabled: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    s = (await db.execute(select(EnteSettings).where(EnteSettings.id == 1))).scalar_one_or_none()
    if s is None:
        return RedirectResponse("/admin/legal-entity", status_code=302)

    enable = legal_entity_enabled in ("yes", "on", "true", "1")

    if enable and confirmed != "yes":
        return RedirectResponse("/admin/legal-entity?warning=1", status_code=302)

    s.legal_entity_enabled = enable
    await db.commit()

    try:
        await generate_and_write(db)
        await asyncio.to_thread(reload_satosa)
    except Exception:
        pass

    return RedirectResponse("/admin/legal-entity?saved=1", status_code=302)
```

- [ ] **Step 4: Crea il template**

Crea `config-api/app/templates/legal_entity/config.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}Persona giuridica — PA SSO Proxy{% endblock %}
{% block page_title %}Persona giuridica{% endblock %}

{% block content %}
<div style="max-width:720px;">
  {% if saved %}
  <div class="a-alert a-alert-success" style="margin-bottom:16px;">Configurazione aggiornata. SATOSA ricaricato.</div>
  {% endif %}

  <div class="a-card" style="margin-bottom:14px;">
    <div class="a-card-header">
      Accesso SPID persona giuridica
      {% if s and s.legal_entity_enabled %}
      <span class="a-badge a-badge-success">abilitato</span>
      {% else %}
      <span class="a-badge a-badge-neutral">disabilitato</span>
      {% endif %}
    </div>
    <div class="a-card-body">
      <p style="font-size:13px;margin-bottom:20px;color:var(--fg-muted);">
        Permette l'autenticazione SPID Tipo 4 ("uso professionale per la persona giuridica")
        per i client OIDC che richiedono esplicitamente lo scope <code>legal_entity</code>.
        Aggiunge gli attributi azienda (ragione sociale, sede legale, codice fiscale/P.IVA)
        al metadata SP pubblicato.
      </p>

      <form method="post" action="/admin/legal-entity/toggle" id="legal-entity-form" onsubmit="return handleSubmit(event)">
        <input type="hidden" name="confirmed" id="legal-entity-confirmed" value="no">

        <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;">
          <label class="a-toggle">
            <input type="checkbox" name="legal_entity_enabled" id="legal-entity-enabled" value="yes" {% if s and s.legal_entity_enabled %}checked{% endif %}>
            <span class="a-toggle-slider"></span>
          </label>
          <span style="font-weight:600;font-size:14px;color:var(--fg-1);user-select:none;">Abilita accesso persona giuridica</span>
        </div>

        <div style="margin-top:24px;">
          <button type="submit" class="a-btn a-btn-primary">Salva configurazione</button>
        </div>
      </form>
    </div>
  </div>

  <div class="a-card" style="margin-bottom:14px;">
    <div class="a-card-header">Stato Metadata SAML (attributi azienda)</div>
    <div class="a-card-body">
      {% if metadata_status %}
        {% if metadata_status.valid %}
          {% if metadata_status.has_company_attributes %}
            <span class="a-badge a-badge-success">Attributi azienda dichiarati</span>
          {% else %}
            <span class="a-badge a-badge-neutral">Non dichiarati</span>
          {% endif %}
          {% if s and s.legal_entity_enabled and not metadata_status.has_company_attributes %}
            <div class="a-alert a-alert-warning" style="margin-top:14px;">
              <strong>Attenzione:</strong> l'accesso persona giuridica e' abilitato ma il metadata pubblicato non contiene ancora gli attributi azienda. Verifica che SATOSA sia stato ricaricato correttamente.
            </div>
          {% endif %}
        {% else %}
          <div class="a-alert a-alert-danger"><strong>Impossibile verificare lo stato del metadata:</strong> {{ metadata_status.error }}</div>
        {% endif %}
      {% else %}
        <div class="a-muted" style="font-size:12px;">Verifica in corso...</div>
      {% endif %}
    </div>
  </div>
</div>

<script>
const initialEnabled = {% if s and s.legal_entity_enabled %}true{% else %}false{% endif %};

function handleSubmit(event) {
  var isEnabled = document.getElementById("legal-entity-enabled").checked;
  var confirmedInput = document.getElementById("legal-entity-confirmed");

  if (isEnabled && !initialEnabled) {
    var ok = window.confirm(
      "Abilitare l'accesso SPID persona giuridica?\n\n" +
      "Questo modifica il metadata SP pubblicato (nuovi attributi opzionali azienda) " +
      "e richiede ri-validazione presso AgID."
    );
    if (!ok) {
      event.preventDefault();
      return false;
    }
    confirmedInput.value = "yes";
  } else if (!isEnabled && initialEnabled) {
    var ok = window.confirm("Disabilitare l'accesso SPID persona giuridica?");
    if (!ok) {
      event.preventDefault();
      return false;
    }
    confirmedInput.value = "yes";
  } else {
    confirmedInput.value = "yes";
  }
  return true;
}
</script>
{% endblock %}
```

- [ ] **Step 5: Registra la route in `main.py`**

In `config-api/app/main.py`, riga 22, modifica l'import:

```python
from app.routes import dashboard, clients, idps, settings, certs, cie, eidas, legal_entity, test_client, backup, access_log, internal, placeholders, verifica
```

Dopo la riga 229 (`app.include_router(eidas.router, prefix="/admin")`), aggiungi:

```python
app.include_router(legal_entity.router, prefix="/admin")
```

- [ ] **Step 6: Aggiungi il link in navigazione**

In `config-api/app/templates/base.html.j2`, dopo il blocco eIDAS (riga 58, dopo `</a>`):

```html
    <a href="/admin/legal-entity" class="a-nav-item {% if request.url.path.startswith('/admin/legal-entity') %}active{% endif %}">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
      Persona giuridica
    </a>
```

- [ ] **Step 7: Esegui i test per verificare che passino**

Run: `cd config-api && python -m pytest tests/test_legal_entity.py -v`
Expected: PASS (3/3)

- [ ] **Step 8: Esegui l'intera suite per assicurarti di non aver rotto nulla**

Run: `cd config-api && python -m pytest -q`
Expected: PASS (tutti i test, incluso il conteggio precedente + i nuovi)

- [ ] **Step 9: Commit**

```bash
git add config-api/app/routes/legal_entity.py config-api/app/templates/legal_entity/config.html.j2 config-api/app/main.py config-api/app/templates/base.html.j2 config-api/tests/test_legal_entity.py
git commit -m "feat(webui): aggiunge pannello impostazioni per accesso SPID persona giuridica"
```

---

### Task 4: Opt-in scope `legal_entity` per client OIDC

**Files:**
- Modify: `config-api/app/templates/clients/form.html.j2:25`
- Test: `config-api/tests/test_clients.py` (verifica file esistente prima di aggiungere — se non esiste, crea `config-api/tests/test_clients_scopes.py`)

**Interfaces:**
- Produces: client con `legal_entity` in `allowed_scopes` — consumato da Task 5 (`_legal_entity_requested()` in `spidsaml2.py`, che legge lo `scope` dalla query `/authorize`, non direttamente da `allowed_scopes`; questo task garantisce solo che il client POSSA dichiarare lo scope in WebUI e che venga salvato).

- [ ] **Step 1: Verifica se esiste già un test sui client OIDC**

Run: `ls config-api/tests/ | grep -i client`

Se esiste `test_clients.py`, aggiungi il test lì; altrimenti crea `config-api/tests/test_clients_scopes.py` con il fixture `auth_client` (stesso pattern di Task 3, copialo identico).

- [ ] **Step 2: Scrivi il test che fallisce**

```python
async def test_client_form_shows_legal_entity_scope_option(auth_client):
    response = await auth_client.get("/admin/clients/new")
    assert response.status_code == 200
    assert 'value="legal_entity"' in response.text


async def test_client_create_with_legal_entity_scope(auth_client, db_session):
    from sqlalchemy import select
    from app.models import OIDCClient

    response = await auth_client.post(
        "/admin/clients/new",
        data={
            "name": "App Aziende",
            "redirect_uris": "https://app.test.it/callback",
            "scopes": ["openid", "profile", "legal_entity"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    client = (await db_session.execute(select(OIDCClient).where(OIDCClient.name == "App Aziende"))).scalar_one()
    assert "legal_entity" in client.allowed_scopes
```

- [ ] **Step 3: Esegui i test per verificare che falliscano**

Run: `cd config-api && python -m pytest tests/test_clients_scopes.py -v` (o il file che hai scelto)
Expected: FAIL su `test_client_form_shows_legal_entity_scope_option` (stringa assente)

- [ ] **Step 4: Implementa**

In `config-api/app/templates/clients/form.html.j2`, riga 25, sostituisci:

```jinja
        {% for scope in ['openid', 'profile', 'email'] %}
```

con:

```jinja
        {% for scope in ['openid', 'profile', 'email', 'legal_entity'] %}
```

- [ ] **Step 5: Esegui i test per verificare che passino**

Run: `cd config-api && python -m pytest tests/test_clients_scopes.py -v`
Expected: PASS (2/2)

- [ ] **Step 6: Commit**

```bash
git add config-api/app/templates/clients/form.html.j2 config-api/tests/test_clients_scopes.py
git commit -m "feat(clients): aggiunge scope legal_entity opzionale per client OIDC"
```

---

### Task 5: Wiring `Purpose=PG` in `spidsaml2.py`

**Files:**
- Modify: `satosa/plugins/spidsaml2.py` (aggiungi import `urllib.parse` se assente, due funzioni pure a livello modulo, integrazione in `authn_request`)
- Test: `satosa/tests/test_spidsaml2.py`

**Interfaces:**
- Consumes: nessuna dipendenza diretta dagli altri task (funziona indipendentemente da Task 1-4, ma è inutile senza Task 4 che permette ai client di dichiarare lo scope).
- Produces: `_legal_entity_requested(context) -> bool`, `_build_purpose_extension(purpose: str) -> saml2.samlp.Extensions` — funzioni a livello modulo in `backends/spidsaml2.py`, usate solo internamente da `authn_request`.

- [ ] **Step 1: Verifica import esistenti**

Run: `grep -n "^import\|^from" satosa/plugins/spidsaml2.py | head -25`

Se `import urllib.parse` non è già presente (il codice esistente alla riga 422 fa `import urllib.parse` inline dentro la funzione — verificalo), aggiungilo in cima al file con gli altri import, riga 4 (dopo `import re`):

```python
import urllib.parse
```

- [ ] **Step 2: Scrivi i test che falliscono**

Aggiungi a `satosa/tests/test_spidsaml2.py`, dopo l'ultimo test esistente:

```python
class _FakeContext:
    def __init__(self, state):
        self.state = state


def test_legal_entity_requested_true_when_scope_present():
    ctx = _FakeContext({"OIDC": {"oidc_request": "client_id=x&scope=openid+profile+legal_entity&state=y"}})
    assert spidsaml2._legal_entity_requested(ctx) is True


def test_legal_entity_requested_false_when_scope_absent():
    ctx = _FakeContext({"OIDC": {"oidc_request": "client_id=x&scope=openid+profile&state=y"}})
    assert spidsaml2._legal_entity_requested(ctx) is False


def test_legal_entity_requested_false_when_no_oidc_request():
    ctx = _FakeContext({"OIDC": {"oidc_request": None}})
    assert spidsaml2._legal_entity_requested(ctx) is False


def test_legal_entity_requested_false_when_state_has_no_oidc_key():
    ctx = _FakeContext({"some_other_key": {"foo": "bar"}})
    assert spidsaml2._legal_entity_requested(ctx) is False


def test_build_purpose_extension_produces_expected_xml():
    ext = spidsaml2._build_purpose_extension("PG")
    xml = ext.to_string().decode("utf-8") if isinstance(ext.to_string(), bytes) else ext.to_string()
    assert 'https://spid.gov.it/saml-extensions' in xml
    assert '<spid:Purpose' in xml or ':Purpose' in xml
    assert '>PG<' in xml
```

- [ ] **Step 3: Esegui i test per verificare che falliscano**

Run: `cd satosa && python -m pytest tests/test_spidsaml2.py -v -k "legal_entity or purpose_extension"`
Expected: FAIL con `AttributeError: module 'backends.spidsaml2' has no attribute '_legal_entity_requested'`

Nota: questo test richiede l'ambiente satosa (pysaml2 dal fork) — se `import backends.spidsaml2` fallisce localmente per moduli mancanti, segui `CLAUDE.md` sezione "Test satosa/plugins/" per eseguirlo dentro il container Docker:
```bash
docker build -t satosa-test -f satosa/Dockerfile satosa/
docker run --entrypoint sh satosa-test -c "cd /satosa_proxy && PYTHONPATH=/satosa_proxy python -m pytest /path/to/test_spidsaml2.py -v -k legal_entity"
```

- [ ] **Step 4: Implementa le funzioni pure**

In `satosa/plugins/spidsaml2.py`, subito dopo `SPID_ANOMALIES = {...}` (dopo la riga 105, prima di `_TROUBLESHOOT_MSG`), aggiungi:

```python
def _legal_entity_requested(context) -> bool:
    """True se la richiesta OIDC originale include lo scope 'legal_entity'."""
    for v in context.state.values():
        if isinstance(v, dict) and "oidc_request" in v:
            oidc_request = v["oidc_request"]
            if not oidc_request:
                return False
            try:
                params = urllib.parse.parse_qs(oidc_request)
            except Exception as e:
                logger.warning(f"Failed to parse oidc_request query params: {e}")
                return False
            scopes = params.get("scope", [""])[0].split()
            return "legal_entity" in scopes
    return False


def _build_purpose_extension(purpose: str) -> "saml2.samlp.Extensions":
    """Costruisce <samlp:Extensions><spid:Purpose>PURPOSE</spid:Purpose></samlp:Extensions>
    come da Avviso AgID n.18 v.2 (identita' Tipo 3/4 uso professionale)."""
    ext = saml2.ExtensionElement(
        "Purpose", namespace="https://spid.gov.it/saml-extensions", text=purpose
    )
    return saml2.samlp.Extensions(extension_elements=[ext])
```

- [ ] **Step 5: Esegui i test per verificare che passino**

Run: `cd satosa && python -m pytest tests/test_spidsaml2.py -v -k "legal_entity or purpose_extension"`
Expected: PASS (5/5). Se `test_build_purpose_extension_produces_expected_xml` fallisce sul nome dell'attributo/metodo di serializzazione, ispeziona `saml2.samlp.Extensions` con `python -c "from saml2 import samlp; help(samlp.Extensions)"` dentro il container e correggi la funzione di conseguenza (unico punto del design con margine di incertezza sull'API esatta pysaml2, come segnalato nello spec).

- [ ] **Step 6: Integra in `authn_request`**

In `satosa/plugins/spidsaml2.py`, riga 462, subito dopo:

```python
            authn_req.requested_authn_context = req_authn_context
```

aggiungi:

```python
            if _legal_entity_requested(context):
                authn_req.extensions = _build_purpose_extension("PG")
```

- [ ] **Step 7: Esegui l'intera suite satosa per assicurarti di non aver rotto nulla**

Run: `cd satosa && python -m pytest tests/ -v` (o dentro il container come da Step 3 se l'import fallisce localmente)
Expected: PASS (tutti i test esistenti + i 5 nuovi)

- [ ] **Step 8: Commit**

```bash
git add satosa/plugins/spidsaml2.py satosa/tests/test_spidsaml2.py
git commit -m "feat(spidsaml2): aggiunge estensione SAML Purpose=PG per login persona giuridica"
```

---

## Note per l'esecutore

- I Task 1-4 (config-api) sono eseguibili e testabili in sequenza con `pytest` locale, nessun requisito Docker.
- Il Task 5 (satosa/plugins) potrebbe richiedere il build dell'immagine Docker per eseguire i test, se l'ambiente locale non ha il fork pysaml2/SATOSA installato (`pip show satosa` per verificare) — vedi `CLAUDE.md` sezione "Test satosa/plugins/" per i comandi esatti, incluso `MSYS_NO_PATHCONV=1` su Windows/Git Bash.
- Dopo tutti i task: aprire branch + PR (mai push diretto su `main`), attendere CI verde (inclusi `Build satosa` e `Analyze (python)`), poi squash-merge.
- Comunicare all'operatore ente che, una volta abilitato il toggle (Task 3) in produzione, serve ri-validazione del metadata presso AgID — non automatizzabile da questo sistema.
