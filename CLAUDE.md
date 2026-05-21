# CLAUDE.md

Questo file fornisce contesto a Claude Code quando lavora su questo repository.

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
- `cie_saml_backend` — CIE SAML (Ministero dell'Interno)
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
  templates/              Template YAML per config SATOSA (placeholder → sostituiti da generator)
  static/                 File statici SATOSA (discovery page assets)
config-api/
  app/
    main.py               Entry point FastAPI
    routes/               Blueprint per ogni sezione WebUI
      clients.py          Gestione client OIDC
      idps.py             Gestione IdP SPID/CIE
      settings.py         Impostazioni ente
      keys.py             JWK management
      certs.py            Certificato SPID
    templates/            Jinja2 HTML templates
    models/               SQLAlchemy models
      client.py
      idp.py
      settings.py
      key.py
    satosa_generator.py   Genera config SATOSA da DB
    metadata_watcher.py   Cron aggiornamento metadata IdP
nginx/
  conf.d/
    proxy.conf            Route: / → satosa, /admin → config-api
docs/
  architecture.md         Architettura dettagliata
  deployment.md           Guida deploy (Portainer)
  spid-registration.md    Procedura accreditamento AgID SPID
  cie-oidc-registration.md Registrazione portale CIE OIDC
```

## Variabili d'ambiente chiave

Tutte in `.env` (vedi `.env.example`). Le variabili sono passate dal compose a satosa e config-api.

| Variabile | Usata da |
|---|---|
| `PROXY_HOSTNAME` | SATOSA (redirect URI, SP metadata), config-api |
| `ADMIN_USER` / `ADMIN_PASSWORD` | config-api WebUI |
| `POSTGRES_*` | config-api (SQLAlchemy), postgres |
| `ORG_*` / `IPA_CODE` | config-api (impostazioni ente default) |

## Relazione con altri repository

- **keycloak-login-proxy** (Provincia-di-Pescara) — progetto precedente Keycloak-based. Fonte per: tema HTML, script Python certificato SPID, lista IdP SPID.
- **GovPay-Interaction-Layer** (Comune-di-Montesilvano) — fonte originale per il backend CIE OIDC. Il codice è stato integrato nel repository e ora risiede in `satosa/plugins/` come codice nativo del progetto. Non è necessario ricopiarlo da sorgenti esterne.

## Note implementative importanti

### Certificato SPID
SubjectDN richiesto da AgID: `CN=<domain>, O=<ente>, 2.5.4.83=<entityId>, 2.5.4.97=PA:IT-<IPA_CODE>, C=IT, L=<città>`. Vedi `keycloak-login-proxy/scripts/manage-spid-cert.py` per implementazione Python con `cryptography`.

### CIE OIDC Federation
Il backend CIE OIDC usa 3 JWK separati: `jwk-federation` (firma entity configuration), `jwk-core-sig` (firma OIDC requests), `jwk-core-enc` (cifratura). Il config-api genera questi keypair alla prima configurazione e li espone in WebUI per download pubblico.

### Reload SATOSA
Il config-api segnala il reload toccando `/satosa-conf/.reload` (volume condiviso). uWSGI nel container satosa è configurato con `--touch-reload /satosa-conf/.reload` e ricarica i worker gracefully senza caduta delle connessioni. Non è necessario il Docker socket.

### SATOSA OIDC multi-client
La sezione `clients` nel config OIDC di SATOSA è generata da `satosa_generator.py`. Ogni client ha: `client_id`, `client_secret` (hash), `redirect_uris`, `allowed_scopes`. Il generator scrive il file e triggera reload.
