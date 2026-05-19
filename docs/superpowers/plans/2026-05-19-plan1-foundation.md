# pa-sso-proxy — Plan 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Running Docker Compose stack with postgres, nginx, placeholder satosa, and a functional config-api (login, dashboard, all DB tables migrated).

**Architecture:** FastAPI + SQLAlchemy 2.0 async + Alembic for config-api. SessionMiddleware (Starlette built-in) for WebUI auth. Bootstrap 5 CDN, no build step. Nginx routes `/admin` → config-api, `/` → satosa placeholder.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 + asyncpg, Alembic, Jinja2, pytest + pytest-asyncio + httpx, Docker Compose v2, postgres:16, nginx:alpine.

---

## File Map

```
docker-compose.yaml                         Stack principale
.env.example                                (già presente, non modificare)
nginx/
  conf.d/
    proxy.conf                              Route /admin → config-api, / → satosa
config-api/
  Dockerfile
  requirements.txt
  alembic.ini
  alembic/
    env.py
    versions/
      001_initial_schema.py
  app/
    __init__.py                             (vuoto)
    main.py                                 FastAPI app + middleware + route mounting
    auth.py                                 Login/logout routes + auth dependency
    database.py                             AsyncEngine + AsyncSession + get_db()
    models/
      __init__.py                           (vuoto)
      base.py                               DeclarativeBase
      client.py                             OIDCClient model
      idp.py                                SpidIdP model
      cie.py                                CieConfig model
      settings.py                           EnteSettings model
      key.py                                JwkKey model
      cert.py                               SpidCert model
    routes/
      __init__.py                           (vuoto)
      dashboard.py                          GET /admin/ → dashboard.html.j2
    templates/
      base.html.j2                          Layout Bootstrap 5
      login.html.j2                         Pagina login
      dashboard.html.j2                     Dashboard (status container)
    static/
      css/
        app.css                             Minimal overrides
  tests/
    __init__.py                             (vuoto)
    conftest.py                             AsyncClient fixture + test DB
    test_auth.py                            Login/logout/redirect tests
    test_dashboard.py                       Dashboard requires auth
    test_models.py                          DB models round-trip
```

---

## Task 1: Docker Compose skeleton

**Files:**
- Create: `docker-compose.yaml`

- [ ] **Step 1: Crea `docker-compose.yaml`**

```yaml
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: proxy
      POSTGRES_USER: proxy
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - proxy_db_data:/var/lib/postgresql/data
    networks:
      - proxy-internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U proxy"]
      interval: 10s
      timeout: 5s
      retries: 5

  satosa:
    image: python:3.12-slim
    restart: unless-stopped
    networks:
      - proxy-internal
    command: >
      sh -c "python3 -c 'import time; print(\"satosa placeholder\"); time.sleep(86400)'"
    # Placeholder — sostituito in Plan 5

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
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - proxy-internal
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 15s
      timeout: 5s
      retries: 5

  nginx:
    image: nginx:alpine
    restart: unless-stopped
    depends_on:
      - config-api
      - satosa
    ports:
      - "${PROXY_HOST_PORT:-127.0.0.1:18080}:80"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
    networks:
      - proxy-internal

networks:
  proxy-internal:
    driver: bridge

volumes:
  proxy_db_data:
```

- [ ] **Step 2: Aggiungi `SESSION_SECRET` a `.env.example`**

Apri `.env.example` e aggiungi dopo `ADMIN_PASSWORD`:
```
SESSION_SECRET=genera-una-stringa-random-di-almeno-32-caratteri
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yaml .env.example
git commit -m "feat: docker compose skeleton — 4 container, postgres healthcheck"
```

---

## Task 2: nginx routing

**Files:**
- Create: `nginx/conf.d/proxy.conf`

- [ ] **Step 1: Crea `nginx/conf.d/proxy.conf`**

```nginx
server {
    listen 80;
    server_name _;

    # WebUI admin — solo accesso interno
    location /admin {
        proxy_pass http://config-api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    }

    location /health-admin {
        proxy_pass http://config-api:8000/health;
    }

    # Tutto il resto → satosa
    location / {
        proxy_pass http://satosa:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header X-Forwarded-Host $host;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add nginx/
git commit -m "feat: nginx routing — /admin -> config-api, / -> satosa"
```

---

## Task 3: config-api — requirements e Dockerfile

**Files:**
- Create: `config-api/requirements.txt`
- Create: `config-api/Dockerfile`

- [ ] **Step 1: Crea `config-api/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy[asyncio]==2.0.36
asyncpg==0.30.0
alembic==1.13.3
jinja2==3.1.4
python-multipart==0.0.12
itsdangerous==2.2.0
bcrypt==4.2.0
docker==7.1.0
cryptography==43.0.3
httpx==0.27.2
apscheduler==3.10.4
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
```

- [ ] **Step 2: Crea `config-api/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update -qq && apt-get install -y -qq curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Commit**

```bash
git add config-api/requirements.txt config-api/Dockerfile
git commit -m "feat: config-api dockerfile e requirements"
```

---

## Task 4: DB models

**Files:**
- Create: `config-api/app/models/base.py`
- Create: `config-api/app/models/client.py`
- Create: `config-api/app/models/idp.py`
- Create: `config-api/app/models/cie.py`
- Create: `config-api/app/models/settings.py`
- Create: `config-api/app/models/key.py`
- Create: `config-api/app/models/cert.py`
- Create: `config-api/app/models/__init__.py`
- Test: `config-api/tests/test_models.py`

- [ ] **Step 1: Crea `config-api/app/models/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

- [ ] **Step 2: Crea `config-api/app/models/client.py`**

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class OIDCClient(Base):
    __tablename__ = "oidc_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    client_secret_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    redirect_uris: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    allowed_scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 3: Crea `config-api/app/models/idp.py`**

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SpidIdP(Base):
    __tablename__ = "spid_idps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    metadata_url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_cache: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    last_updated: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Crea `config-api/app/models/key.py`**

```python
from datetime import datetime
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class JwkKey(Base):
    __tablename__ = "jwk_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    use: Mapped[str] = mapped_column(String(16), nullable=False)  # federation | sig | enc
    private_jwk: Mapped[dict] = mapped_column(JSONB, nullable=False)
    public_jwk: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 5: Crea `config-api/app/models/cert.py`**

```python
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class SpidCert(Base):
    __tablename__ = "spid_cert"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    certificate_pem: Mapped[str] = mapped_column(Text, nullable=False)
    private_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    not_valid_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subject_dn: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 6: Crea `config-api/app/models/settings.py`**

```python
from typing import Optional
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class EnteSettings(Base):
    __tablename__ = "ente_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # sempre 1
    org_display_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    org_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    org_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ipa_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    contact_email: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    org_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    proxy_hostname: Mapped[str] = mapped_column(String(256), nullable=False, default="")
```

- [ ] **Step 7: Crea `config-api/app/models/cie.py`**

```python
from typing import Optional
from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class CieConfig(Base):
    __tablename__ = "cie_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # sempre 1
    saml_metadata_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
    )
    oidc_federation_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jwk_federation_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
    jwk_core_sig_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
    jwk_core_enc_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jwk_keys.id"), nullable=True)
```

- [ ] **Step 8: Crea `config-api/app/models/__init__.py`**

```python
from .base import Base
from .client import OIDCClient
from .idp import SpidIdP
from .cie import CieConfig
from .settings import EnteSettings
from .key import JwkKey
from .cert import SpidCert

__all__ = ["Base", "OIDCClient", "SpidIdP", "CieConfig", "EnteSettings", "JwkKey", "SpidCert"]
```

- [ ] **Step 9: Scrivi test failing**

Crea `config-api/tests/test_models.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import OIDCClient, SpidIdP, EnteSettings, JwkKey, SpidCert, CieConfig


@pytest.mark.asyncio
async def test_oidc_client_create(db_session: AsyncSession):
    client = OIDCClient(
        client_id="test-app",
        client_secret_hash="hash",
        name="Test App",
        redirect_uris=["https://app.test/callback"],
        allowed_scopes=["openid", "profile"],
    )
    db_session.add(client)
    await db_session.commit()
    await db_session.refresh(client)
    assert client.id is not None
    assert client.enabled is True


@pytest.mark.asyncio
async def test_spid_idp_create(db_session: AsyncSession):
    idp = SpidIdP(
        alias="spid-aruba",
        display_name="Aruba ID",
        metadata_url="https://loginspid.aruba.it/metadata",
    )
    db_session.add(idp)
    await db_session.commit()
    await db_session.refresh(idp)
    assert idp.enabled is False
    assert idp.metadata_cache is None


@pytest.mark.asyncio
async def test_jwk_key_create(db_session: AsyncSession):
    key = JwkKey(
        name="jwk-federation",
        use="federation",
        private_jwk={"kty": "RSA", "d": "private"},
        public_jwk={"kty": "RSA", "e": "AQAB"},
    )
    db_session.add(key)
    await db_session.commit()
    await db_session.refresh(key)
    assert key.id is not None
    assert key.public_jwk["kty"] == "RSA"
```

- [ ] **Step 10: Crea `config-api/tests/conftest.py`**

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.models import Base

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
```

- [ ] **Step 11: Aggiungi `aiosqlite` a `requirements.txt`** (solo per test)

```
aiosqlite==0.20.0
```

- [ ] **Step 12: Esegui test (devono fallire — modelli non ancora importabili)**

```bash
cd config-api
pip install -r requirements.txt
pytest tests/test_models.py -v
```

Il test fallisce con `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 13: Crea `config-api/app/__init__.py` e tutti i `__init__.py` mancanti**

```bash
touch config-api/app/__init__.py
touch config-api/app/models/__init__.py  # già creato sopra
touch config-api/tests/__init__.py
```

- [ ] **Step 14: Esegui test dal path corretto**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_models.py -v
```

Expected: tutti e 3 i test **PASS**.

- [ ] **Step 15: Commit**

```bash
git add config-api/app/models/ config-api/tests/ config-api/requirements.txt
git commit -m "feat: db models — OIDCClient, SpidIdP, JwkKey, SpidCert, CieConfig, EnteSettings"
```

---

## Task 5: database.py + Alembic

**Files:**
- Create: `config-api/app/database.py`
- Create: `config-api/alembic.ini`
- Create: `config-api/alembic/env.py`
- Create: `config-api/alembic/versions/001_initial_schema.py`

- [ ] **Step 1: Crea `config-api/app/database.py`**

```python
import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 2: Inizializza Alembic**

```bash
cd config-api
alembic init alembic
```

- [ ] **Step 3: Sostituisci `config-api/alembic/env.py`**

```python
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url():
    url = os.environ.get("DATABASE_URL", "")
    # Alembic usa driver sincrono
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("sqlite+aiosqlite://", "sqlite://")


def run_migrations_online():
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
```

- [ ] **Step 4: Imposta `sqlalchemy.url` in `alembic.ini`**

In `config-api/alembic.ini`, riga `sqlalchemy.url`:
```ini
sqlalchemy.url = postgresql://proxy:changeme@localhost:5432/proxy
```
(Il valore viene sovrascritto da `env.py` a runtime — questo è solo un placeholder.)

- [ ] **Step 5: Genera la prima migrazione**

```bash
cd config-api
DATABASE_URL=postgresql+asyncpg://proxy:changeme@localhost:5432/proxy \
  alembic revision --autogenerate -m "initial schema"
```

Oppure scrivi la migrazione manualmente in `config-api/alembic/versions/001_initial_schema.py`:

```python
"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oidc_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(128), unique=True, nullable=False),
        sa.Column("client_secret_hash", sa.String(256), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("redirect_uris", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("allowed_scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "spid_idps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alias", sa.String(64), unique=True, nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("metadata_url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("metadata_cache", sa.Text(), nullable=True),
        sa.Column("metadata_hash", sa.String(64), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "jwk_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("use", sa.String(16), nullable=False),
        sa.Column("private_jwk", postgresql.JSONB(), nullable=False),
        sa.Column("public_jwk", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "ente_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("org_display_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("org_name", sa.String(256), nullable=False, server_default=""),
        sa.Column("org_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("ipa_code", sa.String(32), nullable=False, server_default=""),
        sa.Column("contact_email", sa.String(256), nullable=False, server_default=""),
        sa.Column("contact_phone", sa.String(64), nullable=False, server_default=""),
        sa.Column("org_city", sa.String(128), nullable=False, server_default=""),
        sa.Column("proxy_hostname", sa.String(256), nullable=False, server_default=""),
    )
    op.create_table(
        "spid_cert",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("certificate_pem", sa.Text(), nullable=False),
        sa.Column("private_key_pem", sa.Text(), nullable=False),
        sa.Column("not_valid_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_dn", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "cie_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "saml_metadata_url",
            sa.Text(),
            nullable=False,
            server_default="https://idserver.servizicie.interno.gov.it/idp/shibboleth?Metadata",
        ),
        sa.Column("oidc_federation_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("jwk_federation_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
        sa.Column("jwk_core_sig_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
        sa.Column("jwk_core_enc_id", sa.Integer(), sa.ForeignKey("jwk_keys.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("cie_config")
    op.drop_table("spid_cert")
    op.drop_table("ente_settings")
    op.drop_table("jwk_keys")
    op.drop_table("spid_idps")
    op.drop_table("oidc_clients")
```

- [ ] **Step 6: Commit**

```bash
git add config-api/app/database.py config-api/alembic* config-api/alembic/
git commit -m "feat: database.py + alembic migration initial schema"
```

---

## Task 6: Auth middleware + login

**Files:**
- Create: `config-api/app/auth.py`
- Create: `config-api/app/templates/login.html.j2`
- Test: `config-api/tests/test_auth.py`

- [ ] **Step 1: Scrivi test failing**

Crea `config-api/tests/test_auth.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.mark.asyncio
async def test_login_page_accessible(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/login")
    assert response.status_code == 200
    assert "login" in response.text.lower()


@pytest.mark.asyncio
async def test_dashboard_redirects_unauthenticated(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/admin/", follow_redirects=False)
    assert response.status_code == 302
    assert "/admin/login" in response.headers["location"]


@pytest.mark.asyncio
async def test_login_success_and_redirect(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "secret"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/"


@pytest.mark.asyncio
async def test_login_wrong_password(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/login",
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
    assert response.status_code == 200
    assert "credenziali" in response.text.lower()
```

- [ ] **Step 2: Esegui test — devono fallire**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_auth.py -v
```

Expected: FAIL — `app.main` non esiste ancora.

- [ ] **Step 3: Crea `config-api/app/auth.py`**

```python
import os
from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")


def get_current_user(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return user


def require_auth(request: Request) -> str:
    user = request.session.get("user")
    if not user:
        return None
    return user
```

- [ ] **Step 4: Crea template `config-api/app/templates/login.html.j2`**

```html
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Login — PA SSO Proxy</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container mt-5">
  <div class="row justify-content-center">
    <div class="col-md-4">
      <div class="card shadow-sm">
        <div class="card-body p-4">
          <h4 class="card-title mb-4 text-center">PA SSO Proxy</h4>
          {% if error %}
          <div class="alert alert-danger">{{ error }}</div>
          {% endif %}
          <form method="post" action="/admin/login">
            <div class="mb-3">
              <label class="form-label">Username</label>
              <input type="text" name="username" class="form-control" autofocus required>
            </div>
            <div class="mb-3">
              <label class="form-label">Password</label>
              <input type="password" name="password" class="form-control" required>
            </div>
            <button type="submit" class="btn btn-primary w-100">Accedi</button>
          </form>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 5: Crea `config-api/app/main.py`**

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.routes import dashboard

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html.j2", {"request": request, "error": None})


@app.post("/admin/login")
async def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASSWORD:
        request.session["user"] = username
        return RedirectResponse("/admin/", status_code=302)
    return templates.TemplateResponse(
        "login.html.j2",
        {"request": request, "error": "Credenziali non valide"},
        status_code=200,
    )


@app.post("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)
```

- [ ] **Step 6: Crea `config-api/app/routes/__init__.py`** (vuoto)

```bash
mkdir -p config-api/app/routes
touch config-api/app/routes/__init__.py
```

- [ ] **Step 7: Crea `config-api/app/routes/dashboard.py`** (stub minimo per far partire i test auth)

```python
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import get_current_user

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/admin/login", status_code=302)
    return templates.TemplateResponse("dashboard.html.j2", {"request": request, "user": user})
```

- [ ] **Step 8: Crea template `config-api/app/templates/base.html.j2`**

```html
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}PA SSO Proxy{% endblock %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link rel="stylesheet" href="/admin/static/css/app.css">
</head>
<body>
<nav class="navbar navbar-dark bg-dark px-3">
  <span class="navbar-brand">PA SSO Proxy</span>
  <div class="d-flex">
    <form method="post" action="/admin/logout" class="d-inline">
      <button type="submit" class="btn btn-sm btn-outline-light">Logout</button>
    </form>
  </div>
</nav>
<div class="container-fluid mt-4">
  <div class="row">
    <div class="col-md-2">
      <ul class="nav flex-column nav-pills">
        <li class="nav-item"><a class="nav-link" href="/admin/">Dashboard</a></li>
        <li class="nav-item"><a class="nav-link" href="/admin/clients">Clienti OIDC</a></li>
        <li class="nav-item"><a class="nav-link" href="/admin/idps">Provider SPID</a></li>
        <li class="nav-item"><a class="nav-link" href="/admin/cie">CIE OIDC</a></li>
        <li class="nav-item"><a class="nav-link" href="/admin/certs">Certificati</a></li>
        <li class="nav-item"><a class="nav-link" href="/admin/settings">Impostazioni</a></li>
      </ul>
    </div>
    <div class="col-md-10">
      {% block content %}{% endblock %}
    </div>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 9: Crea template `config-api/app/templates/dashboard.html.j2`**

```html
{% extends "base.html.j2" %}
{% block title %}Dashboard — PA SSO Proxy{% endblock %}
{% block content %}
<h2>Dashboard</h2>
<div class="row mt-3">
  <div class="col-md-3">
    <div class="card text-bg-secondary">
      <div class="card-body">
        <h5 class="card-title">SATOSA</h5>
        <p class="card-text" id="satosa-status">Verifica in corso...</p>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 10: Crea `config-api/app/static/css/app.css`**

```css
body { font-size: 0.9rem; }
.nav-pills .nav-link { color: #333; }
.nav-pills .nav-link:hover { background-color: #f0f0f0; }
```

- [ ] **Step 11: Esegui test auth**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_auth.py -v
```

Expected: tutti e 4 i test **PASS**.

- [ ] **Step 12: Commit**

```bash
git add config-api/app/ config-api/tests/test_auth.py
git commit -m "feat: auth login/logout + dashboard shell + jinja2 templates"
```

---

## Task 7: Dashboard health check

**Files:**
- Modify: `config-api/app/routes/dashboard.py`
- Test: `config-api/tests/test_dashboard.py`

- [ ] **Step 1: Scrivi test failing**

Crea `config-api/tests/test_dashboard.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("ADMIN_USER", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "secret")
    monkeypatch.setenv("SESSION_SECRET", "test-secret-32-chars-minimum-pad")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


async def authenticated_client(app):
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    await client.__aenter__()
    await client.post("/admin/login", data={"username": "admin", "password": "secret"})
    return client


@pytest.mark.asyncio
async def test_dashboard_accessible_when_logged_in(app_env):
    from app.main import app
    client = await authenticated_client(app)
    response = await client.get("/admin/")
    await client.__aexit__(None, None, None)
    assert response.status_code == 200
    assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_health_endpoint(app_env):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

- [ ] **Step 2: Esegui — devono passare già (dashboard stub è sufficiente)**

```bash
cd config-api
PYTHONPATH=. pytest tests/test_dashboard.py -v
```

Expected: **PASS**.

- [ ] **Step 3: Commit**

```bash
git add config-api/tests/test_dashboard.py
git commit -m "test: dashboard e health endpoint"
```

---

## Task 8: pytest.ini + coverage

**Files:**
- Create: `config-api/pytest.ini`
- Create: `config-api/setup.cfg`

- [ ] **Step 1: Crea `config-api/pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 2: Esegui tutti i test**

```bash
cd config-api
PYTHONPATH=. pytest -v --tb=short
```

Expected: tutti i test **PASS**.

- [ ] **Step 3: Commit**

```bash
git add config-api/pytest.ini
git commit -m "test: pytest config asyncio_mode=auto"
```

---

## Task 9: Build e smoke test locale

- [ ] **Step 1: Build immagine config-api**

```bash
cd config-api
docker build -t pa-sso-proxy-config-api:local .
```

Expected: build completa senza errori.

- [ ] **Step 2: Avvia stack (richiede .env compilato)**

```bash
cp .env.example .env
# Imposta almeno: POSTGRES_PASSWORD, ADMIN_USER, ADMIN_PASSWORD, PROXY_HOSTNAME
docker compose up -d
```

- [ ] **Step 3: Attendi avvio (postgres healthcheck)**

```bash
docker compose ps
# Attendi che config-api e nginx siano "healthy" o "running"
```

- [ ] **Step 4: Smoke test**

```bash
curl -s http://localhost:18080/health-admin
# Expected: {"status": "ok"}

curl -s -o /dev/null -w "%{http_code}" http://localhost:18080/admin/
# Expected: 302 (redirect a login se non autenticato)
```

- [ ] **Step 5: Login manuale**

Apri `http://localhost:18080/admin/login` nel browser. Login con le credenziali di `.env`. Verifica che la dashboard sia visibile con navbar e link di navigazione.

- [ ] **Step 6: Commit finale Plan 1**

```bash
git add .
git commit -m "feat: plan 1 complete — foundation stack funzionante con auth e dashboard"
```

---

## Self-Review

**Spec coverage:**
- ✅ Docker Compose con 4 container
- ✅ postgres con healthcheck
- ✅ nginx routing `/admin` → config-api, `/` → satosa
- ✅ All DB models (oidc_clients, spid_idps, cie_config, ente_settings, jwk_keys, spid_cert)
- ✅ Alembic migrations
- ✅ FastAPI + auth sessione
- ✅ WebUI login/logout
- ✅ Dashboard base
- ✅ Template Bootstrap 5 con sidebar navigazione
- ⏭ Client OIDC CRUD → Plan 2
- ⏭ Config generator + SATOSA reload → Plan 2
- ⏭ SPID IdP management → Plan 3
- ⏭ SPID cert management → Plan 3
- ⏭ Metadata watcher → Plan 3
- ⏭ CIE OIDC JWK + entity configuration → Plan 4
- ⏭ SATOSA full integration → Plan 5

**Placeholder scan:** nessun TBD o TODO lasciato.

**Type consistency:**
- `get_current_user()` usato in `auth.py`, referenziato ma non dipendente in `dashboard.py` (dashboard usa `request.session` direttamente — coerente)
- `templates` istanziato sia in `main.py` che in `dashboard.py` — duplicato, ma accettabile per Plan 1; Plan 2 centralizzerà

**Note per Plan 2:**
- Centralizzare `templates = Jinja2Templates(...)` in una singola istanza condivisa
- Aggiungere `Depends(get_current_user)` su tutti i router (non solo dashboard)
