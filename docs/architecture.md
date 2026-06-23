# Architettura

## Panoramica

`pa-sso-proxy` è uno stack Docker Compose che funge da Identity Broker per enti di Pubblica Amministrazione italiana. Riceve richieste OIDC dagli applicativi dell'ente e le traduce in autenticazioni SPID/CIE upstream.

```
┌──────────────────────────────────────────────────────────────┐
│                     Internet (cittadino)                      │
└──────────────────────────┬───────────────────────────────────┘
                           │ HTTPS
                    [Reverse Proxy esterno]
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                     Docker Compose                            │
│                                                               │
│  ┌─────────┐    ┌──────────────────────────────────────────┐ │
│  │  nginx  │───▶│  satosa                                  │ │
│  │         │    │  ┌────────────────┐  ┌─────────────────┐ │ │
│  │ /admin  │    │  │ OIDC Frontend  │  │ SPID Backend    │ │ │
│  │    │    │    │  │ (multi-client) │  │ (SAML)          │ │ │
│  │    │    │    │  │                │  ├─────────────────┤ │ │
│  │    ▼    │    │  │                │  │ CIE SAML Backend│ │ │
│  │ config  │    │  └────────────────┘  ├─────────────────┤ │ │
│  │   api   │    │                      │ CIE OIDC Backend│ │ │
│  │(FastAPI)│    │                      │ (Federation 1.0)│ │ │
│  └────┬────┘    └──────────────────────┴─────────────────┘ │ │
│       │                                                      │ │
│  ┌────▼────┐                                                 │ │
│  │postgres │                                                 │ │
│  └─────────┘                                                 │ │
└──────────────────────────────────────────────────────────────┘
```

## Componenti

### nginx

Reverse proxy interno. Routing:
- `/*` → `satosa:8080` (flusso autenticazione cittadino)
- `/admin/*` → `config-api:8000` (WebUI amministrativa)

### satosa

SATOSA IAM proxy (Python). Core del sistema.

**Frontend OIDC** (`oidcop`): espone l'interfaccia verso gli applicativi dell'ente. Supporta N client configurati dinamicamente. Protocollo: OIDC Authorization Code + PKCE.

**Backend SPID SAML**: SP SAML verso gli IdP SPID ufficiali AgID.

**Backend CIE SAML**: SP SAML verso il Ministero dell'Interno (CIE).

**Backend CIE OIDC**: RP OIDC Federation 1.0 verso CIE. Espone:
- `/.well-known/openid-federation` — entity configuration (JWT firmato con `jwk-federation`)
- `/openid_relying_party/jwks.json` — JWKS pubblico

La config di SATOSA è un insieme di file YAML. I file sono template con placeholder sostituiti da `config-api` a ogni modifica.

### config-api

FastAPI application (Python). Due ruoli:

**WebUI** (pagine Jinja2): interfaccia admin.

**Config generator** (`satosa_generator.py`): legge da PostgreSQL → scrive YAML SATOSA → triggera reload di SATOSA toccando il file `.reload` nel volume condiviso.

**Metadata watcher** (`metadata_watcher.py`): cron notturno, fetcha URL metadata SPID/CIE, se cambiati aggiorna DB e triggera reload.

### postgres

| Tabella | Contenuto |
|---|---|
| `oidc_clients` | Client OIDC registrati |
| `spid_idps` | IdP SPID (alias, metadata_url, enabled, cache) |
| `cie_config` | Config CIE (SAML + OIDC federation settings) |
| `ente_settings` | Dati ente (nome, IPA code, città, contatti) |
| `jwk_keys` | Keypair JWK per CIE OIDC |
| `spid_cert` | Certificato SPID corrente e scadenza |

## Flusso autenticazione SPID

```
1. App → GET /authorize?client_id=X&redirect_uri=...&code_challenge=...
2. satosa → pagina discovery → utente sceglie IdP SPID
3. satosa → SAML AuthnRequest → IdP SPID
4. IdP → SAML Response → satosa callback
5. satosa → estrae attributi (fiscalNumber, name, ...)
6. App → POST /token con code + code_verifier
7. satosa → access_token + id_token (JWT con attributi SPID)
```

## Flusso autenticazione CIE OIDC

```
1-2. Come sopra (discovery → utente sceglie CIE OIDC)
3. satosa → OIDC Authorization Request → CIE IdP
4. CIE IdP → verifica /.well-known/openid-federation
5. CIE IdP → redirect con authorization_code
6. satosa → token exchange → JWT con attributi CIE
```

## Flusso aggiornamento config client

```
1. Admin → WebUI → aggiunge/modifica client OIDC
2. config-api → salva in postgres
3. satosa_generator.py → riscrive YAML
4. config-api → tocca il file `/satosa-conf/.reload` → uWSGI in satosa rileva il cambio e ricarica i worker gracefully (zero downtime)
```

## Chiavi e certificati

### Certificato SPID

SubjectDN conforme AgID:
```
CN=<domain>, O=<ente>, 2.5.4.83=<entityId>, 2.5.4.97=PA:IT-<IPA_CODE>, C=IT, L=<città>
```
Estensioni: `basicConstraints` (CA:FALSE), `keyUsage` (digitalSignature + nonRepudiation), `certificatePolicies` (OID AgID).

Generato da config-api con Python `cryptography`. Valido 10 anni. Rinnovato automaticamente entro 90 giorni dalla scadenza.

### JWK CIE OIDC

Tre keypair RSA 4096:
- `jwk-federation` — firma entity configuration JWT
- `jwk-core-sig` — firma OIDC requests (esposto pubblicamente)
- `jwk-core-enc` — cifratura userinfo (esposto pubblicamente)

## Sicurezza

- WebUI (`/admin`) separata da percorso pubblico via nginx routing
- config-api NON esposto su Internet direttamente
- Nessun Docker socket montato o privilegi speciali richiesti (il reload è gestito in modo sicuro tramite mtime del file `.reload` condiviso)
- Client secret memorizzato come bcrypt hash
- JWK privati in DB (JSONB), mai esposti via API pubblica
