# CIE OIDC Federation Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CIE OIDC Federation 1.0 backend to SATOSA in pa-sso-proxy, fully configurable via config-api WebUI.

**Architecture:** RedisStorage adapter provides ephemeral session state for the CIE OIDC flow; satosa/Dockerfile is rewritten to clone iam-proxy-italia at v3.3 and use uwsgi; the config generator migrates proxy.yaml to BACKEND_MODULES format and conditionally writes cie_oidc_backend.yaml; WebUI gains an OIDC Federation section on the CIE config page.

**Tech Stack:** Python, SQLAlchemy 2.0 async, FastAPI, redis-py, fakeredis (tests), SATOSA/iam-proxy-italia v3.3, uwsgi, Docker Compose, Redis alpine.

---

## File Map

### New files
- `satosa/plugins/redis_storage.py` — RedisStorage session adapter (duck-typed OidcStorage)
- `satosa/plugins/cieoidc-endpoints/` — 7 GovPay endpoint override files (copy from GovPay-Interaction-Layer)
- `satosa/plugins/cieoidc-models/user.py` — GovPay user model override
- `satosa/entrypoint.sh` — uwsgi launcher script for iam-proxy-italia container
- `satosa/tests/test_redis_storage.py` — unit tests with fakeredis
- `satosa/tests/requirements-test.txt` — test deps

### Modified files
- `satosa/Dockerfile` — full rewrite: clone project files, install redis, use uwsgi entrypoint
- `config-api/app/models/cie.py` — add 9 nullable Text columns
- `config-api/app/main.py` — add `_migrate_cie_oidc_columns()` called at lifespan startup
- `config-api/app/satosa_config_generator.py` — BACKEND_MODULES format + `_cie_oidc_backend_yaml()`
- `config-api/app/routes/cie.py` — add 9 Form params + oidc_federation_enabled
- `config-api/app/templates/cie/config.html.j2` — OIDC Federation section
- `config-api/tests/test_satosa_config_generator.py` — replace PLUGIN test, add CIE OIDC tests
- `config-api/tests/test_cie.py` — OIDC federation fields save test
- `docker-compose.yaml` — redis service + REDIS_URL in satosa

---

## Task 1: RedisStorage adapter

**Files:**
- Create: `satosa/plugins/redis_storage.py`
- Create: `satosa/tests/test_redis_storage.py`
- Create: `satosa/tests/requirements-test.txt`

- [ ] **Step 1: Create test requirements**

Create `satosa/tests/requirements-test.txt`:
```
fakeredis>=2.26
pydantic>=2.0
```

- [ ] **Step 2: Write failing tests**

Create `satosa/tests/test_redis_storage.py`:
```python
import sys
import os

import fakeredis
import pytest
from pydantic import BaseModel
from typing import Optional

# Minimal stub matching iam-proxy-italia OidcAuthentication — used when running outside container
class OidcAuthentication(BaseModel):
    id: str
    client_id: str = ""
    state: str = ""
    endpoint: str = ""
    data: Optional[dict] = None
    provider_id: str = ""
    provider_configuration: Optional[dict] = None
    user: Optional[dict] = None
    access_token: Optional[str] = None
    code: Optional[str] = None
    id_token: Optional[str] = None
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    token_type: Optional[str] = None
    expires_in: Optional[int] = None
    revoked: bool = False


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "plugins"))

# Patch the model loader so redis_storage uses the stub above
import importlib
import unittest.mock as mock


def _make_storage():
    with mock.patch.dict("sys.modules", {"backends.cieoidc.models.oidc_auth": mock.MagicMock(OidcAuthentication=OidcAuthentication)}):
        import redis_storage as rs
        importlib.reload(rs)
    storage = rs.RedisStorage(url="redis://localhost", ttl=3600)
    storage._client = fakeredis.FakeRedis()
    storage._model = OidcAuthentication
    return storage


def test_add_and_get_session():
    storage = _make_storage()
    entity = OidcAuthentication(id="abc123", state="state-xyz", client_id="c1")
    storage.add_session(entity)
    result = storage.get_sessions("state-xyz")
    assert len(result) == 1
    assert result[0].id == "abc123"


def test_get_sessions_missing_state_returns_empty():
    storage = _make_storage()
    assert storage.get_sessions("nonexistent") == []


def test_update_session_changes_value():
    storage = _make_storage()
    entity = OidcAuthentication(id="abc123", state="state-xyz", client_id="c1")
    storage.add_session(entity)
    entity.access_token = "tok123"
    storage.update_session(entity)
    result = storage.get_sessions("state-xyz")
    assert result[0].access_token == "tok123"


def test_is_connected_returns_true():
    storage = _make_storage()
    assert storage.is_connected() is True


def test_close_sets_client_none():
    storage = _make_storage()
    storage.close()
    assert storage._client is None
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd satosa/tests
pip install -r requirements-test.txt
pytest test_redis_storage.py -v
```
Expected: `ModuleNotFoundError: No module named 'redis_storage'`

- [ ] **Step 4: Implement RedisStorage**

Create `satosa/plugins/redis_storage.py`:
```python
import redis
from typing import Any


def _load_model():
    try:
        from backends.cieoidc.models.oidc_auth import OidcAuthentication
        return OidcAuthentication
    except ImportError:
        from pydantic import BaseModel
        from typing import Optional

        class _Stub(BaseModel):
            id: str
            client_id: str = ""
            state: str = ""
            endpoint: str = ""
            data: Optional[dict] = None
            provider_id: str = ""
            provider_configuration: Optional[dict] = None
            user: Optional[dict] = None
            access_token: Optional[str] = None
            code: Optional[str] = None
            id_token: Optional[str] = None
            refresh_token: Optional[str] = None
            scope: Optional[str] = None
            token_type: Optional[str] = None
            expires_in: Optional[int] = None
            revoked: bool = False

        return _Stub


class RedisStorage:
    """Duck-typed OidcStorage implementation using Redis for CIE OIDC session state."""

    def __init__(self, url: str, ttl: int = 7200):
        self._url = url
        self._ttl = ttl
        self._client = None
        self._model = None

    def connect(self) -> None:
        self._client = redis.from_url(self._url, decode_responses=False)
        self._model = _load_model()

    def close(self) -> None:
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None

    def is_connected(self) -> bool:
        try:
            return self._client is not None and bool(self._client.ping())
        except Exception:
            return False

    def add_session(self, entity: Any) -> int:
        data = entity.model_dump_json()
        self._client.set(f"cie:sess:{entity.id}", data, ex=self._ttl)
        self._client.set(f"cie:state:{entity.state}", entity.id, ex=self._ttl)
        return 1

    def update_session(self, entity: Any) -> int:
        key = f"cie:sess:{entity.id}"
        ttl = self._client.ttl(key)
        ex = ttl if ttl > 0 else self._ttl
        self._client.set(key, entity.model_dump_json(), ex=ex)
        return 1

    def get_sessions(self, state: str) -> list:
        sid = self._client.get(f"cie:state:{state}")
        if not sid:
            return []
        doc = self._client.get(f"cie:sess:{sid.decode()}")
        if not doc:
            return []
        model = self._model or _load_model()
        return [model.model_validate_json(doc)]
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd satosa/tests
pytest test_redis_storage.py -v
```
Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add satosa/plugins/redis_storage.py satosa/tests/test_redis_storage.py satosa/tests/requirements-test.txt
git commit -m "feat: add RedisStorage adapter for CIE OIDC session state"
```

---

## Task 2: SATOSA plugin files + fixed Dockerfile

**Files:**
- Copy: `satosa/plugins/cieoidc-endpoints/` (7 files from GovPay-Interaction-Layer)
- Copy: `satosa/plugins/cieoidc-models/user.py`
- Create: `satosa/entrypoint.sh`
- Modify: `satosa/Dockerfile` (full rewrite)

- [ ] **Step 1: Create plugin directories and copy GovPay files**

Run from the `pa-sso-proxy` directory (PowerShell):
```powershell
New-Item -ItemType Directory -Force "satosa\plugins\cieoidc-endpoints"
New-Item -ItemType Directory -Force "satosa\plugins\cieoidc-models"

Copy-Item "..\GovPay-Interaction-Layer\auth-proxy\cieoidc-endpoints\*" `
    "satosa\plugins\cieoidc-endpoints\" -Recurse

Copy-Item "..\GovPay-Interaction-Layer\auth-proxy\cieoidc-models\user.py" `
    "satosa\plugins\cieoidc-models\user.py"
```

- [ ] **Step 2: Verify the 7 endpoint files are present**

```powershell
Get-ChildItem "satosa\plugins\cieoidc-endpoints\" -Name
```
Expected — exactly these 7 files:
```
authorization_callback_endpoint.py
authorization_endpoint.py
entity_configuration.py
federation_fetch_endpoint.py
federation_list_endpoint.py
federation_resolve_endpoint.py
federation_trust_mark_status_endpoint.py
```

- [ ] **Step 3: Create entrypoint.sh**

Create `satosa/entrypoint.sh`:
```sh
#!/bin/sh
set -e
. /.venv/bin/activate
PYTHON_VER=$(python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')
exec uwsgi \
    --chdir /satosa_proxy \
    --wsgi-file "/.venv/lib/${PYTHON_VER}/site-packages/satosa/wsgi.py" \
    --callable app \
    --http-socket 0.0.0.0:8080 \
    --workers 2 \
    --timeout 60 \
    --buffer-size 32768
```

- [ ] **Step 4: Rewrite satosa/Dockerfile**

Replace the entire content of `satosa/Dockerfile`:
```dockerfile
FROM ghcr.io/italia/iam-proxy-italia:latest

USER root

# Base image contains only /.venv/ — no project files. Clone them.
# Try apt-get first (Debian-based); if it fails swap for: apk add --no-cache git
RUN apt-get update -qq && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

ARG IAM_PROXY_REF=v3.3
RUN git clone --depth 1 --branch "${IAM_PROXY_REF}" \
        https://github.com/italia/iam-proxy-italia.git /tmp/upstream \
    && cp -r /tmp/upstream/iam-proxy-italia-project/. /satosa_proxy/ \
    && rm -rf /tmp/upstream

# Install redis client inside the venv
RUN . /.venv/bin/activate && pip install redis --quiet

# Override CIE OIDC endpoints and models with GovPay versions
COPY plugins/cieoidc-endpoints/ /satosa_proxy/backends/cieoidc/endpoints/
COPY plugins/cieoidc-models/    /satosa_proxy/backends/cieoidc/models/
COPY plugins/redis_storage.py   /satosa_proxy/backends/cieoidc/storage/impl/redis_storage.py

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
```

**Note:** If `apt-get` fails during build (Alpine-based image), replace the RUN line with:
`RUN apk add --no-cache git`

- [ ] **Step 5: Test the Docker build**

```bash
docker build -t pa-sso-proxy-satosa-test ./satosa
```
Expected: build completes with no errors. If apt-get not found → update to apk.

- [ ] **Step 6: Commit**

```bash
git add satosa/plugins/ satosa/entrypoint.sh satosa/Dockerfile
git commit -m "fix: rewrite satosa Dockerfile — clone iam-proxy-italia v3.3, switch gunicorn→uwsgi"
```

---

## Task 3: CieConfig model + startup DB migration

**Files:**
- Modify: `config-api/app/models/cie.py`
- Modify: `config-api/app/main.py`
- Modify: `config-api/tests/test_cie.py`

- [ ] **Step 1: Write failing test**

Add to `config-api/tests/test_cie.py` (after existing imports):
```python
async def test_cie_config_has_oidc_fields(db_session):
    config = CieConfig(
        id=1,
        saml_metadata_url="https://x",
        oidc_provider_url="https://oidc.provider.it",
        trust_anchor_url="https://trust.anchor.it",
        authority_hint_url="https://authority.hint.it",
        homepage_uri="https://ente.it",
        policy_uri="https://ente.it/privacy",
        logo_uri="https://ente.it/logo.png",
        trust_mark_id="https://registry.cie.gov.it/tm/rp",
        trust_mark="eyJhbGciOiJFUzI1NiJ9.stub",
        oidc_contact_email="admin@ente.it",
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)
    assert config.oidc_provider_url == "https://oidc.provider.it"
    assert config.trust_mark == "eyJhbGciOiJFUzI1NiJ9.stub"
    assert config.oidc_contact_email == "admin@ente.it"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd config-api
pytest tests/test_cie.py::test_cie_config_has_oidc_fields -v
```
Expected: FAIL — `CieConfig` has no attribute `oidc_provider_url`.

- [ ] **Step 3: Add 9 new columns to CieConfig**

In `config-api/app/models/cie.py`, add after the `jwk_core_enc_id` line:
```python
    oidc_provider_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trust_anchor_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    authority_hint_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    homepage_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    policy_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logo_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trust_mark_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trust_mark: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oidc_contact_email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_cie.py::test_cie_config_has_oidc_fields -v
```
Expected: PASS (conftest uses `create_all` so SQLite gets the columns automatically)

- [ ] **Step 5: Add runtime migration to main.py**

In `config-api/app/main.py`, add after the existing imports:
```python
from sqlalchemy import inspect, text
from app.database import engine
```

Add this function before the `lifespan` function:
```python
_CIE_OIDC_COLUMNS = [
    "oidc_provider_url",
    "trust_anchor_url",
    "authority_hint_url",
    "homepage_uri",
    "policy_uri",
    "logo_uri",
    "trust_mark_id",
    "trust_mark",
    "oidc_contact_email",
]


async def _migrate_cie_oidc_columns() -> None:
    """Add CIE OIDC Federation columns to cie_config if not present (idempotent)."""
    async with engine.begin() as conn:
        existing = await conn.run_sync(
            lambda c: {col["name"] for col in inspect(c).get_columns("cie_config")}
        )
        for col in _CIE_OIDC_COLUMNS:
            if col not in existing:
                await conn.execute(text(f"ALTER TABLE cie_config ADD COLUMN {col} TEXT"))
```

Update the `lifespan` function to call the migration first:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _migrate_cie_oidc_columns()
    async with AsyncSessionLocal() as session:
        await seed_spid_idps(session)
        try:
            await generate_and_write(session)
        except Exception:
            pass
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_metadata_watcher, CronTrigger(hour=2, minute=0))
    scheduler.start()
    yield
    scheduler.shutdown()
```

- [ ] **Step 6: Run all CIE tests**

```bash
pytest tests/test_cie.py -v
```
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add config-api/app/models/cie.py config-api/app/main.py config-api/tests/test_cie.py
git commit -m "feat: add 9 CIE OIDC Federation columns + startup ALTER TABLE migration"
```

---

## Task 4: Config generator — BACKEND_MODULES + cie_oidc_backend.yaml

**Files:**
- Modify: `config-api/app/satosa_config_generator.py` (full rewrite)
- Modify: `config-api/tests/test_satosa_config_generator.py`

- [ ] **Step 1: Update tests**

In `config-api/tests/test_satosa_config_generator.py`:

Replace `test_proxy_yaml_has_three_plugins` (lines 46–54) with:
```python
async def test_proxy_yaml_uses_backend_modules_format(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    assert "PLUGIN" not in proxy
    assert "BACKEND_MODULES" in proxy
    assert "FRONTEND_MODULES" in proxy
    assert "/satosa-conf/spid_backend.yaml" in proxy["BACKEND_MODULES"]
    assert "/satosa-conf/cie_saml_backend.yaml" in proxy["BACKEND_MODULES"]
    assert "/satosa-conf/oidc_frontend.yaml" in proxy["FRONTEND_MODULES"]


async def test_cie_oidc_not_in_backend_modules_when_disabled(full_db, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(full_db)
    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    assert "/satosa-conf/cie_oidc_backend.yaml" not in proxy["BACKEND_MODULES"]
    assert not (tmp_path / "cie_oidc_backend.yaml").exists()


async def test_cie_oidc_backend_yaml_generated_when_enabled(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    from app.models import EnteSettings, CieConfig, JwkKey, SpidIdP

    s = EnteSettings(
        id=1, proxy_hostname="proxy.ente.it", org_name="Ente", org_display_name="Ente Test",
        org_url="https://ente.it", ipa_code="P_T", contact_email="e@ente.it",
        contact_phone="+39001", org_city="Roma",
    )
    idp = SpidIdP(alias="spid-aruba", display_name="Aruba", metadata_url="https://aruba/meta", enabled=True)
    fed_key = JwkKey(name="cie-fed", use="federation",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "fed1"},
                     public_jwk={"kty": "EC"})
    sig_key = JwkKey(name="cie-sig", use="sig",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "sig1"},
                     public_jwk={"kty": "EC"})
    enc_key = JwkKey(name="cie-enc", use="enc",
                     private_jwk={"kty": "EC", "crv": "P-256", "kid": "enc1"},
                     public_jwk={"kty": "EC"})
    db_session.add_all([s, idp, fed_key, sig_key, enc_key])
    await db_session.commit()
    await db_session.refresh(fed_key)
    await db_session.refresh(sig_key)
    await db_session.refresh(enc_key)

    cie = CieConfig(
        id=1,
        saml_metadata_url="https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
        client_id="https://proxy.ente.it/CieOidcRp",
        oidc_federation_enabled=True,
        oidc_provider_url="https://preprod.oidc.interno.gov.it",
        trust_anchor_url="https://registry.cie.gov.it",
        authority_hint_url="https://registry.cie.gov.it",
        trust_mark_id="https://registry.cie.gov.it/tm/rp",
        trust_mark="eyJhbGciOiJFUzI1NiJ9.stub.sig",
        oidc_contact_email="admin@ente.it",
        jwk_federation_id=fed_key.id,
        jwk_core_sig_id=sig_key.id,
        jwk_core_enc_id=enc_key.id,
    )
    db_session.add(cie)
    await db_session.commit()

    from app.satosa_config_generator import generate_satosa_config
    await generate_satosa_config(db_session)

    proxy = yaml.safe_load((tmp_path / "proxy.yaml").read_text())
    assert "/satosa-conf/cie_oidc_backend.yaml" in proxy["BACKEND_MODULES"]

    cie_yaml = yaml.safe_load((tmp_path / "cie_oidc_backend.yaml").read_text())
    assert cie_yaml["module"] == "backends.cieoidc.CieOidcBackend"
    assert cie_yaml["config"]["providers"] == ["https://preprod.oidc.interno.gov.it"]
    assert cie_yaml["config"]["jwks"]["federation"] == [{"kty": "EC", "crv": "P-256", "kid": "fed1"}]
    assert "entity_config_endpoint" in cie_yaml["config"]["endpoints"]
    assert "authorization_endpoint" in cie_yaml["config"]["endpoints"]
    assert "authorization_callback_endpoint" in cie_yaml["config"]["endpoints"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd config-api
pytest tests/test_satosa_config_generator.py -v
```
Expected: `test_proxy_yaml_uses_backend_modules_format` FAIL, both `test_cie_oidc_*` FAIL. `test_proxy_yaml_base` still PASS.

- [ ] **Step 3: Rewrite satosa_config_generator.py**

Replace the full content of `config-api/app/satosa_config_generator.py`:

```python
import os
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CieConfig, EnteSettings, JwkKey, SpidIdP

SATOSA_CONF_DIR = os.environ.get("SATOSA_CONF_DIR", "/satosa-conf")
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

_OIDC_FRONTEND_CLASS = "satosa.frontends.openid_connect.OpenIDConnectFrontend"
_SAML_BACKEND_CLASS = "satosa.backends.saml2.SAMLMirrorBackend"


def _proxy_yaml(hostname: str, include_cie_oidc: bool) -> dict:
    backend_modules = [
        "/satosa-conf/spid_backend.yaml",
        "/satosa-conf/cie_saml_backend.yaml",
    ]
    if include_cie_oidc:
        backend_modules.append("/satosa-conf/cie_oidc_backend.yaml")
    return {
        "BASE": f"https://{hostname}",
        "COOKIE_STATE_NAME": "satosa_state",
        "USER_ID_HASH_SALT": os.environ.get("SATOSA_HASH_SALT", "changeme"),
        "CONSENT": {"enable": False},
        "BACKEND_MODULES": backend_modules,
        "FRONTEND_MODULES": ["/satosa-conf/oidc_frontend.yaml"],
    }


def _oidc_frontend_yaml(hostname: str, has_jwks: bool) -> dict:
    config: dict = {
        "issuer": f"https://{hostname}",
        "client_db": {
            "class": "oidcop.client_authn.from_file.ClientAuthnFromFile",
            "kwargs": {"client_file": "/satosa-conf/oidcop_clients.yaml"},
        },
        "authentication": {
            "user": {
                "acr": "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport",
                "class": "oidcop.user_authn.authn_context.UserAuthnContextCritical",
            }
        },
    }
    if has_jwks:
        config["keys"] = {
            "private_path": "/satosa-conf/cie_jwks_private.json",
            "public_path": "/satosa-conf/cie_jwks_public.json",
            "read_only": False,
        }
    return config


def _spid_backend_yaml(hostname: str, enabled_idps: list, cert_path: str, key_path: str) -> dict:
    return {
        "entityid": f"https://{hostname}/spid/metadata",
        "service": {
            "sp": {
                "endpoints": {
                    "single_sign_on_service": [
                        [f"https://{hostname}/spid/sso/redirect",
                         "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"],
                        [f"https://{hostname}/spid/sso/post",
                         "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"],
                    ]
                },
                "want_response_signed": True,
                "authn_requests_signed": True,
                "allow_unsolicited": False,
            }
        },
        "key_file": key_path,
        "cert_file": cert_path,
        "metadata": {"remote": [{"url": idp.metadata_url} for idp in enabled_idps]},
    }


def _cie_saml_backend_yaml(hostname: str, cie_metadata_url: str, cert_path: str, key_path: str) -> dict:
    return {
        "entityid": f"https://{hostname}/cie/saml/metadata",
        "service": {
            "sp": {
                "endpoints": {
                    "single_sign_on_service": [
                        [f"https://{hostname}/cie/saml/sso/redirect",
                         "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"],
                        [f"https://{hostname}/cie/saml/sso/post",
                         "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"],
                    ]
                },
                "want_response_signed": True,
                "authn_requests_signed": True,
                "allow_unsolicited": False,
            }
        },
        "key_file": key_path,
        "cert_file": cert_path,
        "metadata": {"remote": [{"url": cie_metadata_url}]},
    }


def _cie_oidc_backend_yaml(
    hostname: str,
    cie_config: "CieConfig",
    settings: "EnteSettings",
    jwk_federation: dict,
    jwk_core_sig: dict,
    jwk_core_enc: dict,
    redis_url: str,
) -> dict:
    contact_email = cie_config.oidc_contact_email or settings.contact_email
    org_name = settings.org_display_name

    db_config = {
        "redis": {
            "module": "backends.cieoidc.storage.impl.redis_storage",
            "class": "RedisStorage",
            "init_params": {"url": redis_url, "ttl": 7200},
        }
    }
    httpc_params = {"connection": {"ssl": True}, "session": {"timeout": 6}}
    metadata = {
        "federation_entity": {
            "federation_resolve_endpoint": f"https://{hostname}/CieOidcRp/resolve",
            "organization_name": org_name,
            "homepage_uri": cie_config.homepage_uri,
            "policy_uri": cie_config.policy_uri,
            "logo_uri": cie_config.logo_uri,
            "contacts": [contact_email],
        },
        "openid_relying_party": {
            "application_type": "web",
            "client_id": cie_config.client_id,
            "client_name": org_name,
            "organization_name": org_name,
            "client_registration_types": ["automatic"],
            "signed_jwks_uri": f"https://{hostname}/CieOidcRp/openid_relying_party/jwks.jose",
            "jwks": None,
            "contacts": [contact_email],
            "grant_types": ["refresh_token", "authorization_code"],
            "redirect_uris": [f"https://{hostname}/CieOidcRp/oidc/callback"],
            "response_types": ["code"],
            "subject_type": "pairwise",
            "id_token_signed_response_alg": "ES256",
            "userinfo_signed_response_alg": "ES256",
            "userinfo_encrypted_response_alg": "ECDH-ES+A128KW",
            "userinfo_encrypted_response_enc": "A256GCM",
            "token_endpoint_auth_method": "private_key_jwt",
            "scope": "openid email",
            "code_challenge": {"length": 64, "method": "S256"},
            "claim": {
                "id_token": {
                    "sub": {"essential": True},
                    "family_name": {"essential": True},
                    "given_name": {"essential": True},
                },
                "userinfo": {
                    "sub": None,
                    "given_name": None,
                    "family_name": None,
                    "email": {"essential": True},
                    "https://attributes.eid.gov.it/fiscal_number": None,
                },
            },
            "claims": {
                "id_token": {
                    "sub": {"essential": True},
                    "family_name": {"essential": True},
                    "given_name": {"essential": True},
                },
                "userinfo": {
                    "sub": None,
                    "given_name": None,
                    "family_name": None,
                    "email": {"essential": True},
                    "https://attributes.eid.gov.it/fiscal_number": None,
                },
            },
        },
    }

    # Shared endpoint config for federation endpoints that need metadata + jwks
    endpoint_base = {
        "metadata": metadata,
        "jwks_federation": [jwk_federation],
        "jwks_core": [jwk_core_sig, jwk_core_enc],
        "entity_type": "openid_relying_party",
        "entity_configuration_exp": 525600,
        "default_sig_alg": "ES256",
        "authority_hints": [cie_config.authority_hint_url],
    }
    trust_marks = [{"id": cie_config.trust_mark_id, "trust_mark": cie_config.trust_mark}]

    return {
        "module": "backends.cieoidc.CieOidcBackend",
        "name": "CieOidcRp",
        "config": {
            "network": {"httpc_params": httpc_params},
            "storage": db_config,
            "providers": [cie_config.oidc_provider_url],
            "security_operations": {
                "hash": {"default": {"func": "SHA-256"}},
                "sign": {
                    "default": {"alg": "ES256"},
                    "supported": {"alg": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]},
                },
                "encrypt": {
                    "default": {"alg": "ECDH-ES+A128KW", "enc": "A256GCM"},
                    "supported": {
                        "alg": [
                            "RSA-OAEP", "RSA-OAEP-256", "ECDH-ES",
                            "ECDH-ES+A128KW", "ECDH-ES+A192KW", "ECDH-ES+A256KW",
                        ],
                        "enc": [
                            "A128CBC-HS256", "A192CBC-HS384", "A256CBC-HS512",
                            "A128GCM", "A192GCM", "A256GCM",
                        ],
                    },
                },
            },
            "jwks": {
                "federation": [jwk_federation],
                "core": [jwk_core_sig, jwk_core_enc],
            },
            "metadata": metadata,
            "trust_chain": {
                "config": {
                    "cache_ttl": 0,
                    "trust_anchor": [cie_config.trust_anchor_url],
                    "httpc_params": httpc_params,
                }
            },
            "endpoints": {
                "entity_config_endpoint": {
                    "module": "backends.cieoidc.endpoints.entity_configuration",
                    "class": "EntityConfigHandler",
                    "routes": [
                        "/.well-known/openid-federation",
                        "/openid_relying_party/jwks.json",
                        "/openid_relying_party/jwks.jose",
                    ],
                    "config": {**endpoint_base, "trust_marks": trust_marks},
                },
                "federation_resolve_endpoint": {
                    "module": "backends.cieoidc.endpoints.federation_resolve_endpoint",
                    "class": "FederationResolveHandler",
                    "routes": ["/resolve"],
                    "config": {**endpoint_base, "trust_marks": []},
                },
                "federation_fetch_endpoint": {
                    "module": "backends.cieoidc.endpoints.federation_fetch_endpoint",
                    "class": "FederationFetchHandler",
                    "routes": ["/fetch"],
                    "config": {**endpoint_base, "trust_marks": []},
                },
                "federation_trust_mark_status_endpoint": {
                    "module": "backends.cieoidc.endpoints.federation_trust_mark_status_endpoint",
                    "class": "FederationTrustMarkStatusHandler",
                    "routes": ["/trust_mark_status"],
                    "config": {},
                },
                "federation_list_endpoint": {
                    "module": "backends.cieoidc.endpoints.federation_list_endpoint",
                    "class": "FederationListHandler",
                    "routes": ["/list"],
                    "config": {},
                },
                "authorization_endpoint": {
                    "module": "backends.cieoidc.endpoints.authorization_endpoint",
                    "class": "AuthorizationHandler",
                    "routes": ["/oidc/authorization"],
                    "config": {
                        **endpoint_base,
                        "db_config": db_config,
                        "trust_marks": trust_marks,
                        "prompt": "consent",
                    },
                },
                "authorization_callback_endpoint": {
                    "module": "backends.cieoidc.endpoints.authorization_callback_endpoint",
                    "class": "AuthorizationCallBackHandler",
                    "routes": ["/oidc/callback"],
                    "config": {
                        **endpoint_base,
                        "db_config": db_config,
                        "httpc_params": httpc_params,
                        "trust_marks": trust_marks,
                        "default_sign_alg": "ES256",
                        "supported_sign_alg": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
                        "default_enc_alg": "ECDH-ES+A128KW",
                        "default_enc_enc": "A256GCM",
                        "supported_enc_alg": [
                            "RSA-OAEP", "RSA-OAEP-256", "ECDH-ES",
                            "ECDH-ES+A128KW", "ECDH-ES+A192KW", "ECDH-ES+A256KW",
                        ],
                        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                        "grant_type": "authorization_code",
                        "claims": {
                            "sub": ["sub"],
                            "username": [{
                                "func": "backends.cieoidc.utils.helpers.misc.issuer_prefixed_sub",
                                "kwargs": {"sep": "__"},
                            }],
                            "first_name": ["given_name", "given_name"],
                            "last_name": ["family_name", "last_name"],
                            "email": ["email", "email"],
                            "fiscal_number": [
                                "https://attributes.eid.gov.it/fiscal_number",
                                "fiscal_number",
                            ],
                        },
                    },
                },
                "extends_session_endpoint": {
                    "module": "backends.cieoidc.endpoints.extend_session_endpoint",
                    "class": "ExtendSessionHandler",
                    "routes": ["/extend_session"],
                    "config": {
                        **endpoint_base,
                        "httpc_params": httpc_params,
                        "trust_marks": trust_marks,
                        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                        "grant_type": "refresh_token",
                    },
                },
            },
        },
    }


def _write(conf_dir: str, filename: str, data: dict) -> None:
    with open(os.path.join(conf_dir, filename), "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


async def generate_satosa_config(db: AsyncSession) -> None:
    """Generate all SATOSA YAML config files from DB. No-op if proxy_hostname not set."""
    result = await db.execute(select(EnteSettings).where(EnteSettings.id == 1))
    settings = result.scalar_one_or_none()
    if not settings or not settings.proxy_hostname:
        return

    result = await db.execute(select(SpidIdP).where(SpidIdP.enabled == True))
    enabled_idps = list(result.scalars().all())

    result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    cie_config = result.scalar_one_or_none()
    cie_metadata_url = (
        cie_config.saml_metadata_url
        if cie_config
        else "https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata"
    )

    result = await db.execute(select(JwkKey).limit(1))
    has_jwks = result.scalar_one_or_none() is not None

    jwk_federation = None
    jwk_core_sig = None
    jwk_core_enc = None
    if cie_config:
        if cie_config.jwk_federation_id:
            r = await db.execute(select(JwkKey).where(JwkKey.id == cie_config.jwk_federation_id))
            k = r.scalar_one_or_none()
            if k:
                jwk_federation = k.private_jwk
        if cie_config.jwk_core_sig_id:
            r = await db.execute(select(JwkKey).where(JwkKey.id == cie_config.jwk_core_sig_id))
            k = r.scalar_one_or_none()
            if k:
                jwk_core_sig = k.private_jwk
        if cie_config.jwk_core_enc_id:
            r = await db.execute(select(JwkKey).where(JwkKey.id == cie_config.jwk_core_enc_id))
            k = r.scalar_one_or_none()
            if k:
                jwk_core_enc = k.private_jwk

    include_cie_oidc = bool(
        cie_config is not None
        and cie_config.oidc_federation_enabled
        and cie_config.trust_mark
        and cie_config.trust_mark_id
        and cie_config.authority_hint_url
        and cie_config.trust_anchor_url
        and cie_config.client_id
        and cie_config.oidc_provider_url
        and jwk_federation is not None
        and jwk_core_sig is not None
        and jwk_core_enc is not None
    )

    conf_dir = os.environ.get("SATOSA_CONF_DIR", SATOSA_CONF_DIR)
    os.makedirs(conf_dir, exist_ok=True)

    cert_path = "/satosa-conf/spid_sp_cert.pem"
    key_path = "/satosa-conf/spid_sp_key.pem"
    hostname = settings.proxy_hostname
    redis_url = os.environ.get("REDIS_URL", REDIS_URL)

    _write(conf_dir, "proxy.yaml", _proxy_yaml(hostname, include_cie_oidc))
    _write(conf_dir, "oidc_frontend.yaml", _oidc_frontend_yaml(hostname, has_jwks))
    _write(conf_dir, "spid_backend.yaml", _spid_backend_yaml(hostname, enabled_idps, cert_path, key_path))
    _write(conf_dir, "cie_saml_backend.yaml", _cie_saml_backend_yaml(hostname, cie_metadata_url, cert_path, key_path))

    if include_cie_oidc:
        _write(
            conf_dir,
            "cie_oidc_backend.yaml",
            _cie_oidc_backend_yaml(
                hostname, cie_config, settings,
                jwk_federation, jwk_core_sig, jwk_core_enc, redis_url,
            ),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd config-api
pytest tests/test_satosa_config_generator.py -v
```
Expected: all 8 tests PASS (7 old + 3 new, minus 1 replaced = net +2).

- [ ] **Step 5: Run full test suite to verify no regressions**

```bash
pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add config-api/app/satosa_config_generator.py config-api/tests/test_satosa_config_generator.py
git commit -m "feat: proxy.yaml → BACKEND_MODULES format, add _cie_oidc_backend_yaml with 8 endpoints"
```

---

## Task 5: WebUI — CIE OIDC Federation section

**Files:**
- Modify: `config-api/app/routes/cie.py`
- Modify: `config-api/app/templates/cie/config.html.j2`
- Modify: `config-api/tests/test_cie.py`

- [ ] **Step 1: Write failing test**

Add to `config-api/tests/test_cie.py`:
```python
async def test_cie_save_oidc_federation_fields(auth_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("SATOSA_CONF_DIR", str(tmp_path))
    response = await auth_client.post(
        "/admin/cie",
        data={
            "saml_metadata_url": "https://idserver.servizicie.interno.gov.it/idp/shibboleth",
            "entity_id": "",
            "client_id": "https://proxy.ente.it/CieOidcRp",
            "jwk_federation_id": "",
            "jwk_core_sig_id": "",
            "jwk_core_enc_id": "",
            "oidc_federation_enabled": "on",
            "oidc_provider_url": "https://preprod.oidc.interno.gov.it",
            "trust_anchor_url": "https://registry.cie.gov.it",
            "authority_hint_url": "https://registry.cie.gov.it",
            "homepage_uri": "https://ente.it",
            "policy_uri": "",
            "logo_uri": "",
            "trust_mark_id": "https://registry.cie.gov.it/tm/rp",
            "trust_mark": "eyJhbGciOiJFUzI1NiJ9.stub",
            "oidc_contact_email": "admin@ente.it",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    result = await db_session.execute(select(CieConfig).where(CieConfig.id == 1))
    config = result.scalar_one_or_none()
    assert config is not None
    assert config.oidc_federation_enabled is True
    assert config.trust_mark == "eyJhbGciOiJFUzI1NiJ9.stub"
    assert config.trust_mark_id == "https://registry.cie.gov.it/tm/rp"
    assert config.authority_hint_url == "https://registry.cie.gov.it"
    assert config.oidc_contact_email == "admin@ente.it"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd config-api
pytest tests/test_cie.py::test_cie_save_oidc_federation_fields -v
```
Expected: FAIL — POST route ignores new fields.

- [ ] **Step 3: Update routes/cie.py**

Replace `cie_config_post` (the `@router.post("/cie")` function) with:
```python
@router.post("/cie")
async def cie_config_post(
    request: Request,
    saml_metadata_url: str = Form(...),
    entity_id: str = Form(default=""),
    client_id: str = Form(default=""),
    jwk_federation_id: str = Form(default=""),
    jwk_core_sig_id: str = Form(default=""),
    jwk_core_enc_id: str = Form(default=""),
    oidc_federation_enabled: str = Form(default=""),
    oidc_provider_url: str = Form(default=""),
    trust_anchor_url: str = Form(default=""),
    authority_hint_url: str = Form(default=""),
    homepage_uri: str = Form(default=""),
    policy_uri: str = Form(default=""),
    logo_uri: str = Form(default=""),
    trust_mark_id: str = Form(default=""),
    trust_mark: str = Form(default=""),
    oidc_contact_email: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    if not _auth_check(request):
        return RedirectResponse("/admin/login", status_code=302)

    result = await db.execute(select(CieConfig).where(CieConfig.id == 1))
    config = result.scalar_one_or_none()

    if config is None:
        config = CieConfig(id=1)
        db.add(config)

    config.saml_metadata_url = saml_metadata_url
    config.entity_id = entity_id or None
    config.client_id = client_id or None
    config.jwk_federation_id = _parse_int(jwk_federation_id)
    config.jwk_core_sig_id = _parse_int(jwk_core_sig_id)
    config.jwk_core_enc_id = _parse_int(jwk_core_enc_id)
    config.oidc_federation_enabled = oidc_federation_enabled == "on"
    config.oidc_provider_url = oidc_provider_url or None
    config.trust_anchor_url = trust_anchor_url or None
    config.authority_hint_url = authority_hint_url or None
    config.homepage_uri = homepage_uri or None
    config.policy_uri = policy_uri or None
    config.logo_uri = logo_uri or None
    config.trust_mark_id = trust_mark_id or None
    config.trust_mark = trust_mark or None
    config.oidc_contact_email = oidc_contact_email or None

    await db.commit()

    keys = await _get_all_keys(db)
    await _write_jwks_safe(keys)

    return RedirectResponse("/admin/cie", status_code=302)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_cie.py::test_cie_save_oidc_federation_fields -v
```
Expected: PASS

- [ ] **Step 5: Update config.html.j2**

Replace the full content of `config-api/app/templates/cie/config.html.j2`:
```jinja2
{% extends "base.html.j2" %}
{% block title %}Configurazione CIE — PA SSO Proxy{% endblock %}
{% block content %}
<h2>CIE</h2>

<form method="post" action="/admin/cie" class="mb-5">
  <h5 class="mt-3 mb-3">CIE SAML</h5>
  <div class="mb-3">
    <label class="form-label" for="saml_metadata_url">SAML Metadata URL</label>
    <input type="url" class="form-control" id="saml_metadata_url" name="saml_metadata_url"
           value="{{ config.saml_metadata_url if config else 'https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata' }}">
  </div>
  <div class="mb-3">
    <label class="form-label" for="entity_id">Entity ID (SP)</label>
    <input type="text" class="form-control" id="entity_id" name="entity_id"
           value="{{ config.entity_id or '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label" for="client_id">Client ID (CIE OIDC)</label>
    <input type="text" class="form-control" id="client_id" name="client_id"
           value="{{ config.client_id or '' }}">
  </div>
  <div class="mb-3">
    <label class="form-label" for="jwk_federation_id">JWK Federation</label>
    <select class="form-select" id="jwk_federation_id" name="jwk_federation_id">
      <option value="">— nessuna —</option>
      {% for key in jwk_keys %}
      <option value="{{ key.id }}" {% if config and config.jwk_federation_id == key.id %}selected{% endif %}>
        {{ key.name }} ({{ key.use }})
      </option>
      {% endfor %}
    </select>
  </div>
  <div class="mb-3">
    <label class="form-label" for="jwk_core_sig_id">JWK Core Signature</label>
    <select class="form-select" id="jwk_core_sig_id" name="jwk_core_sig_id">
      <option value="">— nessuna —</option>
      {% for key in jwk_keys %}
      <option value="{{ key.id }}" {% if config and config.jwk_core_sig_id == key.id %}selected{% endif %}>
        {{ key.name }} ({{ key.use }})
      </option>
      {% endfor %}
    </select>
  </div>
  <div class="mb-3">
    <label class="form-label" for="jwk_core_enc_id">JWK Core Encryption</label>
    <select class="form-select" id="jwk_core_enc_id" name="jwk_core_enc_id">
      <option value="">— nessuna —</option>
      {% for key in jwk_keys %}
      <option value="{{ key.id }}" {% if config and config.jwk_core_enc_id == key.id %}selected{% endif %}>
        {{ key.name }} ({{ key.use }})
      </option>
      {% endfor %}
    </select>
  </div>

  <hr>
  <h5 class="mt-4 mb-3">CIE OIDC Federation 1.0</h5>

  {% if config and config.oidc_federation_enabled %}
    {% if config.trust_mark and config.trust_mark_id and config.authority_hint_url and config.trust_anchor_url and config.client_id and config.oidc_provider_url %}
      <span class="badge bg-success mb-3">Configurato</span>
    {% else %}
      <span class="badge bg-warning text-dark mb-3">Incompleto — mancano campi obbligatori</span>
    {% endif %}
  {% endif %}

  <div class="mb-3 form-check form-switch">
    <input class="form-check-input" type="checkbox" id="oidc_federation_enabled"
           name="oidc_federation_enabled" value="on"
           {% if config and config.oidc_federation_enabled %}checked{% endif %}
           onchange="document.getElementById('cie-oidc-fields').style.display = this.checked ? '' : 'none'">
    <label class="form-check-label" for="oidc_federation_enabled">Abilita CIE OIDC Federation</label>
  </div>

  <div id="cie-oidc-fields" {% if not (config and config.oidc_federation_enabled) %}style="display:none"{% endif %}>
    <div class="mb-3">
      <label class="form-label" for="oidc_provider_url">Provider URL (CIE OIDC OP)</label>
      <input type="url" class="form-control" id="oidc_provider_url" name="oidc_provider_url"
             placeholder="https://preprod.oidc.interno.gov.it"
             value="{{ config.oidc_provider_url or '' if config else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label" for="trust_anchor_url">Trust Anchor URL (IPZS)</label>
      <input type="url" class="form-control" id="trust_anchor_url" name="trust_anchor_url"
             placeholder="https://registry.cie.gov.it"
             value="{{ config.trust_anchor_url or '' if config else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label" for="authority_hint_url">Authority Hint URL (IPZS)</label>
      <input type="url" class="form-control" id="authority_hint_url" name="authority_hint_url"
             placeholder="https://registry.cie.gov.it"
             value="{{ config.authority_hint_url or '' if config else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label" for="homepage_uri">Homepage URI ente</label>
      <input type="url" class="form-control" id="homepage_uri" name="homepage_uri"
             value="{{ config.homepage_uri or '' if config else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label" for="policy_uri">Policy URI (privacy)</label>
      <input type="url" class="form-control" id="policy_uri" name="policy_uri"
             value="{{ config.policy_uri or '' if config else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label" for="logo_uri">Logo URI</label>
      <input type="url" class="form-control" id="logo_uri" name="logo_uri"
             value="{{ config.logo_uri or '' if config else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label" for="oidc_contact_email">Email contatto OIDC Federation</label>
      <input type="email" class="form-control" id="oidc_contact_email" name="oidc_contact_email"
             value="{{ config.oidc_contact_email or '' if config else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label" for="trust_mark_id">Trust Mark ID (da IPZS)</label>
      <input type="text" class="form-control" id="trust_mark_id" name="trust_mark_id"
             placeholder="https://registry.cie.gov.it/tm/rp"
             value="{{ config.trust_mark_id or '' if config else '' }}">
    </div>
    <div class="mb-3">
      <label class="form-label" for="trust_mark">Trust Mark JWT (da IPZS)</label>
      <textarea class="form-control font-monospace" id="trust_mark" name="trust_mark" rows="4"
                placeholder="eyJhbGciOiJFUzI1NiJ9...">{{ config.trust_mark or '' if config else '' }}</textarea>
      <div class="form-text">JWT rilasciato da IPZS al completamento della registrazione federazione.</div>
    </div>
  </div>

  <button type="submit" class="btn btn-primary">Salva configurazione</button>
</form>

<hr>

<h5 class="mt-4 mb-3">Chiavi JWK</h5>

<div class="mb-3 d-flex gap-2">
  <form method="post" action="/admin/cie/generate-jwk/federation" class="d-inline">
    <button type="submit" class="btn btn-outline-secondary btn-sm">+ Genera Federation</button>
  </form>
  <form method="post" action="/admin/cie/generate-jwk/sig" class="d-inline">
    <button type="submit" class="btn btn-outline-secondary btn-sm">+ Genera Sig</button>
  </form>
  <form method="post" action="/admin/cie/generate-jwk/enc" class="d-inline">
    <button type="submit" class="btn btn-outline-secondary btn-sm">+ Genera Enc</button>
  </form>
</div>

{% if jwk_keys %}
<table class="table table-sm table-hover">
  <thead>
    <tr><th>Name</th><th>Use</th><th>Kid</th><th>Actions</th></tr>
  </thead>
  <tbody>
    {% for key in jwk_keys %}
    <tr>
      <td>{{ key.name }}</td>
      <td><code>{{ key.use }}</code></td>
      <td><small><code>{{ key.public_jwk.get('kid', '—') if key.public_jwk else '—' }}</code></small></td>
      <td>
        <form method="post" action="/admin/cie/delete-jwk/{{ key.id }}" class="d-inline"
              onsubmit="return confirm('Eliminare la chiave {{ key.name }}?')">
          <button type="submit" class="btn btn-sm btn-outline-danger">Elimina</button>
        </form>
      </td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p class="text-muted">Nessuna chiave JWK configurata.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Run all CIE tests**

```bash
pytest tests/test_cie.py -v
```
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add config-api/app/routes/cie.py config-api/app/templates/cie/config.html.j2 config-api/tests/test_cie.py
git commit -m "feat: add CIE OIDC Federation section to WebUI (toggle + 9 fields + status badge)"
```

---

## Task 6: docker-compose.yaml — Redis service

**Files:**
- Modify: `docker-compose.yaml`

- [ ] **Step 1: Add redis service**

In `docker-compose.yaml`, add the `redis` service after the `postgres` block and before `satosa`:
```yaml
  redis:
    image: redis:alpine
    restart: unless-stopped
    networks:
      - proxy-internal
```

- [ ] **Step 2: Update satosa service**

In the `satosa:` block:

Add `REDIS_URL` to environment:
```yaml
      - REDIS_URL=redis://redis:6379/0
```

Add `redis` dependency (after `config-api`):
```yaml
      redis:
        condition: service_started
```

The full updated `satosa:` service block:
```yaml
  satosa:
    build: ./satosa
    restart: unless-stopped
    depends_on:
      config-api:
        condition: service_healthy
      redis:
        condition: service_started
    environment:
      - SATOSA_CONFIG=/satosa-conf/proxy.yaml
      - SATOSA_HASH_SALT=${SATOSA_HASH_SALT:-changeme-generate-random-32chars}
      - REDIS_URL=redis://redis:6379/0
    volumes:
      - proxy_satosa_conf:/satosa-conf
    networks:
      - proxy-internal
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8080/.well-known/openid-configuration || exit 1"]
      interval: 20s
      timeout: 10s
      retries: 10
      start_period: 60s
```

- [ ] **Step 3: Validate compose syntax**

```bash
docker compose config --quiet
```
Expected: no errors

- [ ] **Step 4: Run full config-api test suite one final time**

```bash
cd config-api && pytest tests/ -v
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yaml
git commit -m "feat: add Redis service, wire REDIS_URL env to satosa container"
```

---

## Self-Review

**Spec coverage:**
- RedisStorage duck-typed, TTL 7200, two keys per session → Task 1 ✓
- Dockerfile: clone iam-proxy-italia v3.3, copy overrides, uwsgi entrypoint → Task 2 ✓
- 9 new CieConfig nullable Text columns → Task 3 ✓
- Runtime ALTER TABLE migration (no Alembic — no versions dir in project) → Task 3 ✓
- proxy.yaml → BACKEND_MODULES/FRONTEND_MODULES format → Task 4 ✓
- `_cie_oidc_backend_yaml()` with all 8 endpoints matching GovPay template → Task 4 ✓
- include_cie_oidc gate checks all 9 prerequisites → Task 4 ✓
- WebUI toggle + 9 fields + status badge → Task 5 ✓
- POST handler saves all fields → Task 5 ✓
- Redis service in compose, REDIS_URL in satosa env → Task 6 ✓

**Alg note:** Plan uses ES256/ECDH-ES+A128KW/A256GCM throughout. The approved spec used GovPay's RS256/RSA-OAEP defaults (written before confirming pa-sso-proxy generates EC P-256 keys). ES256 is correct for EC P-256 keys.

**Placeholder scan:** None — all steps have complete code.

**Type consistency:**
- `_cie_oidc_backend_yaml(jwk_federation, jwk_core_sig, jwk_core_enc)` — all `dict` from `k.private_jwk` ✓
- `oidc_federation_enabled = oidc_federation_enabled == "on"` matches HTML `value="on"` ✓
- `endpoint_base` dict spread with `**endpoint_base` used consistently across all 6 federation endpoints ✓
