# CIE OIDC Federation Backend — Design Spec

## Goal

Integrare il backend CIE OIDC Federation in SATOSA: aggiunge autenticazione CIE tramite OpenID Connect Federation 1.0 (protocollo IPZS) accanto all'esistente CIE SAML backend. Gestita interamente da WebUI config-api.

## Architecture

SATOSA riceve richieste OIDC dai client interni (frontend OIDC), poi autentica l'utente verso il provider CIE tramite OIDC Federation (backend CieOidcRp). Le sessioni temporanee del flow OIDC sono salvate in Redis (ephemeral, TTL 2h). La configurazione completa — JWK, trust marks, authority hints — viene generata da config-api e scritta nel volume `/satosa-conf` condiviso.

```
Browser → SATOSA oidc_frontend → client OIDC interno
Browser → SATOSA CieOidcRp backend → CIE OIDC Provider (IPZS federation)
                                              ↓ session state
                                            Redis (redis:alpine, proxy-internal)
```

Il backend CIE OIDC è incluso in proxy.yaml solo se `CieConfig.oidc_federation_enabled = True` E tutti i campi obbligatori sono presenti (trust_mark, trust_mark_id, authority_hint_url, trust_anchor_url, client_id, JWK federation + core).

## Tech Stack

- **Backend class**: `backends.cieoidc.CieOidcBackend` (upstream iam-proxy-italia, già nell'immagine)
- **Endpoint overrides**: GovPay `cieoidc-endpoints/` (7 file .py) — authorization, callback, entity_configuration, federation_fetch/list/resolve/trust_mark_status
- **Session storage**: Redis via `redis:alpine` + adapter `RedisStorage` (~80 righe)
- **Storage interface**: `backends.cieoidc.storage.interfaces.storage.OidcStorage` (ABC con 6 metodi)
- **Config generation**: `satosa_config_generator.py` (FastAPI config-api)
- **DB**: PostgreSQL + SQLAlchemy 2.0 async + Alembic migrations

---

## File Map

### Nuovi file
- `satosa/plugins/redis_storage.py` — RedisStorage adapter
- `satosa/plugins/cieoidc-endpoints/` — Copy da GovPay-Interaction-Layer/auth-proxy/cieoidc-endpoints/ (7 file)
- `satosa/plugins/cieoidc-models/user.py` — Copy da GovPay-Interaction-Layer/auth-proxy/cieoidc-models/user.py
- `config-api/tests/test_redis_storage.py` — Unit test con fakeredis

### File modificati
- `satosa/Dockerfile` — installa redis pip, copia plugin overrides
- `config-api/app/models/cie.py` — 8 nuovi campi Optional[str]
- `config-api/alembic/versions/xxxx_cie_oidc_federation_fields.py` — migrazione
- `config-api/app/satosa_config_generator.py` — `_cie_oidc_backend_yaml()`, migra proxy.yaml a BACKEND_MODULES/FRONTEND_MODULES format
- `config-api/app/routes/cie.py` — 9 nuovi Form fields nel POST
- `config-api/app/templates/cie/config.html.j2` — sezione OIDC Federation
- `config-api/tests/test_satosa_config_generator.py` — test CIE OIDC backend yaml
- `config-api/tests/test_cie.py` — test salvataggio nuovi campi
- `docker-compose.yaml` — aggiunge redis service, REDIS_URL a satosa
- `.env.example` — nessun nuovo var (REDIS_URL fisso: redis://redis:6379/0)

---

## Componenti in Dettaglio

### RedisStorage (`satosa/plugins/redis_storage.py`)

Implementa `OidcStorage` ABC. Due chiavi Redis per sessione:
- `cie:sess:{id}` → JSON di `OidcAuthentication`, TTL 7200s
- `cie:state:{state}` → id sessione, TTL 7200s

```python
class RedisStorage(OidcStorage):
    def __init__(self, url: str, ttl: int = 7200): ...
    def connect(self) -> None: ...          # redis.from_url(url)
    def close(self) -> None: ...
    def is_connected(self) -> bool: ...     # ping()
    def add_session(self, entity) -> int:  # SET cie:sess:{id} EX ttl; SET cie:state:{state} {id} EX ttl
    def update_session(self, entity) -> int: # SET cie:sess:{id} con TTL preserved (KEEPTTL)
    def get_sessions(self, state) -> list:  # GET state→id→doc, return [OidcAuthentication]
```

Config YAML nel `cie_oidc_backend.yaml`:
```yaml
storage:
  redis:
    module: backends.cieoidc.storage.impl.redis_storage
    class: RedisStorage
    init_params:
      url: redis://redis:6379/0
      ttl: 7200
```

### Nuovi campi CieConfig

```python
oidc_provider_url: Mapped[Optional[str]]    # CIE OIDC OP URL (prod o preprod)
trust_anchor_url: Mapped[Optional[str]]      # IPZS trust anchor
authority_hint_url: Mapped[Optional[str]]    # IPZS authority hint
homepage_uri: Mapped[Optional[str]]          # ente homepage (default: settings.org_url)
policy_uri: Mapped[Optional[str]]            # privacy policy URI
logo_uri: Mapped[Optional[str]]              # logo URI
trust_mark_id: Mapped[Optional[str]]         # ID ottenuto da IPZS registration
trust_mark: Mapped[Optional[str]]            # JWT ottenuto da IPZS (testo lungo)
oidc_contact_email: Mapped[Optional[str]]    # email contatto CIE OIDC Federation
```

Tutti 9 nullable. Migration Alembic: `ADD COLUMN` per ciascuno (SQLite-compatible per test, PostgreSQL in produzione).

In `_cie_oidc_backend_yaml()`, campi derivati da `EnteSettings` (non da CieConfig):
- `organization_name` / `client_name` → `settings.org_display_name`
- `contacts` → `[cie_config.oidc_contact_email or settings.contact_email]`

### Config Generation (`satosa_config_generator.py`)

**Migrazione proxy.yaml** da `PLUGIN` inline a `BACKEND_MODULES`/`FRONTEND_MODULES`:

```python
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
```

**`_cie_oidc_backend_yaml()`** genera il config completo:

```python
def _cie_oidc_backend_yaml(
    hostname: str,
    cie_config: CieConfig,
    jwk_federation: dict,   # JWK dict completo
    jwk_core_sig: dict,
    jwk_core_enc: dict,
    redis_url: str,
) -> dict:
    return {
        "module": "backends.cieoidc.CieOidcBackend",
        "name": "CieOidcRp",
        "config": {
            "network": {"httpc_params": {"connection": {"ssl": True}, "session": {"timeout": 6}}},
            "storage": {
                "redis": {
                    "module": "backends.cieoidc.storage.impl.redis_storage",
                    "class": "RedisStorage",
                    "init_params": {"url": redis_url, "ttl": 7200},
                }
            },
            "providers": [cie_config.oidc_provider_url],
            "security_operations": {
                "hash": {"default": {"func": "SHA-256"}},
                "sign": {
                    "default": {"alg": "RS256"},
                    "supported": {"alg": ["RS256","RS384","RS512","ES256","ES384","ES512"]},
                },
                "encrypt": {
                    "default": {"alg": "RSA-OAEP", "enc": "A256CBC-HS512"},
                    "supported": {
                        "alg": ["RSA-OAEP","RSA-OAEP-256","ECDH-ES","ECDH-ES+A128KW","ECDH-ES+A192KW","ECDH-ES+A256KW"],
                        "enc": ["A128CBC-HS256","A192CBC-HS384","A256CBC-HS512","A128GCM","A192GCM","A256GCM"],
                    },
                },
            },
            "jwks": {
                "federation": [jwk_federation],
                "core": [jwk_core_sig, jwk_core_enc],
            },
            "metadata": {
                "federation_entity": {
                    "federation_resolve_endpoint": f"https://{hostname}/CieOidcRp/resolve",
                    "organization_name": settings.org_display_name,   # da EnteSettings
                    "homepage_uri": cie_config.homepage_uri,
                    "policy_uri": cie_config.policy_uri,
                    "logo_uri": cie_config.logo_uri,
                    "contacts": [cie_config.oidc_contact_email],
                },
                "openid_relying_party": {
                    "application_type": "web",
                    "client_id": cie_config.client_id,
                    "client_name": settings.org_display_name,
                    "organization_name": settings.org_display_name,
                    "client_registration_types": ["automatic"],
                    "signed_jwks_uri": f"https://{hostname}/CieOidcRp/openid_relying_party/jwks.jose",
                    "jwks": None,  # autopopolato dal backend
                    "contacts": [cie_config.oidc_contact_email],
                    "grant_types": ["refresh_token", "authorization_code"],
                    "redirect_uris": [f"https://{hostname}/CieOidcRp/oidc/callback"],
                    "response_types": ["code"],
                    "subject_type": "pairwise",
                    "id_token_signed_response_alg": "RS256",
                    "userinfo_signed_response_alg": "RS256",
                    "userinfo_encrypted_response_alg": "RSA-OAEP",
                    "userinfo_encrypted_response_enc": "A256CBC-HS512",
                    "token_endpoint_auth_method": "private_key_jwt",
                    "scope": "openid email",
                    "code_challenge": {"length": 64, "method": "S256"},
                    "claim": {
                        "id_token": {"sub": {"essential": True}, "family_name": {"essential": True}, "given_name": {"essential": True}},
                        "userinfo": {"sub": None, "given_name": None, "family_name": None, "email": {"essential": True}, "https://attributes.eid.gov.it/fiscal_number": None},
                    },
                    "claims": {  # campo standard OIDC Federation
                        "id_token": {"sub": {"essential": True}, "family_name": {"essential": True}, "given_name": {"essential": True}},
                        "userinfo": {"sub": None, "given_name": None, "family_name": None, "email": {"essential": True}, "https://attributes.eid.gov.it/fiscal_number": None},
                    },
                },
            },
            "trust_chain": {
                "config": {
                    "cache_ttl": 0,
                    "trust_anchor": [cie_config.trust_anchor_url],
                    "httpc_params": {"connection": {"ssl": True}, "session": {"timeout": 6}},
                }
            },
            "endpoints": {
                # Ogni endpoint ha: module, class, routes, config (con authority_hints, trust_marks, jwks_*, metadata, entity_type, entity_configuration_exp, default_sig_alg)
                # Struttura derivata da GovPay cieoidc_backend.override.yaml.template — implementer legge il template per i dettagli completi
                "entity_config_endpoint": {
                    "module": "backends.cieoidc.endpoints.entity_configuration",
                    "class": "EntityConfigHandler",
                    "routes": ["/.well-known/openid-federation", "/openid_relying_party/jwks.json", "/openid_relying_party/jwks.jose"],
                    "config": {
                        "entity_type": "openid_relying_party",
                        "entity_configuration_exp": 525600,
                        "default_sig_alg": "RS256",
                        "authority_hints": [cie_config.authority_hint_url],
                        "trust_marks": [{"id": cie_config.trust_mark_id, "trust_mark": cie_config.trust_mark}],
                        # metadata, jwks_federation, jwks_core — stesso schema del template GovPay
                    },
                },
                # federation_resolve_endpoint, federation_fetch_endpoint: stessa struttura di entity_config_endpoint ma trust_marks: []
                # federation_trust_mark_status_endpoint, federation_list_endpoint: config: {}
                # authorization_endpoint: aggiunge db_config, prompt: "consent"
                # authorization_callback_endpoint: aggiunge db_config, httpc_params, alg/enc, claims mapping
                # extends_session_endpoint: httpc_params, client_assertion_type, grant_type refresh_token
            },
        },
    }
```

**Condizione di inclusione** in `generate_satosa_config()`:
```python
include_cie_oidc = (
    cie_config is not None
    and cie_config.oidc_federation_enabled
    and cie_config.trust_mark
    and cie_config.trust_mark_id
    and cie_config.authority_hint_url
    and cie_config.trust_anchor_url
    and cie_config.client_id
    and jwk_federation is not None
    and jwk_core_sig is not None
    and jwk_core_enc is not None
)
```

### Dockerfile SATOSA

```dockerfile
FROM ghcr.io/italia/iam-proxy-italia:latest
USER root
RUN pip install redis --quiet
COPY plugins/cieoidc-endpoints/ /satosa_proxy/backends/cieoidc/endpoints/
COPY plugins/cieoidc-models/    /satosa_proxy/backends/cieoidc/models/
COPY plugins/redis_storage.py   /satosa_proxy/backends/cieoidc/storage/impl/redis_storage.py
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "60", "satosa.wsgi:APP"]
```

### docker-compose.yaml

```yaml
redis:
  image: redis:alpine
  restart: unless-stopped
  networks:
    - proxy-internal
  # nessuna porta esposta

satosa:
  environment:
    - REDIS_URL=redis://redis:6379/0
  depends_on:
    config-api:
      condition: service_healthy
    redis:
      condition: service_started
```

### WebUI (`cie/config.html.j2`)

Nuova card "CIE OIDC Federation" con:
- Toggle `oidc_federation_enabled` (Bootstrap switch)
- Sezione collassabile visibile solo se toggle ON
- Campi: `oidc_provider_url` (con placeholder URL preprod CIE), `trust_anchor_url`, `authority_hint_url`, `homepage_uri`, `policy_uri`, `logo_uri`
- `trust_mark_id` (input text)
- `trust_mark` (textarea, per JWT lungo)
- Badge stato: "Configurato" (verde) / "Incompleto — mancano campi obbligatori" (arancione)

---

## Error Handling

- `generate_satosa_config()` non-op se `oidc_federation_enabled` ma campi incompleti — non scrive `cie_oidc_backend.yaml`, non aggiunge a `BACKEND_MODULES`
- `CieOidcBackend.__init__` fa HTTP fetch del trust anchor — se URL non raggiungibile SATOSA non parte. Questo è comportamento upstream atteso (l'ente deve avere connettività verso IPZS).
- Redis connection failure: SATOSA non parte (session storage obbligatorio per il flow)

---

## Testing

### `test_redis_storage.py`
Usa `fakeredis` (pip install fakeredis):
```python
def test_add_and_get_session():
    storage = RedisStorage(url="redis://localhost", ttl=3600)
    storage._client = fakeredis.FakeRedis()
    entity = OidcAuthentication(id="abc", state="xyz", client_id="c1", ...)
    storage.add_session(entity)
    result = storage.get_sessions("xyz")
    assert len(result) == 1
    assert result[0].id == "abc"

def test_update_session_preserves_ttl():
    ...

def test_get_sessions_missing_state_returns_empty():
    ...
```

### `test_satosa_config_generator.py` (aggiunte)
```python
async def test_cie_oidc_backend_yaml_generated_when_enabled(db_session):
    # setup CieConfig con tutti i campi + JwkKey x3
    # genera config
    # assert "cie_oidc_backend.yaml" scritto
    # assert "BACKEND_MODULES" in proxy.yaml include il path

async def test_cie_oidc_backend_not_generated_when_disabled(db_session):
    # oidc_federation_enabled = False
    # assert "cie_oidc_backend.yaml" NOT scritto

async def test_proxy_yaml_uses_backend_modules_format(db_session):
    # assert proxy.yaml ha BACKEND_MODULES key, non PLUGIN
```

### `test_cie.py` (aggiunte)
```python
async def test_cie_config_saves_trust_mark_fields(auth_client):
    response = await auth_client.post("/admin/cie", data={
        "saml_metadata_url": "https://x",
        "trust_mark": "eyJ...",
        "trust_mark_id": "https://registry.cie.gov.it/tm/rp",
        "authority_hint_url": "https://registry.cie.gov.it",
        ...
    })
    assert response.status_code in (200, 302)
    # verifica DB
```
