# Design: pa-sso-proxy

**Data**: 2026-05-19
**Stato**: Approvato, da implementare

## Contesto

La Provincia di Pescara necessita di un SSO centralizzato per autenticare i cittadini tramite SPID e CIE su N applicativi interni. Il progetto precedente (`keycloak-login-proxy`) usava Keycloak come core, ma Keycloak è overkill per il use case "solo identità cittadino" e non supporta nativamente CIE OIDC Federation 1.0.

**Decisioni prese durante brainstorming:**
- No Keycloak — rimosso, overkill per solo identità cittadino
- SATOSA-based — IAM proxy leggero, già testato in GovPay-Interaction-Layer
- WebUI standalone — non estensione GovPay backoffice, prodotto indipendente
- Multi-client tipo A — stesso ente, più app (non multi-ente su una istanza)
- Deploy per ente — Docker Compose, un'istanza per ente PA

## Architettura

### Container

| Container | Immagine base | Ruolo |
|---|---|---|
| `nginx` | `nginx:alpine` | Routing: `/` → satosa, `/admin` → config-api |
| `satosa` | Custom Python | IAM proxy (SPID SAML + CIE SAML + CIE OIDC) |
| `config-api` | Custom Python | WebUI FastAPI + config generator + metadata watcher |
| `postgres` | `postgres:16` | Persistenza (client OIDC, config, chiavi) |

### SATOSA backends

- `spid_backend` — SAML SP verso IdP SPID ufficiali AgID
- `cie_saml_backend` — SAML SP verso CIE (Ministero dell'Interno)
- `cie_oidc_backend` — OIDC RP Federation 1.0 verso CIE

### SATOSA frontend

- `oidc_frontend` — OIDC OP verso app dell'ente (multi-client via `oidcop`)

## Config API

### Stack

- Python 3.12
- FastAPI
- Jinja2 (template HTML)
- SQLAlchemy + asyncpg
- APScheduler (cron metadata watcher)

### Sezioni WebUI

1. **Dashboard** — status container, health, ultimo reload
2. **Clienti OIDC** — CRUD client
3. **Provider SPID** — lista IdP, toggle enabled, stato metadata
4. **CIE OIDC** — generazione JWK, download JWKS pubblico
5. **Certificati** — stato cert SPID, rigenera
6. **Impostazioni Ente** — dati org, IPA code, città

### Config generator

Legge DB → costruisce dict Python → serializza YAML → scrive in volume condiviso → `docker restart satosa`.

### Metadata watcher

Cron 02:00. Per ogni IdP abilitato: GET metadata → SHA-256 → se diverso da DB → aggiorna → reload.

## Database

```sql
oidc_clients (id, client_id, client_secret_hash, name, redirect_uris[], allowed_scopes[], enabled)
spid_idps (id, alias, display_name, metadata_url, enabled, metadata_cache, metadata_hash, last_updated)
cie_config (id, saml_metadata_url, oidc_federation_enabled, jwk_federation_id, jwk_core_sig_id, jwk_core_enc_id)
ente_settings (id, org_display_name, org_name, org_url, ipa_code, contact_email, contact_phone, org_city)
jwk_keys (id, name, use, private_jwk JSONB, public_jwk JSONB, created_at)
spid_cert (id, certificate_pem, private_key_pem, not_valid_after, subject_dn)
```

## Multi-client OIDC

SATOSA `oidcop` config YAML:

```yaml
OIDCOP:
  clients:
    client_A:
      client_secret: "bcrypt_hash"
      redirect_uris: [https://app1.ente.it/callback]
      allowed_scopes: [openid, profile]
```

Il config generator costruisce questa sezione da `oidc_clients WHERE enabled=true`.

## Reload SATOSA

```python
import docker
client = docker.from_env()
container = client.containers.get("pa-sso-proxy-satosa-1")
container.restart(timeout=10)
```

Downtime: 3-5 secondi.

## Sicurezza

- Docker socket montato solo in config-api
- WebUI autenticazione session con ADMIN_USER/ADMIN_PASSWORD
- Client secret: bcrypt hash
- JWK privati in DB, mai esposti via API pubblica

## Codice da riusare

| Sorgente | Path | Riuso |
|---|---|---|
| GovPay-Interaction-Layer | `auth-proxy/cieoidc-endpoints/` | CIE OIDC backend SATOSA |
| GovPay-Interaction-Layer | `auth-proxy/startup.sh` (sezione JWK) | Pattern iniezione JWK |
| keycloak-login-proxy | `scripts/manage-spid-cert.py` | Generazione cert SPID |
| keycloak-login-proxy | `scripts/configure-spid.py` | Lista IdP SPID ufficiali |

## Fuori scope (v1)

- Multi-ente su istanza singola
- Federazione SPID OIDC
- IT-Wallet / EUDI Wallet
- SSO dipendenti interni (AD/LDAP)
