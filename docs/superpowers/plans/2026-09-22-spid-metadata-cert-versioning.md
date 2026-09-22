# Storico certificati SPID e versioning metadata SPID/eIDAS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere non distruttive la rotazione del certificato SPID e la modifica del metadata SP SPID/eIDAS, storicizzando entrambi e permettendo di riattivare/esporre versioni precedenti; aggiungere upload manuale di metadata.

**Architecture:** `config-api` guadagna una colonna `is_active` su `SpidCert` (selezione esplicita invece di "ultimo per data") e una nuova tabella `spid_metadata_version` che storicizza ogni XML di metadata generato da SATOSA (via snapshot POST fire-and-forget, stesso pattern di `access_log_reporter`) o caricato manualmente. Esporre una versione non corrente scrive un file di override su `/satosa-conf/`; `spidsaml2.py::_metadata_endpoint` lo serve al posto del metadata generato dal vivo se presente.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (config-api), pysaml2/SATOSA custom backend `satosa/plugins/spidsaml2.py`, `urllib.request` stdlib per la POST fire-and-forget lato SATOSA.

**Spec:** `docs/superpowers/specs/2026-09-22-spid-metadata-cert-versioning-design.md`

## Global Constraints

- Un solo `SpidCert.is_active=True` alla volta; invariante mantenuta applicativamente (nessun vincolo DB), stesso pattern di `is_exposed`/`is_validated` su `spid_metadata_version`.
- Nessuna riconferma password aggiuntiva per il download della chiave privata: la sessione admin (`_auth_check`) è già il perimetro di sicurezza esistente.
- Snapshot metadata: fire-and-forget, errori non bloccanti (mai far fallire l'avvio/reload di SATOSA per un config-api irraggiungibile) — stesso principio di `access_log_reporter.py`.
- Warning "cert non corrisponde" in fase di esposizione: **non blocca** l'azione, solo segnala.
- Nessuna retention automatica dello storico in questo piano (YAGNI, fuori scope spec).
- CIE OIDC entity configuration è esplicitamente fuori scope.

---

## File Structure

**Componente A — storico certificati:**
- Modify: `config-api/app/models/cert.py` — colonna `is_active`
- Create: `config-api/alembic/versions/014_spid_cert_is_active.py`
- Modify: `config-api/app/routes/certs.py` — history, download, activate, delete; `generate` aggiorna `is_active`
- Modify: `config-api/app/routes/idps.py` — selezione cert per `is_active`
- Modify: `config-api/app/templates/certs/status.html.j2` → contenuto sostituito con storico (stesso file, nuovo scopo)
- Modify: `config-api/app/templates/idps/list.html.j2` — link "Storico certificati"
- Modify: `config-api/tests/test_certs.py` — aggiorna test esistenti + nuovi

**Componente B — versioning metadata:**
- Create: `config-api/app/models/metadata_version.py` — `SpidMetadataVersion`
- Modify: `config-api/app/models/__init__.py` — export
- Create: `config-api/alembic/versions/015_spid_metadata_version.py`
- Modify: `config-api/app/routes/internal.py` — endpoint snapshot
- Create: `config-api/app/routes/metadata.py` — history/expose/validate/upload/download/delete
- Create: `config-api/app/templates/metadata/history.html.j2`
- Modify: `config-api/app/main.py` — registra router
- Modify: `config-api/app/templates/base.html.j2` — voce nav "Metadata SPID"
- Create: `config-api/tests/test_metadata_version.py`
- Modify: `satosa/plugins/spidsaml2.py` — funzioni pure `_report_metadata_snapshot` / `_read_metadata_override`, wiring in `__init__`/`_metadata_endpoint`
- Modify: `satosa/tests/test_spidsaml2.py` — test delle due funzioni pure

---

### Task 1: `SpidCert.is_active` — modello e migrazione

**Files:**
- Modify: `config-api/app/models/cert.py`
- Create: `config-api/alembic/versions/014_spid_cert_is_active.py`
- Test: `config-api/tests/test_certs.py`

**Interfaces:**
- Produces: `SpidCert.is_active: bool` (default `False`), usato da Task 2/3/4.

- [ ] **Step 1: Scrivi il test che verifica il default della colonna**

In `config-api/tests/test_certs.py`, aggiungi in fondo al file:

```python
async def test_spid_cert_is_active_defaults_false(db_session):
    cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=sso.test.it",
    )
    db_session.add(cert)
    await db_session.commit()
    await db_session.refresh(cert)
    assert cert.is_active is False
```

- [ ] **Step 2: Esegui il test, verifica che fallisca**

Run: `cd config-api && python -m pytest tests/test_certs.py::test_spid_cert_is_active_defaults_false -v`
Expected: FAIL — `TypeError: 'is_active' is an invalid keyword argument` o `AttributeError` (colonna non esiste ancora).

- [ ] **Step 3: Aggiungi la colonna al modello**

In `config-api/app/models/cert.py`, aggiungi l'import `Boolean` e la colonna:

```python
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
```

(sostituisce la riga import esistente, aggiungendo `Boolean`), poi dopo `id: Mapped[int] = mapped_column(Integer, primary_key=True)`:

```python
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
```

- [ ] **Step 4: Esegui il test, verifica che passi**

Run: `cd config-api && python -m pytest tests/test_certs.py::test_spid_cert_is_active_defaults_false -v`
Expected: PASS

- [ ] **Step 5: Scrivi la migrazione Alembic**

Crea `config-api/alembic/versions/014_spid_cert_is_active.py`:

```python
"""add is_active to spid_cert, backfill from latest row

Revision ID: 014
Revises: 013
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing = {row[0] for row in conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='spid_cert'"
    ))}
    if "is_active" not in existing:
        op.add_column("spid_cert", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"))
    conn.execute(sa.text(
        "UPDATE spid_cert SET is_active = true "
        "WHERE id = (SELECT id FROM spid_cert ORDER BY created_at DESC LIMIT 1)"
    ))


def downgrade():
    op.drop_column("spid_cert", "is_active")
```

- [ ] **Step 6: Verifica la migrazione su DB locale (se stack Docker attivo)**

Run: `docker compose exec config-api alembic upgrade head` (skip se lo stack non è in esecuzione — verrà comunque eseguita al prossimo `docker compose up`).
Expected: `Running upgrade 013 -> 014` senza errori.

- [ ] **Step 7: Commit**

```bash
git add config-api/app/models/cert.py config-api/alembic/versions/014_spid_cert_is_active.py config-api/tests/test_certs.py
git commit -m "feat(certs): aggiunge SpidCert.is_active con backfill migrazione

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: selezione certificato per `is_active` in `idps.py`

**Files:**
- Modify: `config-api/app/routes/idps.py`
- Test: `config-api/tests/test_idps.py` (o file equivalente esistente — verifica con `ls config-api/tests/ | grep idp`)

**Interfaces:**
- Consumes: `SpidCert.is_active` (Task 1).

- [ ] **Step 1: Scrivi il test che verifica la selezione del cert attivo**

Trova il file di test esistente per `idps.py` (`grep -rl "admin/idps" config-api/tests/`) e aggiungi:

```python
async def test_idps_list_shows_active_cert_not_latest(auth_client, db_session):
    from app.models import SpidCert
    old = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nold\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nold\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=old.test.it",
        is_active=True,
    )
    db_session.add(old)
    await db_session.commit()
    new = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nnew\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nnew\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=new.test.it",
        is_active=False,
    )
    db_session.add(new)
    await db_session.commit()

    response = await auth_client.get("/admin/idps")
    assert response.status_code == 200
    assert "CN=old.test.it" in response.text
    assert "CN=new.test.it" not in response.text
```

(Aggiungi `from datetime import datetime, timezone` in cima al file se non già presente.)

- [ ] **Step 2: Esegui il test, verifica che fallisca**

Run: `cd config-api && python -m pytest tests/test_idps.py::test_idps_list_shows_active_cert_not_latest -v`
Expected: FAIL — mostra `CN=new.test.it` (selezionato per `created_at` invece che per `is_active`).

- [ ] **Step 3: Aggiorna la query in `idps.py`**

In `config-api/app/routes/idps.py:151`, sostituisci:

```python
    cert_result = await db.execute(select(SpidCert).order_by(SpidCert.created_at.desc()).limit(1))
```

con:

```python
    cert_result = await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))
```

- [ ] **Step 4: Esegui il test, verifica che passi**

Run: `cd config-api && python -m pytest tests/test_idps.py::test_idps_list_shows_active_cert_not_latest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config-api/app/routes/idps.py config-api/tests/test_idps.py
git commit -m "fix(idps): seleziona certificato attivo per is_active invece che per data

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: storico certificati — route history/activate/download

**Files:**
- Modify: `config-api/app/routes/certs.py`
- Test: `config-api/tests/test_certs.py`

**Interfaces:**
- Consumes: `SpidCert.is_active` (Task 1), `write_spid_cert(cert)` (`app/spid_cert_writer.py`, esistente), `generate_and_write(db)` (`app/satosa_generator.py`, esistente).
- Produces: `GET /admin/certs` (200, non più redirect), `GET /admin/certs/{id}/download/cert`, `GET /admin/certs/{id}/download/key`, `POST /admin/certs/{id}/activate` — usati da Task 4 (template) e verificati stand-alone qui.

- [ ] **Step 1: Aggiorna il test esistente che si aspetta il redirect**

In `config-api/tests/test_certs.py`, sostituisci:

```python
async def test_certs_status_no_cert(auth_client):
    response = await auth_client.get("/admin/certs", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/idps" in response.headers["location"]
```

con:

```python
async def test_certs_history_no_certs(auth_client):
    response = await auth_client.get("/admin/certs")
    assert response.status_code == 200
    assert "Nessun certificato" in response.text
```

- [ ] **Step 2: Aggiungi i test per activate e download (falliranno tutti — endpoint non esistono)**

Aggiungi in fondo a `config-api/tests/test_certs.py`:

```python
async def _add_cert(db_session, subject_dn, is_active, cert_pem="cert", key_pem="key"):
    from app.models import SpidCert
    cert = SpidCert(
        certificate_pem=f"-----BEGIN CERTIFICATE-----\n{cert_pem}\n-----END CERTIFICATE-----",
        private_key_pem=f"-----BEGIN PRIVATE KEY-----\n{key_pem}\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn=subject_dn,
        is_active=is_active,
    )
    db_session.add(cert)
    await db_session.commit()
    await db_session.refresh(cert)
    return cert


async def test_certs_history_lists_all(auth_client, db_session):
    await _add_cert(db_session, "CN=old.test.it", is_active=False)
    await _add_cert(db_session, "CN=new.test.it", is_active=True)
    response = await auth_client.get("/admin/certs")
    assert response.status_code == 200
    assert "CN=old.test.it" in response.text
    assert "CN=new.test.it" in response.text


async def test_certs_download_cert_pem(auth_client, db_session):
    cert = await _add_cert(db_session, "CN=test.it", is_active=True, cert_pem="mycertdata")
    response = await auth_client.get(f"/admin/certs/{cert.id}/download/cert")
    assert response.status_code == 200
    assert "mycertdata" in response.text
    assert response.headers["content-type"].startswith("application/x-pem-file")


async def test_certs_download_key_pem(auth_client, db_session):
    cert = await _add_cert(db_session, "CN=test.it", is_active=True, key_pem="mykeydata")
    response = await auth_client.get(f"/admin/certs/{cert.id}/download/key")
    assert response.status_code == 200
    assert "mykeydata" in response.text


async def test_certs_activate_switches_active_flag(auth_client, db_session):
    from app.models import SpidCert
    from sqlalchemy import select
    old = await _add_cert(db_session, "CN=old.test.it", is_active=True)
    new = await _add_cert(db_session, "CN=new.test.it", is_active=False)

    with patch("app.routes.certs.write_spid_cert"), patch(
        "app.routes.certs.generate_and_write", new=AsyncMock()
    ):
        response = await auth_client.post(f"/admin/certs/{new.id}/activate", follow_redirects=False)
    assert response.status_code == 303

    await db_session.refresh(old)
    await db_session.refresh(new)
    assert old.is_active is False
    assert new.is_active is True
```

Aggiungi in cima al file gli import mancanti: `from unittest.mock import AsyncMock, patch` (se non già presente — il file ha già `from unittest.mock import patch`, estendilo ad `AsyncMock`).

- [ ] **Step 3: Esegui i test, verifica che falliscano**

Run: `cd config-api && python -m pytest tests/test_certs.py -v`
Expected: FAIL su tutti i nuovi test (404/405 — route non esistono ancora), oltre a `test_certs_history_no_certs` che fallisce (redirect invece di 200).

- [ ] **Step 4: Riscrivi `certs.py`**

Sostituisci il contenuto di `config-api/app/routes/certs.py`:

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from app.jinja_templates import templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnteSettings, SpidCert
from app.spid_cert import generate_spid_cert
from app.spid_cert_writer import write_spid_cert
from app.satosa_generator import generate_and_write

from urllib.parse import quote

router = APIRouter()


def _auth_check(request: Request) -> bool:
    return request.session.get("user") is not None


@router.get("/certs", response_class=HTMLResponse)
async def certs_history(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).order_by(SpidCert.created_at.desc()))
    certs = result.scalars().all()
    return templates.TemplateResponse(
        request,
        "certs/status.html.j2",
        {"certs": certs, "now": datetime.now(timezone.utc)},
    )


@router.get("/certs/{cert_id}/download/cert")
async def certs_download_cert(cert_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).where(SpidCert.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404)
    return PlainTextResponse(
        cert.certificate_pem,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="spid_sp_cert_{cert_id}.pem"'},
    )


@router.get("/certs/{cert_id}/download/key")
async def certs_download_key(cert_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).where(SpidCert.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404)
    return PlainTextResponse(
        cert.private_key_pem,
        media_type="application/x-pem-file",
        headers={"Content-Disposition": f'attachment; filename="spid_sp_key_{cert_id}.pem"'},
    )


@router.post("/certs/{cert_id}/activate")
async def certs_activate(cert_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).where(SpidCert.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404)

    all_certs = await db.execute(select(SpidCert))
    for c in all_certs.scalars().all():
        c.is_active = c.id == cert_id
    await db.commit()

    import asyncio
    try:
        await asyncio.to_thread(write_spid_cert, cert)
        await generate_and_write(db)
    except Exception:
        pass
    return RedirectResponse("/admin/certs", status_code=303)


@router.post("/certs/{cert_id}/delete")
async def certs_delete(cert_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(SpidCert).where(SpidCert.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404)
    if cert.is_active:
        return RedirectResponse(
            f"/admin/certs?cert_error={quote('Impossibile eliminare il certificato attivo.')}",
            status_code=303,
        )
    await db.delete(cert)
    await db.commit()
    return RedirectResponse("/admin/certs", status_code=303)


@router.post("/certs/generate")
async def certs_generate(request: Request, db: AsyncSession = Depends(get_db)):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    s = result.scalar_one_or_none()

    redirect_to = request.query_params.get("redirect_to", "/admin/idps")

    missing = not s or not all([s.proxy_hostname, s.org_name, s.ipa_code, s.org_city])
    if missing:
        err_msg = "Configura prima le impostazioni ente (proxy_hostname, org_name, ipa_code, org_city)."
        return RedirectResponse(f"{redirect_to}?cert_error={quote(err_msg)}", status_code=303)
    try:
        cert_obj = generate_spid_cert(s)
    except ValueError as exc:
        return RedirectResponse(f"{redirect_to}?cert_error={quote(str(exc))}", status_code=303)

    existing = await db.execute(select(SpidCert))
    for c in existing.scalars().all():
        c.is_active = False
    cert_obj.is_active = True
    db.add(cert_obj)
    await db.commit()

    import asyncio
    try:
        await asyncio.to_thread(write_spid_cert, cert_obj)
        await generate_and_write(db)
    except Exception:
        pass
    return RedirectResponse(redirect_to, status_code=303)
```

(Nota: `write_spid_cert` e `generate_and_write` erano importati localmente dentro `certs_generate` nel file originale — ora sono import di modulo in cima, così `patch("app.routes.certs.write_spid_cert")` nel test funziona.)

- [ ] **Step 5: Esegui i test, verifica che passino**

Run: `cd config-api && python -m pytest tests/test_certs.py -v`
Expected: PASS su tutti (il template `certs/status.html.j2` esiste ancora nella sua forma vecchia — verrà riscritto al Task 4; se `TemplateResponse` fallisce per variabili mancanti, è atteso finché il Task 4 non aggiorna il template — se necessario correggilo già qui in modo minimale per far passare i test di questo task, es. rendendo il template tollerante a `certs` assente).

- [ ] **Step 6: Commit**

```bash
git add config-api/app/routes/certs.py config-api/tests/test_certs.py
git commit -m "feat(certs): storico certificati, download, attivazione, eliminazione

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: template storico certificati

**Files:**
- Modify: `config-api/app/templates/certs/status.html.j2`
- Modify: `config-api/app/templates/idps/list.html.j2`

**Interfaces:**
- Consumes: contesto `{certs: list[SpidCert], now: datetime}` da Task 3.

- [ ] **Step 1: Riscrivi il template come storico**

Sostituisci il contenuto di `config-api/app/templates/certs/status.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}Storico certificati SPID — PA SSO Proxy{% endblock %}
{% block page_title %}Storico certificati SPID{% endblock %}

{% block content %}
<div style="max-width:900px;">
  {% if cert_error %}<div class="a-alert a-alert-danger">{{ cert_error }}</div>{% endif %}

  {% if not certs %}
  <div class="a-alert a-alert-warning">Nessun certificato SPID configurato. Genera il certificato dalla pagina Provider di Identità.</div>
  {% else %}
  <table class="a-table">
    <thead>
      <tr>
        <th>Subject DN</th>
        <th>Generato il</th>
        <th>Scadenza</th>
        <th>Stato</th>
        <th>Azioni</th>
      </tr>
    </thead>
    <tbody>
      {% for cert in certs %}
      <tr>
        <td class="a-mono" style="font-size:12px;">{{ cert.subject_dn }}</td>
        <td>{{ cert.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
        <td>{{ cert.not_valid_after.strftime('%Y-%m-%d') }}</td>
        <td>
          {% if cert.is_active %}<span class="a-badge a-badge-success">Attivo</span>{% endif %}
        </td>
        <td>
          {% if not cert.is_active %}
          <form method="post" action="/admin/certs/{{ cert.id }}/activate" style="display:inline;" onsubmit="return confirm('Attivare questo certificato? Il metadata SPID esposto dinamicamente cambierà.');">
            <button type="submit" class="a-btn a-btn-secondary a-btn-sm">Attiva</button>
          </form>
          {% endif %}
          <a href="/admin/certs/{{ cert.id }}/download/cert" class="a-btn a-btn-secondary a-btn-sm">Scarica cert.</a>
          <a href="/admin/certs/{{ cert.id }}/download/key" class="a-btn a-btn-secondary a-btn-sm" onclick="return confirm('Stai per scaricare la chiave privata. Continuare?');">Scarica chiave</a>
          {% if not cert.is_active %}
          <form method="post" action="/admin/certs/{{ cert.id }}/delete" style="display:inline;" onsubmit="return confirm('Eliminare definitivamente questo certificato?');">
            <button type="submit" class="a-btn a-btn-danger a-btn-sm">Elimina</button>
          </form>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 2: Aggiungi link dalla pagina IdP**

In `config-api/app/templates/idps/list.html.j2`, dopo il blocco del form `/admin/certs/generate` (dopo la riga con `Rigenera certificato` o `Genera certificato`, entrambi i rami `{% if cert %}...{% else %}...{% endif %}`), aggiungi subito prima del rispettivo `{% endif %}` di chiusura del blocco cert (fuori da entrambi i rami, quindi dopo il secondo `{% endif %}` a chiusura di `{% if cert %}`):

```jinja
      <a href="/admin/certs" class="a-link" style="font-size:13px;">Storico certificati &rarr;</a>
```

- [ ] **Step 3: Verifica manuale**

Run: `cd config-api && python -m pytest tests/test_certs.py tests/test_idps.py -v`
Expected: PASS (nessuna regressione — i test di Task 2/3 già coprono il rendering).

- [ ] **Step 4: Commit**

```bash
git add config-api/app/templates/certs/status.html.j2 config-api/app/templates/idps/list.html.j2
git commit -m "feat(certs): template storico certificati con export/attiva/elimina

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: `SpidMetadataVersion` — modello e migrazione

**Files:**
- Create: `config-api/app/models/metadata_version.py`
- Modify: `config-api/app/models/__init__.py`
- Create: `config-api/alembic/versions/015_spid_metadata_version.py`
- Test: `config-api/tests/test_metadata_version.py`

**Interfaces:**
- Produces: `SpidMetadataVersion(id, source, xml_content, content_hash, cert_id, is_exposed, is_validated, label, created_at)` — usato da Task 6/7/8/9.

- [ ] **Step 1: Scrivi il test del modello**

Crea `config-api/tests/test_metadata_version.py`:

```python
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.database import get_db
from app.models import SpidCert, SpidMetadataVersion


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-metadata-version")
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


async def test_spid_metadata_version_defaults(db_session):
    row = SpidMetadataVersion(
        source="generated",
        xml_content="<EntityDescriptor/>",
        content_hash="abc123",
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    assert row.is_exposed is False
    assert row.is_validated is False
    assert row.cert_id is None
```

- [ ] **Step 2: Esegui il test, verifica che fallisca**

Run: `cd config-api && python -m pytest tests/test_metadata_version.py -v`
Expected: FAIL — `ImportError: cannot import name 'SpidMetadataVersion'`.

- [ ] **Step 3: Crea il modello**

Crea `config-api/app/models/metadata_version.py`:

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SpidMetadataVersion(Base):
    __tablename__ = "spid_metadata_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # "generated" | "uploaded"
    xml_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("spid_cert.id", ondelete="SET NULL"), nullable=True)
    is_exposed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: Esporta dal package**

In `config-api/app/models/__init__.py`, aggiungi l'import e aggiorna `__all__`:

```python
from .metadata_version import SpidMetadataVersion
```

E aggiungi `"SpidMetadataVersion"` alla lista `__all__`.

- [ ] **Step 5: Esegui il test, verifica che passi**

Run: `cd config-api && python -m pytest tests/test_metadata_version.py -v`
Expected: PASS

- [ ] **Step 6: Scrivi la migrazione Alembic**

Crea `config-api/alembic/versions/015_spid_metadata_version.py`:

```python
"""create spid_metadata_version table

Revision ID: 015
Revises: 014
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    existing_tables = {row[0] for row in conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    ))}
    if "spid_metadata_version" in existing_tables:
        return
    op.create_table(
        "spid_metadata_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("xml_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("cert_id", sa.Integer(), sa.ForeignKey("spid_cert.id", ondelete="SET NULL"), nullable=True),
        sa.Column("is_exposed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_validated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("label", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_spid_metadata_version_content_hash", "spid_metadata_version", ["content_hash"])


def downgrade():
    op.drop_index("ix_spid_metadata_version_content_hash", table_name="spid_metadata_version")
    op.drop_table("spid_metadata_version")
```

- [ ] **Step 7: Verifica la migrazione su DB locale (se stack Docker attivo)**

Run: `docker compose exec config-api alembic upgrade head` (skip se lo stack non è in esecuzione).
Expected: `Running upgrade 014 -> 015` senza errori.

- [ ] **Step 8: Commit**

```bash
git add config-api/app/models/metadata_version.py config-api/app/models/__init__.py config-api/alembic/versions/015_spid_metadata_version.py config-api/tests/test_metadata_version.py
git commit -m "feat(metadata): aggiunge modello SpidMetadataVersion e migrazione

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: endpoint interno snapshot metadata

**Files:**
- Modify: `config-api/app/routes/internal.py`
- Test: `config-api/tests/test_internal.py`

**Interfaces:**
- Consumes: `SpidMetadataVersion` (Task 5), `SpidCert.is_active` (Task 1).
- Produces: `POST /internal/spid-metadata-snapshot` — chiamato da Task 11 (`spidsaml2.py`).

- [ ] **Step 1: Scrivi i test dell'endpoint**

Crea `config-api/tests/test_internal.py`:

```python
import hashlib

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.database import get_db
from app.models import SpidCert, SpidMetadataVersion


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SATOSA_CONF_DIR", "/tmp/satosa-test-internal")
    monkeypatch.setenv("SATOSA_CONTAINER_NAME", "test-satosa")


@pytest_asyncio.fixture
async def client(db_session, app_env):
    from app.main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_snapshot_creates_row_with_active_cert_id(client, db_session):
    cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nc\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nk\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=test.it",
        is_active=True,
    )
    db_session.add(cert)
    await db_session.commit()
    await db_session.refresh(cert)

    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    assert response.status_code == 200

    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "generated"
    assert rows[0].cert_id == cert.id
    assert rows[0].content_hash == hashlib.sha256(b"<A/>").hexdigest()


async def test_snapshot_first_row_is_exposed_by_default(client, db_session):
    response = await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    assert response.status_code == 200
    result = await db_session.execute(select(SpidMetadataVersion))
    row = result.scalar_one()
    assert row.is_exposed is True


async def test_snapshot_dedupes_identical_content(client, db_session):
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 1


async def test_snapshot_new_content_creates_second_row_not_exposed(client, db_session):
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<A/>"})
    await client.post("/internal/spid-metadata-snapshot", json={"xml_content": "<B/>"})
    result = await db_session.execute(
        select(SpidMetadataVersion).order_by(SpidMetadataVersion.created_at)
    )
    rows = result.scalars().all()
    assert len(rows) == 2
    assert rows[1].is_exposed is False
```

- [ ] **Step 2: Esegui i test, verifica che falliscano**

Run: `cd config-api && python -m pytest tests/test_internal.py -v`
Expected: FAIL — `404 Not Found` (route non esiste).

- [ ] **Step 3: Aggiungi l'endpoint a `internal.py`**

In `config-api/app/routes/internal.py`, aggiungi in cima `import hashlib` e `from app.models import SpidCert, SpidMetadataVersion` (estendendo l'import esistente `from app.models import AccessLog`), poi in coda al file:

```python
class MetadataSnapshotEntry(BaseModel):
    xml_content: str


@router.post("/internal/spid-metadata-snapshot")
async def log_metadata_snapshot(entry: MetadataSnapshotEntry, db: AsyncSession = Depends(get_db)):
    try:
        content_hash = hashlib.sha256(entry.xml_content.encode("utf-8")).hexdigest()
        last_result = await db.execute(
            select(SpidMetadataVersion)
            .where(SpidMetadataVersion.source == "generated")
            .order_by(SpidMetadataVersion.created_at.desc())
            .limit(1)
        )
        last_row = last_result.scalar_one_or_none()
        if last_row is None or last_row.content_hash != content_hash:
            cert_result = await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))
            cert = cert_result.scalar_one_or_none()
            row = SpidMetadataVersion(
                source="generated",
                xml_content=entry.xml_content,
                content_hash=content_hash,
                cert_id=cert.id if cert else None,
                is_exposed=last_row is None,
            )
            db.add(row)
            await db.commit()
    except Exception:
        logger.error("Failed to save metadata snapshot", exc_info=True)
    return {"ok": True}
```

Aggiungi anche `from sqlalchemy import select` se non già importato nel file (verifica: il file usa già `select`? Se assente, aggiungilo).

- [ ] **Step 4: Esegui i test, verifica che passino**

Run: `cd config-api && python -m pytest tests/test_internal.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config-api/app/routes/internal.py config-api/tests/test_internal.py
git commit -m "feat(metadata): endpoint interno snapshot metadata con dedupe e cert_id

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: pagina storico metadata (GET) e registrazione router

**Files:**
- Create: `config-api/app/routes/metadata.py`
- Create: `config-api/app/templates/metadata/history.html.j2`
- Modify: `config-api/app/main.py`
- Modify: `config-api/app/templates/base.html.j2`
- Test: `config-api/tests/test_metadata_version.py`

**Interfaces:**
- Consumes: `SpidMetadataVersion` (Task 5).
- Produces: `GET /admin/metadata` — usato/esteso da Task 8/9.

- [ ] **Step 1: Scrivi il test della pagina**

Aggiungi in `config-api/tests/test_metadata_version.py`:

```python
async def test_metadata_history_page_loads_empty(auth_client):
    response = await auth_client.get("/admin/metadata")
    assert response.status_code == 200
    assert "Nessuna versione" in response.text


async def test_metadata_history_page_lists_versions(auth_client, db_session):
    db_session.add(SpidMetadataVersion(
        source="generated", xml_content="<A/>", content_hash="h1", is_exposed=True,
    ))
    await db_session.commit()
    response = await auth_client.get("/admin/metadata")
    assert response.status_code == 200
    assert "generated" in response.text or "Generato" in response.text
```

- [ ] **Step 2: Esegui i test, verifica che falliscano**

Run: `cd config-api && python -m pytest tests/test_metadata_version.py -v`
Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Crea `metadata.py`**

Crea `config-api/app/routes/metadata.py`:

```python
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
```

- [ ] **Step 4: Crea il template**

Crea `config-api/app/templates/metadata/history.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% block title %}Metadata SPID — PA SSO Proxy{% endblock %}
{% block page_title %}Storico metadata SPID/eIDAS{% endblock %}

{% block content %}
<div style="max-width:1000px;">
  {% if error %}<div class="a-alert a-alert-danger">{{ error }}</div>{% endif %}
  {% if warning %}<div class="a-alert a-alert-warning">{{ warning }}</div>{% endif %}

  <form method="post" action="/admin/metadata/upload" enctype="multipart/form-data" style="margin-bottom:20px;">
    <div class="a-form-group">
      <label class="a-label">Carica metadata XML manuale</label>
      <input type="file" name="file" accept=".xml" class="a-input">
    </div>
    <button type="submit" class="a-btn a-btn-secondary">Carica</button>
  </form>

  {% if not versions %}
  <div class="a-alert a-alert-warning">Nessuna versione di metadata storicizzata ancora.</div>
  {% else %}
  <table class="a-table">
    <thead>
      <tr>
        <th>Fonte</th>
        <th>Generato il</th>
        <th>Cert usato</th>
        <th>Hash</th>
        <th>Stato</th>
        <th>Azioni</th>
      </tr>
    </thead>
    <tbody>
      {% for v in versions %}
      <tr>
        <td>{{ "Generato" if v.source == "generated" else "Caricato" }}</td>
        <td>{{ v.created_at.strftime('%Y-%m-%d %H:%M') }}</td>
        <td>
          {% if v.cert_id %}
            #{{ v.cert_id }}{% if v.cert_id != active_cert_id %} <span class="a-badge a-badge-warning">non è il cert attivo</span>{% endif %}
          {% else %}—{% endif %}
        </td>
        <td class="a-mono" style="font-size:11px;">{{ v.content_hash[:12] }}</td>
        <td>
          {% if v.is_exposed %}<span class="a-badge a-badge-success">Esposto</span>{% endif %}
          {% if v.is_validated %}<span class="a-badge a-badge-info">Validato AgID</span>{% endif %}
        </td>
        <td>
          {% if not v.is_exposed %}
          <form method="post" action="/admin/metadata/{{ v.id }}/expose" style="display:inline;" onsubmit="return confirm('Esporre questa versione al posto di quella corrente?');">
            <button type="submit" class="a-btn a-btn-secondary a-btn-sm">Esponi</button>
          </form>
          {% endif %}
          {% if not v.is_validated %}
          <form method="post" action="/admin/metadata/{{ v.id }}/validate" style="display:inline;">
            <button type="submit" class="a-btn a-btn-secondary a-btn-sm">Segna validato</button>
          </form>
          {% endif %}
          <a href="/admin/metadata/{{ v.id }}/download" class="a-btn a-btn-secondary a-btn-sm">Scarica XML</a>
          {% if not v.is_exposed and not v.is_validated %}
          <form method="post" action="/admin/metadata/{{ v.id }}/delete" style="display:inline;" onsubmit="return confirm('Eliminare questa versione?');">
            <button type="submit" class="a-btn a-btn-danger a-btn-sm">Elimina</button>
          </form>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: Registra il router in `main.py`**

In `config-api/app/main.py`, aggiungi `metadata` all'import esistente (riga 22):

```python
from app.routes import dashboard, clients, idps, settings, certs, cie, eidas, legal_entity, test_client, backup, access_log, internal, placeholders, verifica, metadata
```

E aggiungi, vicino a `app.include_router(certs.router, prefix="/admin")`:

```python
app.include_router(metadata.router, prefix="/admin")
```

- [ ] **Step 6: Aggiungi la voce di navigazione**

In `config-api/app/templates/base.html.j2`, dopo la voce `/admin/eidas` (riga ~55-58), aggiungi:

```jinja
    <a href="/admin/metadata" class="a-nav-item {% if request.url.path.startswith('/admin/metadata') %}active{% endif %}">
      Metadata SPID
    </a>
```

- [ ] **Step 7: Esegui i test, verifica che passino**

Run: `cd config-api && python -m pytest tests/test_metadata_version.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add config-api/app/routes/metadata.py config-api/app/templates/metadata/history.html.j2 config-api/app/main.py config-api/app/templates/base.html.j2 config-api/tests/test_metadata_version.py
git commit -m "feat(metadata): pagina storico metadata SPID con upload form

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: esposizione versione (`expose`) con file di override

**Files:**
- Modify: `config-api/app/routes/metadata.py`
- Test: `config-api/tests/test_metadata_version.py`

**Interfaces:**
- Consumes: `SpidMetadataVersion`, `SpidCert.is_active` (Task 1/5).
- Produces: `POST /admin/metadata/{id}/expose`; file `/satosa-conf/spid_sp_metadata_override.xml` (letto da Task 12 in `spidsaml2.py`).

- [ ] **Step 1: Scrivi i test**

Aggiungi in `config-api/tests/test_metadata_version.py`:

```python
import os


async def test_expose_non_latest_writes_override_file(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    latest = SpidMetadataVersion(source="generated", xml_content="<Latest/>", content_hash="h2", is_exposed=True)
    older = SpidMetadataVersion(source="generated", xml_content="<Older/>", content_hash="h1", is_exposed=False)
    db_session.add_all([older, latest])
    await db_session.commit()
    await db_session.refresh(older)

    response = await auth_client.post(f"/admin/metadata/{older.id}/expose", follow_redirects=False)
    assert response.status_code == 303

    override_path = tmp_path / "spid_sp_metadata_override.xml"
    assert override_path.exists()
    assert override_path.read_text() == "<Older/>"

    await db_session.refresh(older)
    await db_session.refresh(latest)
    assert older.is_exposed is True
    assert latest.is_exposed is False


async def test_expose_latest_removes_override_file(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    override_path = tmp_path / "spid_sp_metadata_override.xml"
    override_path.write_text("<Stale/>")

    older = SpidMetadataVersion(source="generated", xml_content="<Older/>", content_hash="h1", is_exposed=True)
    latest = SpidMetadataVersion(source="generated", xml_content="<Latest/>", content_hash="h2", is_exposed=False)
    db_session.add_all([older, latest])
    await db_session.commit()
    await db_session.refresh(latest)

    response = await auth_client.post(f"/admin/metadata/{latest.id}/expose", follow_redirects=False)
    assert response.status_code == 303
    assert not override_path.exists()


async def test_expose_warns_when_cert_mismatch(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    active_cert = SpidCert(
        certificate_pem="-----BEGIN CERTIFICATE-----\nc\n-----END CERTIFICATE-----",
        private_key_pem="-----BEGIN PRIVATE KEY-----\nk\n-----END PRIVATE KEY-----",
        not_valid_after=datetime(2036, 1, 1, tzinfo=timezone.utc),
        subject_dn="CN=active.it",
        is_active=True,
    )
    db_session.add(active_cert)
    await db_session.commit()

    latest = SpidMetadataVersion(source="generated", xml_content="<Latest/>", content_hash="h2", is_exposed=True)
    older = SpidMetadataVersion(source="generated", xml_content="<Older/>", content_hash="h1", is_exposed=False, cert_id=9999)
    db_session.add_all([older, latest])
    await db_session.commit()
    await db_session.refresh(older)

    response = await auth_client.post(f"/admin/metadata/{older.id}/expose", follow_redirects=False)
    assert response.status_code == 303
    assert "warning=" in response.headers["location"]
```

Aggiungi `from datetime import datetime, timezone` in cima al file se non presente.

- [ ] **Step 2: Esegui i test, verifica che falliscano**

Run: `cd config-api && python -m pytest tests/test_metadata_version.py -v`
Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Aggiungi la route in `metadata.py`**

In `config-api/app/routes/metadata.py`, aggiungi in cima `import os` e `from urllib.parse import quote`, poi in coda al file:

```python
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
        .order_by(SpidMetadataVersion.created_at.desc())
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
```

- [ ] **Step 4: Esegui i test, verifica che passino**

Run: `cd config-api && python -m pytest tests/test_metadata_version.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config-api/app/routes/metadata.py config-api/tests/test_metadata_version.py
git commit -m "feat(metadata): esposizione versione con file override e warning coerenza cert

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: validate / upload / download / delete

**Files:**
- Modify: `config-api/app/routes/metadata.py`
- Modify: `config-api/requirements.txt`
- Test: `config-api/tests/test_metadata_version.py`

**Interfaces:**
- Consumes: `SpidMetadataVersion` (Task 5), `_override_path()` (Task 8).
- Produces: `POST /admin/metadata/{id}/validate`, `POST /admin/metadata/upload`, `GET /admin/metadata/{id}/download`, `POST /admin/metadata/{id}/delete`.

**Sicurezza:** il parsing dell'XML caricato dall'admin usa `defusedxml`, non
`xml.etree.ElementTree` stdlib — quest'ultimo è vulnerabile a XXE (external entity) e
billion-laughs anche quando il chiamante è autenticato (difesa in profondità).

- [ ] **Step 1: Scrivi i test**

Aggiungi in `config-api/tests/test_metadata_version.py`:

```python
async def test_validate_switches_flag(auth_client, db_session):
    v1 = SpidMetadataVersion(source="generated", xml_content="<A/>", content_hash="h1", is_validated=True)
    v2 = SpidMetadataVersion(source="generated", xml_content="<B/>", content_hash="h2", is_validated=False)
    db_session.add_all([v1, v2])
    await db_session.commit()
    await db_session.refresh(v2)

    response = await auth_client.post(f"/admin/metadata/{v2.id}/validate", follow_redirects=False)
    assert response.status_code == 303

    await db_session.refresh(v1)
    await db_session.refresh(v2)
    assert v1.is_validated is False
    assert v2.is_validated is True


async def test_upload_valid_xml_creates_uploaded_row(auth_client, db_session):
    xml_bytes = b'<?xml version="1.0"?><md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="https://test.it/metadata"/>'
    response = await auth_client.post(
        "/admin/metadata/upload",
        files={"file": ("metadata.xml", xml_bytes, "text/xml")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" not in response.headers["location"]

    result = await db_session.execute(select(SpidMetadataVersion))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "uploaded"
    assert rows[0].cert_id is None
    assert rows[0].is_exposed is False


async def test_upload_invalid_xml_rejected(auth_client, db_session):
    response = await auth_client.post(
        "/admin/metadata/upload",
        files={"file": ("bad.xml", b"not xml at all", "text/xml")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    result = await db_session.execute(select(SpidMetadataVersion))
    assert result.scalars().all() == []


async def test_download_returns_xml_content(auth_client, db_session):
    v = SpidMetadataVersion(source="generated", xml_content="<Downloadable/>", content_hash="h1")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    response = await auth_client.get(f"/admin/metadata/{v.id}/download")
    assert response.status_code == 200
    assert "<Downloadable/>" in response.text


async def test_delete_blocked_if_exposed(auth_client, db_session):
    v = SpidMetadataVersion(source="generated", xml_content="<A/>", content_hash="h1", is_exposed=True)
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    response = await auth_client.post(f"/admin/metadata/{v.id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert "error=" in response.headers["location"]

    result = await db_session.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == v.id))
    assert result.scalar_one_or_none() is not None


async def test_delete_removes_unexposed_unvalidated_row(auth_client, db_session):
    v = SpidMetadataVersion(source="uploaded", xml_content="<A/>", content_hash="h1")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)

    response = await auth_client.post(f"/admin/metadata/{v.id}/delete", follow_redirects=False)
    assert response.status_code == 303

    result = await db_session.execute(select(SpidMetadataVersion).where(SpidMetadataVersion.id == v.id))
    assert result.scalar_one_or_none() is None
```

- [ ] **Step 2: Esegui i test, verifica che falliscano**

Run: `cd config-api && python -m pytest tests/test_metadata_version.py -v`
Expected: FAIL — `404 Not Found` sulle nuove route.

- [ ] **Step 3: Aggiungi `defusedxml` alle dipendenze**

In `config-api/requirements.txt`, aggiungi in coda:

```
defusedxml==0.7.1
```

Run: `cd config-api && pip install defusedxml==0.7.1` (ambiente locale, per far passare subito i test — l'immagine Docker la installerà al prossimo build via `requirements.txt`).

- [ ] **Step 4: Aggiungi le route in `metadata.py`**

In `config-api/app/routes/metadata.py`, aggiungi in cima `import hashlib`, `from defusedxml import ElementTree` (mai `xml.etree.ElementTree` stdlib — vulnerabile a XXE su input non fidato), `from fastapi import File, UploadFile` (estendi l'import `fastapi` esistente), `from fastapi.responses import PlainTextResponse` (estendi l'import esistente), poi in coda al file:

```python
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
    await db.commit()
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
```

- [ ] **Step 5: Esegui i test, verifica che passino**

Run: `cd config-api && python -m pytest tests/test_metadata_version.py -v`
Expected: PASS

- [ ] **Step 6: Esegui l'intera suite config-api per verificare nessuna regressione**

Run: `cd config-api && python -m pytest -q`
Expected: tutti i test PASS.

- [ ] **Step 7: Commit**

```bash
git add config-api/app/routes/metadata.py config-api/requirements.txt config-api/tests/test_metadata_version.py
git commit -m "feat(metadata): validazione AgID, upload manuale (defusedxml), download, eliminazione

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: `spidsaml2.py` — snapshot POST fire-and-forget

**Files:**
- Modify: `satosa/plugins/spidsaml2.py`
- Test: `satosa/tests/test_spidsaml2.py`

**Interfaces:**
- Consumes: `POST /internal/spid-metadata-snapshot` (Task 6).
- Produces: `_report_metadata_snapshot(xml_text: str) -> None` — funzione pura a livello di modulo, usata da Task 11.

- [ ] **Step 1: Scrivi il test della funzione pura**

Aggiungi in `satosa/tests/test_spidsaml2.py`:

```python
from unittest.mock import MagicMock


def test_report_metadata_snapshot_posts_xml(monkeypatch):
    monkeypatch.setenv("CONFIG_API_INTERNAL_URL", "http://config-api:8000")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["method"] = req.get_method()
        return MagicMock()

    monkeypatch.setattr("backends.spidsaml2.urllib.request.urlopen", fake_urlopen)
    spidsaml2._report_metadata_snapshot("<EntityDescriptor/>")

    assert captured["url"] == "http://config-api:8000/internal/spid-metadata-snapshot"
    assert captured["method"] == "POST"
    assert b"EntityDescriptor" in captured["data"]


def test_report_metadata_snapshot_swallows_errors(monkeypatch):
    def fake_urlopen(req, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr("backends.spidsaml2.urllib.request.urlopen", fake_urlopen)
    spidsaml2._report_metadata_snapshot("<EntityDescriptor/>")  # non deve sollevare
```

- [ ] **Step 2: Esegui il test dentro il container satosa, verifica che fallisca**

Per Windows/Git Bash usa `MSYS_NO_PATHCONV=1` e path assoluto stile `/c/...` (vedi CLAUDE.md).

Run:
```bash
docker build -t satosa-test -f satosa/Dockerfile satosa/
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh satosa-test -c \
  "PYTHONPATH=/satosa_proxy pytest /satosa_proxy/tests/test_spidsaml2.py -v -k report_metadata_snapshot"
```
Expected: FAIL — `AttributeError: module 'backends.spidsaml2' has no attribute '_report_metadata_snapshot'`.

- [ ] **Step 3: Aggiungi la funzione a `spidsaml2.py`**

In `satosa/plugins/spidsaml2.py`, aggiungi in cima agli import:

```python
import inspect
import json
import logging
import os
import re
import urllib.parse
import urllib.request
```

(sostituisce il blocco import esistente aggiungendo `os` e `urllib.request` — `inspect`, `json`, `logging`, `re`, `urllib.parse` restano invariati e vanno mantenuti: `inspect` è già usato altrove nel file, es. `inspect.getframeinfo` in `_metadata_endpoint`/`_metadata_contact_person`).

Dopo la definizione di `_redact_pii_xml` (funzione pura esistente a livello di modulo), aggiungi:

```python
def _report_metadata_snapshot(xml_text):
    """
    Invia in modo fire-and-forget il metadata SP generato a config-api, che lo
    storicizza per permettere rollback non distruttivi. Errori/timeout non devono
    mai bloccare l'inizializzazione del backend.
    """
    config_api_url = os.environ.get("CONFIG_API_INTERNAL_URL", "http://config-api:8000")
    url = f"{config_api_url}/internal/spid-metadata-snapshot"
    try:
        payload = json.dumps({"xml_content": xml_text}).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        logger.warning("Failed to report metadata snapshot to config-api", exc_info=True)
```

- [ ] **Step 4: Esegui il test dentro il container, verifica che passi**

Run (stesso comando dello Step 2).
Expected: PASS

- [ ] **Step 5: Chiama la funzione da `__init__`**

In `satosa/plugins/spidsaml2.py`, dopo la riga:

```python
        self.xmldoc = self.__create_metadata(self.sp.config)
```

aggiungi:

```python
        _report_metadata_snapshot(text_type(self.xmldoc))
```

- [ ] **Step 6: Esegui l'intera suite satosa dentro il container**

Run:
```bash
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh satosa-test -c \
  "PYTHONPATH=/satosa_proxy pytest /satosa_proxy/tests/test_spidsaml2.py -v"
```
Expected: tutti i test PASS (nessuna regressione sui test esistenti `_redact_pii_xml`).

- [ ] **Step 7: Commit**

```bash
git add satosa/plugins/spidsaml2.py satosa/tests/test_spidsaml2.py
git commit -m "feat(spidsaml2): snapshot fire-and-forget del metadata SP a config-api

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: `spidsaml2.py` — servire il file di override

**Files:**
- Modify: `satosa/plugins/spidsaml2.py`
- Test: `satosa/tests/test_spidsaml2.py`

**Interfaces:**
- Consumes: file `/satosa-conf/spid_sp_metadata_override.xml` (scritto da Task 8).
- Produces: `_read_metadata_override() -> Optional[bytes]` — funzione pura, usata da `_metadata_endpoint`.

- [ ] **Step 1: Scrivi il test della funzione pura**

Aggiungi in `satosa/tests/test_spidsaml2.py`:

```python
def test_read_metadata_override_returns_none_if_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    assert spidsaml2._read_metadata_override() is None


def test_read_metadata_override_returns_bytes_if_present(monkeypatch, tmp_path):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    override_path = tmp_path / "spid_sp_metadata_override.xml"
    override_path.write_text("<Overridden/>")
    assert spidsaml2._read_metadata_override() == b"<Overridden/>"
```

- [ ] **Step 2: Esegui il test dentro il container, verifica che fallisca**

Run:
```bash
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh satosa-test -c \
  "PYTHONPATH=/satosa_proxy pytest /satosa_proxy/tests/test_spidsaml2.py -v -k read_metadata_override"
```
Expected: FAIL — `AttributeError: module 'backends.spidsaml2' has no attribute '_read_metadata_override'`.

- [ ] **Step 3: Aggiungi la funzione a `spidsaml2.py`**

Dopo `_report_metadata_snapshot`, aggiungi:

```python
def _read_metadata_override():
    """
    Se un admin ha esposto (rollback) una versione di metadata storicizzata
    diversa da quella corrente, config-api scrive il suo contenuto qui.
    Ritorna None se nessun override è attivo (comportamento dinamico invariato).
    """
    conf_dir = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")
    override_path = os.path.join(conf_dir, "spid_sp_metadata_override.xml")
    if not os.path.exists(override_path):
        return None
    with open(override_path, "rb") as f:
        return f.read()
```

- [ ] **Step 4: Esegui il test, verifica che passi**

Run (stesso comando dello Step 2).
Expected: PASS

- [ ] **Step 5: Usa la funzione in `_metadata_endpoint`**

In `satosa/plugins/spidsaml2.py`, sostituisci il corpo di `_metadata_endpoint`:

```python
    def _metadata_endpoint(self, context):
        logger.debug(
            f"Entering method: {inspect.getframeinfo(inspect.currentframe()).function}. Params[ context: {context}]."
        )
        """
        Endpoint for retrieving the backend metadata
        :type context: satosa.context.Context
        :rtype: satosa.response.Response

        :param context: The current context
        :return: response with metadata
        """
        logger.debug("Sending metadata response")
        override = _read_metadata_override()
        if override is not None:
            return Response(override, content="text/xml; charset=utf8")
        return Response(
            text_type(self.xmldoc).encode("utf-8"), content="text/xml; charset=utf8"
        )
```

- [ ] **Step 6: Esegui l'intera suite satosa dentro il container**

Run:
```bash
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh satosa-test -c \
  "PYTHONPATH=/satosa_proxy pytest /satosa_proxy/tests/test_spidsaml2.py -v"
```
Expected: tutti i test PASS.

- [ ] **Step 7: Verifica end-to-end manuale (se stack Docker attivo)**

Run: `docker compose up -d --build satosa && curl -s http://localhost:8080/spidSaml2/metadata | head -c 200` (o porta esposta configurata) — conferma risposta XML normale (nessun override attivo di default).
Expected: XML `EntityDescriptor` come oggi, nessuna differenza visibile.

- [ ] **Step 8: Commit**

```bash
git add satosa/plugins/spidsaml2.py satosa/tests/test_spidsaml2.py
git commit -m "feat(spidsaml2): serve file di override metadata se presente

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Post-implementazione

- Aggiorna `CLAUDE.md` (sezione "Note implementative importanti") con una nuova sottosezione "Storico certificati e metadata SPID" che descrive: colonna `is_active` su `SpidCert`, tabella `spid_metadata_version`, endpoint interno snapshot, file di override `/satosa-conf/spid_sp_metadata_override.xml` e comportamento fallback. Usa lo skill `claude-md-management:revise-claude-md` a fine implementazione.
- Esegui `cd config-api && python -m pytest -q` (regola memoria "Run tests before commit") prima di aprire la PR finale.
- Apri PR da `feat/spid-metadata-cert-versioning` verso `main`.
