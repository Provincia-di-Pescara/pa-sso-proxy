# CLAUDE.md

Questo file fornisce contesto a Claude Code quando lavora su questo repository.

## Comandi rapidi

```bash
docker compose up -d --build   # build + avvia stack
docker compose logs -f config-api
docker compose logs -f satosa
docker compose restart satosa  # dopo modifica manuale a satosa-conf
```

## Cos'è

Docker Compose stack per SSO centralizzato di Pubblica Amministrazione italiana. Permette a N applicativi dell'ente di autenticare cittadini tramite SPID e CIE, esponendo un'unica interfaccia OIDC standard (PKCE).

**Non usa Keycloak.** Lo stack è SATOSA-based, più leggero e allineato al use case "solo identità cittadino".

## Architettura

```
nginx → satosa        SATOSA IAM proxy
      → config-api    FastAPI + Jinja2 (WebUI + config generator)
postgres              PostgreSQL (client OIDC, config ente, JWK)
```

### Flusso autenticazione

```
App → OIDC PKCE → nginx → satosa (OIDC frontend)
satosa → pagina discovery (SPID/CIE) → IdP upstream
IdP → satosa (callback) → JWT con attributi → App
```

### SATOSA — backend supportati

- `spid_backend` — SPID SAML (tutti gli IdP ufficiali AgID)
- `cie_oidc_backend` — CIE OIDC Federation 1.0 (codice in `satosa/plugins/`, mantenuto in questo repo)

### Config API (`config-api/`)

FastAPI app con due ruoli:
1. **WebUI** — pagine Jinja2 per gestione clienti, IdP, certs, JWK, impostazioni ente
2. **Config generator** — legge DB → scrive config SATOSA YAML → segnala reload

Il reload avviene toccando `/satosa-conf/.reload` (volume condiviso) → uWSGI `--touch-reload` rileva il cambio mtime e ricarica i worker gracefully (zero downtime).

### Multi-client OIDC

SATOSA OIDC frontend (`oidcop`) accetta lista `clients` nel config YAML. Il config generator costruisce questo blocco da DB ogni volta che un client viene aggiunto/modificato.

### Metadata IdP

Cron notturno nel config-api:
1. Fetcha URL metadata SPID/CIE
2. Confronta hash con versione in DB
3. Se diverso → aggiorna DB → rigenera config → reload SATOSA

Reload graceful uWSGI: zero downtime (worker swap in-flight). Schedulato di notte per i metadata IdP.

## Struttura directory

```
satosa/
  plugins/                Plugin Python custom (SPID backend, CIE OIDC backend, endpoints)
    spidsaml2.py          Backend SPID SAML2
    cieoidc-backend/      Backend CIE OIDC Federation
    cieoidc-endpoints/    Endpoint CIE OIDC (callback, entity config, …)
  public/                 Asset statici discovery page
config-api/
  app/
    main.py               Entry point FastAPI
    routes/               Route per ogni sezione WebUI
      dashboard.py        Dashboard + statistiche accessi
      clients.py          Gestione client OIDC
      idps.py             Gestione IdP SPID/CIE
      cie.py              Configurazione CIE OIDC Federation
      settings.py         Impostazioni ente
      certs.py            Certificato SPID
      access_log.py       Monitoraggio accessi (filtri, paginazione, CSV)
      internal.py         POST /internal/access-log (chiamato da SATOSA, no auth)
      placeholders.py     eIDAS e IT Wallet coming-soon
      test_client.py      Test flow OIDC
      backup.py           Backup/ripristino configurazione JSON
    templates/            Jinja2 HTML templates
    models/               SQLAlchemy models
      client.py, idp.py, cie.py, settings.py, key.py, cert.py
      access_log.py       Log accessi anonimi
    satosa_config_generator.py   Genera YAML SATOSA + plugin Python da DB
    satosa_generator.py   Wrapper: chiama generator + scrive cert/key
    metadata_watcher.py   Cron aggiornamento metadata IdP
  alembic/versions/       Migrazioni DB (001–006)
nginx/
  conf.d/
    proxy.conf            Route: / → satosa, /admin → config-api
docs/
  architecture.md, deployment.md, spid-registration.md, cie-oidc-registration.md
```

## Variabili d'ambiente chiave

Tutte in `.env` (vedi `.env.example`). Le variabili sono passate dal compose a satosa e config-api.

| Variabile | Usata da |
|---|---|
| `PROXY_HOSTNAME` | SATOSA (redirect URI, SP metadata), config-api |
| `ADMIN_USER` / `ADMIN_PASSWORD` | config-api WebUI |
| `POSTGRES_*` | config-api (SQLAlchemy), postgres |
| `ORG_*` / `IPA_CODE` | config-api (impostazioni ente default) |
| `SATOSA_INTERNAL_URL` | config-api → health check SATOSA (dashboard) |
| `CONFIG_API_INTERNAL_URL` | SATOSA plugins → POST /internal/access-log |

## Relazione con altri repository

- **keycloak-login-proxy** (Provincia-di-Pescara) — progetto precedente Keycloak-based. Fonte per: tema HTML, script Python certificato SPID, lista IdP SPID.
- **GovPay-Interaction-Layer** (Comune-di-Montesilvano) — fonte originale per il backend CIE OIDC. Il codice è stato integrato nel repository e ora risiede in `satosa/plugins/` come codice nativo del progetto. Non è necessario ricopiarlo da sorgenti esterne.

## Note implementative importanti

### Certificato SPID
SubjectDN richiesto da AgID: `CN=<domain>, O=<ente>, 2.5.4.83=<entityId>, 2.5.4.97=PA:IT-<IPA_CODE>, C=IT, L=<città>`. Vedi `keycloak-login-proxy/scripts/manage-spid-cert.py` per implementazione Python con `cryptography`.

### CIE OIDC Federation
Il backend CIE OIDC usa 3 JWK separati: `jwk-federation` (firma entity configuration), `jwk-core-sig` (firma OIDC requests), `jwk-core-enc` (cifratura). Il config-api genera questi keypair e li espone in WebUI con tab separato "Portale CIE" (solo federation key, privata) e "SATOSA interno" (public).

**URL fissi produzione:**
- Trust Anchor / authority_hint: `https://oidc.registry.servizicie.interno.gov.it`
- OP (provider): `https://oidc.idserver.servizicie.interno.gov.it`
- Trust anchor e authority_hint coincidono — NON usare l'OP come authority_hint (causa errore federazione)

**URL fissi collaudo:**
- Trust Anchor / authority_hint: `https://preproduzione.cie.interno.gov.it`
- OP: `https://preproduzione.cie.interno.gov.it/idp/oidc/op`

**Algoritmi enc richiesti da CIE:** `RSA-OAEP` + `A256CBC-HS512`. Non `RSA-OAEP-256`/`A256GCM` (il portale CIE li rifiuta).

**Entity configuration JWT — campi obbligatori verificati:**
- `contacts` in `federation_entity`: deve essere PEC dell'ente (non email generica)
- `claims` in `openid_relying_party`: campo standard OIDC (internamente config usa `claim`, entity_configuration.py mappa → `claims` in pubblicazione)
- `authority_hints`: Trust Anchor, non OP
- `trust_marks`: emesso dal portale CIE dopo accettazione registrazione — non generabile autonomamente

**Registrazione portale CIE:**
- Entity ID da inserire: `https://<PROXY_HOSTNAME>/CieOidcRp` (con path, non root dominio)
- Il portale fetcha `{entity_id}/.well-known/openid-federation` — l'iss nel JWT deve corrispondere esattamente

**cryptojwt e `use=federation`:** cryptojwt rifiuta chiavi con `use=federation` per signing (`alg_keys` accetta solo `use=sig` o assente). La chiave federation nel SATOSA config viene scritta senza campo `use` (RFC 7517: assente = qualsiasi uso). Il DB mantiene `use=federation` per il display nel portale.

**Istanza di riferimento funzionante:** `https://pagopa-prx.comune.montesilvano.pe.it/` (govpay-interaction-layer Comune di Montesilvano). Per debug confrontare `/.well-known/openid-federation` con quella istanza.

### Reload SATOSA
Il config-api segnala il reload toccando `/satosa-conf/.reload` (volume condiviso). uWSGI nel container satosa è configurato con `--touch-reload /satosa-conf/.reload` e ricarica i worker gracefully senza caduta delle connessioni. Non è necessario il Docker socket.

### SATOSA OIDC multi-client
La sezione `clients` nel config OIDC di SATOSA è generata da `satosa_generator.py`. Ogni client ha: `client_id`, `client_secret` (hash), `redirect_uris`, `allowed_scopes`. Il generator scrive il file e triggera reload.

### Plugin SATOSA generati a runtime
`satosa_config_generator.py` scrive moduli Python in `/satosa-conf/` a ogni rigenerazione config (es. `default_backend_router.py`, `oidc_frontend_ext.py`, `access_log_reporter.py`). Questi file sono caricati da SATOSA via `CUSTOM_PLUGIN_MODULE_PATHS: ["/satosa-conf"]`. Non modificarli direttamente in satosa-conf — vengono sovrascritti al prossimo reload.

### Access log pipeline
Ogni auth SATOSA completata (successo o errore) → `POST http://config-api:8000/internal/access-log` (rete Docker interna, nginx non lo espone, nessuna autenticazione necessaria). Endpoint fire-and-forget: risponde sempre 200, errori DB non bloccano SATOSA. Tabella `access_log` (migration 006): nessun PII — solo `provider_type` / `client_id` / `result` / `error_code`.
