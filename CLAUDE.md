# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandi rapidi

```bash
docker compose up -d --build   # build + avvia stack
docker compose logs -f config-api
docker compose logs -f satosa
docker compose restart satosa  # dopo modifica manuale a satosa-conf

# Test (da eseguire nella directory config-api/)
cd config-api && pytest                              # tutti i test
cd config-api && pytest tests/test_satosa_config_generator.py -v  # singolo file
cd config-api && pytest tests/test_eidas.py::test_name -v         # singolo test
```

`docker compose port nginx 80` per trovare la porta host esposta (es. `18080`) quando serve `curl`/testare form admin dal terminale — config-api non è esposto direttamente sull'host, solo dietro nginx.

Test flussi SATOSA via script su `http://localhost:<porta>`: il cookie `satosa_state` è `Secure; SameSite=None`, quindi httpx/curl non lo rimandano su http → SATOSA perde lo stato (scope, client) e il comportamento sembra sbagliato. Estrai `satosa_state=...` dal `Set-Cookie` della `/OIDC/authorization` e passalo a mano come header `Cookie`.

`POST /admin/eidas/toggle` da form: checkbox `eidas_enabled=yes` per abilitare (assente = disabilita), **richiede anche `confirmed=yes`** altrimenti redirect a warning senza applicare nulla (stesso `window.confirm()` della UI) — utile saperlo per test via curl/script.

Login admin via curl/script: con 2FA attivo (default) `POST /admin/login` dà solo `pending_2fa` → serve `POST /admin/login/2fa` con `code` TOTP. In locale più semplice `ADMIN_2FA_ENABLED=false`. Reset TOTP: `docker compose exec config-api python -m app.cli reset-2fa`. Nei test pytest il 2FA è off di default (fixture autouse in `tests/conftest.py`); i test 2FA lo riattivano con `monkeypatch.setenv("ADMIN_2FA_ENABLED", "true")`.

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

- `spid_backend` — SPID SAML (tutti gli IdP ufficiali AgID + nodo eIDAS italiano)
- `cie_oidc_backend` — CIE OIDC Federation 1.0 (codice in `satosa/plugins/`, mantenuto in questo repo)

**IT-Wallet/OpenID4VP**: nessun backend esiste ancora in questo repo. Ricerca preparatoria (attori, processo onboarding federativo, variabili RP config) in `docs/itwallet-registration.md` — leggere prima di ripartire su questo, evita di rifare la ricerca.

### Config API (`config-api/`)

FastAPI app con due ruoli:
1. **WebUI** — pagine Jinja2 per gestione clienti, IdP, certs, JWK, impostazioni ente
2. **Config generator** — legge DB → scrive config SATOSA YAML → segnala reload

Il reload avviene toccando `/satosa-conf/.reload` (volume condiviso) → uWSGI `--touch-reload` rileva il cambio mtime e ricarica i worker gracefully (zero downtime).

### Multi-client OIDC

SATOSA OIDC frontend (`oidcop`) accetta lista `clients` nel config YAML. Il config generator costruisce questo blocco da DB ogni volta che un client viene aggiunto/modificato.

### Metadata IdP

- **SPID aggregate**: scaricato programmaticamente a startup da `https://registry.spid.gov.it/metadata/idp/spid-entities-idps.xml`, cached in `/satosa-conf/spid-entities-idps.xml` (con hash-check). Fallback al file bundled nell'immagine solo se il volume file manca.
- **Altri IdP** (CIE, eIDAS, test): URL metadata per singolo IdP; cron notturno aggiorna DB → rigenera config → reload SATOSA.

Reload graceful uWSGI: zero downtime (worker swap in-flight).

## Struttura directory

```
satosa/
  plugins/                Plugin Python custom (SPID backend, CIE OIDC backend, endpoints)
    spidsaml2.py          Backend SPID SAML2 (flag ficep_enable per ACS eIDAS 99/100)
    cieoidc-backend/      Backend CIE OIDC Federation
    cieoidc-endpoints/    Endpoint CIE OIDC (callback, entity config, …)
  public/                 Asset statici discovery page
config-api/
  app/
    main.py               Entry point FastAPI
    admin_2fa.py          2FA TOTP admin (flag env, cifratura secret, verifica anti-replay)
    cli.py                `python -m app.cli reset-2fa`
    routes/               Route per ogni sezione WebUI
      dashboard.py        Dashboard + statistiche accessi
      login_2fa.py        /admin/login/2fa + /admin/login/setup (enrollment forzato)
      clients.py          Gestione client OIDC
      idps.py             Gestione IdP SPID/CIE
      cie.py              Configurazione CIE OIDC Federation
      eidas.py            Toggle eIDAS + verifica metadata ACS
      settings.py         Impostazioni ente
      certs.py            Certificato SPID
      access_log.py       Monitoraggio accessi (filtri, paginazione, CSV)
      internal.py         POST /internal/access-log (chiamato da SATOSA, no auth)
      verifica.py         Pagina pubblica test SPID (no auth — attiva solo con test IdP)
      test_client.py      Test flow OIDC
      backup.py           Backup/ripristino configurazione JSON
    templates/            Jinja2 HTML templates
    models/               SQLAlchemy models
      client.py, idp.py, cie.py, settings.py, key.py, cert.py
      access_log.py       Log accessi (idp_entity_id, fiscal_number_hash, user_type)
      access_stats_monthly.py  Aggregati mensili (forever, no PII)
    satosa_config_generator.py   Genera YAML SATOSA + plugin Python da DB
    satosa_generator.py   Wrapper: chiama generator + scrive cert/key
    metadata_watcher.py   Cron aggiornamento metadata IdP + retention access_log
  alembic/versions/       Migrazioni DB (001–019)
nginx/
  conf.d/
    proxy.conf            Route: /verifica → config-api, /admin → config-api, / → satosa
docs/
  architecture.md, deployment.md, spid-registration.md, cie-oidc-registration.md
```

## Variabili d'ambiente chiave

Tutte in `.env` (vedi `.env.example`). Le variabili sono passate dal compose a satosa e config-api.

| Variabile | Usata da |
|---|---|
| `PROXY_HOSTNAME` | SATOSA (redirect URI, SP metadata), config-api |
| `ADMIN_USER` / `ADMIN_PASSWORD` | config-api WebUI |
| `ADMIN_2FA_ENABLED` / `ADMIN_2FA_RESET` | config-api — 2FA TOTP admin (default on; `false` solo dev locale) / reset all'avvio |
| `POSTGRES_*` | config-api (SQLAlchemy), postgres |
| `ORG_*` / `IPA_CODE` | config-api (impostazioni ente default) |
| `SATOSA_INTERNAL_URL` | config-api → health check SATOSA (dashboard) |
| `CONFIG_API_INTERNAL_URL` | SATOSA plugins → POST /internal/access-log |
| `SATOSA_HASH_SALT` | CF pseudonymization (HMAC key); deriva anche secret del client `__spid_verifica__` |
| `CF_HASH_KEY` | Alias di SATOSA_HASH_SALT usato in `access_log_reporter.py` generato; generare con `openssl rand -hex 32`, mai committare |

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

### eIDAS
Il nodo eIDAS italiano usa lo **stesso backend SAML2** di SPID (`spid_backend`). La differenza è nel metadata SP: quando `eidas_enabled=True` in `ente_settings`, `satosa_config_generator.py` imposta `ficep_enable: true` in `spidsaml2.py`, che aggiunge ACS index 99 ("eIDAS Natural Person Minimum") e 100 ("eIDAS Natural Person Full") al metadata SP.

**Abilitare eIDAS modifica il metadata SPID** → richiede ri-validazione AgID. La WebUI mostra warning con `window.confirm()` prima di procedere.

URL metadata IdP eIDAS: QA `https://sp-proxy.pre.eid.gov.it/spproxy/idpitmetadata`, Prod `https://sp-proxy.eid.gov.it/spproxy/idpitmetadata`.

### SPID persona giuridica
Quando un client OIDC chiede lo scope `legal_entity`, il backend SPID (`spidsaml2.py`) aggiunge all'`AuthnRequest` l'estensione `<spid:Purpose>PG</spid:Purpose>` (Avviso AgID n.18 v.2, identità Tipo 3/4 uso professionale) e imposta `attribute_consuming_service_index` sull'ACS dedicato (index `4`) invece del default index 0. Questo ACS dichiara sia gli attributi persona fisica sia quelli azienda (`companyName`, `registeredOffice`, `ivaCode`); è creato in `__create_metadata` quando `legal_entity_enable: true` in `sp_config` (derivato da `ente_settings.legal_entity_enabled`). Lato OIDC, i claim azienda sono rilasciati solo per lo scope `legal_entity` (non per `profile`), per minimizzazione dati — vedi `extra_scopes` in `_oidc_frontend_yaml`.

**Abilitare persona giuridica modifica il metadata SPID** (nuovo ACS) → richiede ri-validazione AgID, stesso avviso già presente per eIDAS.

**Flusso persona giuridica = solo SPID.** Con scope `legal_entity`, `SpidSAMLBackend.disco_query` aggiunge `legal_entity=1` all'URL della discovery (`disco.html` è statica, non legge lo stato SATOSA): la pagina nasconde le tab CIE/eIDAS e mostra un avviso. Guard lato server (URL di login aperti a mano): `authn_request` rifiuta l'`entity_id` FICEP e `CieOidcBackend.start_auth` rifiuta CIE, entrambi con la pagina d'errore del proxy (403, `LEGAL_ENTITY_SPID_ONLY_ERROR`), non redirect al client. Motivo: ACS eIDAS 99/100 sono solo "Natural Person" e CIE non ha identità PG — nessuno dei due può restituire i claim aziendali.

### Storico certificati e metadata SPID/eIDAS
`SpidCert.is_active` (un solo `True` alla volta, applicativo non DB) sostituisce la selezione "ultimo per data" in tutti i punti che leggono il cert attivo (`idps.py`, `dashboard.py`, `eidas.py`, `backup.py`). Storico consultabile in `/admin/certs`: export cert/chiave, riattivazione, eliminazione dei non-attivi.

`spid_metadata_version` storicizza ogni XML di metadata generato da SATOSA: `spidsaml2.py` invia uno snapshot fire-and-forget a `POST /internal/spid-metadata-snapshot` dopo ogni `__create_metadata`. Un admin può "esporre" (rollback non distruttivo) una versione storica: `config-api` scrive/rimuove `/satosa-conf/spid_sp_metadata_override.xml`, che `_metadata_endpoint` serve al posto del metadata dinamico se presente (nessun reload necessario, letto ad ogni richiesta). Il file è rifiutato se è un symlink (`os.open(..., O_NOFOLLOW)`) — endpoint pubblico, stessa directory della chiave privata SPID.

**Gotcha (risolto):** pysaml2 firma con ID XML casuale (`sign_entity_descriptor(metadata, None, secc, ...)` → `ident=None` → `sid()`), quindi hash del documento FIRMATO cambia ad ogni reload anche a config invariata. Fix: `spidsaml2.py` calcola un `semantic_hash` (sha256 del metadata NON firmato, prima di `sign_entity_descriptor`) e lo manda a `/internal/spid-metadata-snapshot`; dedup in `internal.py` usa quello, non l'hash del documento firmato.

**Niente `UNIQUE(source, content_hash)` sulla tabella**: con l'hash semantico il contenuto può legittimamente ripetersi nel tempo (ciclo toggle A→B→A riporta lo stesso hash di una riga VECCHIA, non solo dell'ultima) — un vincolo globale blocca in silenzio quell'insert (IntegrityError scambiata per race tra worker), lasciando `is_exposed` su una riga che SATOSA non serve più. Dedup "niente rumore" resta solo a livello applicativo, confronto contro l'ultima riga.

**"Ultima riga" va ordinata per `id.desc()`, non `created_at.desc()`**: due commit ravvicinati possono ricevere lo stesso timestamp (granularità DB), rendendo l'ordinamento per data non deterministico — visto in produzione su `spid_metadata_version`.

`spid_metadata_version` porta anche uno snapshot di `eidas_enabled`/`eidas_environment`/`legal_entity_enabled` per riga: "Esponi" ripristina ANCHE questi toggle (non solo il documento XML) se la riga li ha — altrimenti si rischia di esporre un metadata senza ACS eIDAS mentre il backend ha ancora `ficep_enable=true` attivo.

**Gotcha:** mai hardcodare URL assoluti verso `pagopa-prx.comune.montesilvano.pe.it` (o altra istanza di riferimento esterna) in codice servito in produzione — è solo per confronto/debug (vedi sezione "Relazione con altri repository"). Successo una volta in `satosa_config_generator.py` (`logo_uri` di spid-demo/spid-validator) copiato per errore da lì invece che puntare ad asset locale in `satosa/public/static/`. Se serve un'icona statica, va sempre in `satosa/public/static/` e referenziata con path relativo, mai un dominio esterno (nemmeno GitHub raw — fragile, hotlink).

### Reload SATOSA
Il config-api segnala il reload toccando `/satosa-conf/.reload` (volume condiviso). uWSGI nel container satosa è configurato con `--touch-reload /satosa-conf/.reload` e ricarica i worker gracefully senza caduta delle connessioni. Non è necessario il Docker socket.

### SATOSA OIDC multi-client
La sezione `clients` nel config OIDC di SATOSA è generata da `satosa_generator.py`. Ogni client ha: `client_id`, `client_secret` (hash), `redirect_uris`, `allowed_scopes`. Il generator scrive il file e triggera reload.

Client speciale `__spid_verifica__`: nessun record DB — secret derivato deterministicamente da `SATOSA_HASH_SALT` via HMAC-SHA256. Iniettato nel config SATOSA solo quando almeno un IdP con alias `spid-demo` o `spid-validator` è abilitato.

### Plugin SATOSA generati a runtime
`satosa_config_generator.py` scrive moduli Python in `/satosa-conf/` a ogni rigenerazione config (es. `default_backend_router.py`, `oidc_frontend_ext.py`, `access_log_reporter.py`). Questi file sono caricati da SATOSA via `CUSTOM_PLUGIN_MODULE_PATHS: ["/satosa-conf"]`. Non modificarli direttamente in satosa-conf — vengono sovrascritti al prossimo reload.

### Access log pipeline
Ogni auth SATOSA completata (successo o errore) → `POST http://config-api:8000/internal/access-log` (rete Docker interna, nginx non lo espone, nessuna autenticazione necessaria). Endpoint fire-and-forget: risponde sempre 200, errori DB non bloccano SATOSA.

Colonne tabella `access_log`: `provider_type`, `client_id`, `result`, `error_code`, `idp_entity_id`, `user_type` (PF/PG), `fiscal_number_hash` (HMAC-SHA256 del CF — pseudonimizzazione GDPR). Retention 24 mesi: cron 1° del mese aggrega in `access_stats_monthly` (UNIQUE su year/month/idp/provider/user_type/client), poi cancella righe vecchie. `access_stats_monthly` è forever, no PII.

### Pagina /verifica
Pagina pubblica (no login admin) per validazione AgID. Gate: 404 se nessun IdP con alias `spid-demo` o `spid-validator` è abilitato. Flusso PKCE completo via `__spid_verifica__` client. URL: `https://<hostname>/verifica`. Mandare questo link ad AgID per la sessione di validazione.

### Test satosa/plugins/
`satosa`/`pysaml2` da PyPI sono pacchetti sbagliati: il Dockerfile usa fork pinnati (`peppelinux/pysaml2`, `peppelinux/SATOSA`) via immagine base `ghcr.io/italia/iam-proxy-italia:latest`. `pyeudiw` ha un bug di packaging upstream (sottopacchetti `federation`/`trust`/ecc. assenti dal pacchetto installato). I file in `satosa/plugins/` sono override (`COPY` nel Dockerfile) sopra l'albero upstream clonato a build-time — non moduli autosufficienti.

Unico modo per testarli davvero: build dell'immagine satosa e pytest dentro il container (`docker build -t satosa-test -f satosa/Dockerfile satosa/`, poi `docker run --entrypoint sh satosa-test -c "... PYTHONPATH=/satosa_proxy pytest ..."`, import tipo `from backends.spidsaml2 import ...`). Vedi `.github/workflows/satosa-tests.yml` job `test-satosa-plugins-docker`.

Comando reale che funziona (quello sopra fallisce con `pytest: not found` — niente venv su PATH): `docker run --rm -v "<repo>/satosa/tests:/tests" --entrypoint sh satosa-test -c ". /.venv/bin/activate && pip install -q -r /tests/requirements-test.txt && cd /satosa_proxy && PYTHONPATH=/satosa_proxy pytest /tests/test_spidsaml2.py -v"` — venv del pacchetto fork attivato esplicitamente, test montati da `/tests` (non `/satosa_proxy/tests`), dipendenze installate da `requirements-test.txt`.

Per testare modifiche ai plugin senza rebuild: montali sopra l'immagine (`-v "<repo>/satosa/plugins/spidsaml2.py:/satosa_proxy/backends/spidsaml2.py"`, `-v ".../cieoidc-backend/cieoidc.py:/satosa_proxy/backends/cieoidc/cieoidc.py"`) e usa `--ignore=/tests/test_redis_storage.py` come la CI (quel file fallisce nel container con `No module named 'redis_storage'`, gira nel job pytest separato).

Su Windows/Git Bash, `-v "$PWD/...":...` nel `docker run` non risolve il path — usa `MSYS_NO_PATHCONV=1` e path assoluto `/c/Users/...`.

**Parsing XML da input non fidato (upload admin, ecc.)**: usare sempre `defusedxml.ElementTree`, mai `xml.etree.ElementTree` stdlib (XXE/billion-laughs anche da utente autenticato). Dipendenza già in `config-api/requirements.txt`.

### Disaster recovery (volumi/container azzerati)
Procedura testata end-to-end (volumi `proxy_db_data`/`proxy_satosa_conf` distrutti con `docker compose down -v`, rebuild, restore): `docker compose up -d` → login WebUI → `POST /admin/backup/import` con l'ultimo bundle JSON → **nessun accesso console necessario**, `satosa` si auto-guarisce entro ~1-2 minuti (crash iniziale su cert mancante → `restart: unless-stopped` lo rilancia → al riavvio trova cert/chiavi già scritti dal restore).

Due prerequisiti, entrambi già a posto in questo repo:
- `backup_import` deve scrivere `write_spid_cert()`/`write_jwks_files()` su `/satosa-conf/` (non solo il DB) — `generate_and_write()` da solo non lo fa.
- `nginx` in `docker-compose.yaml` deve dipendere da `satosa` con `condition: service_started`, **non** `service_healthy` — altrimenti deadlock al primo boot da volumi vuoti (nginx aspetta satosa sano, satosa diventa sano solo dopo un restore che passa da nginx) che richiede `docker start <container>` manuale per sbloccare.

### CI/CD
`docker/metadata-action` con `tags:` custom deve includere `type=ref,event=pr`, altrimenti su evento PR i tag sono vuoti (rompe step che dipendono da `steps.meta.outputs.tags`, es. scan Trivy).

Trivy su immagine satosa: gate ristretto a `CRITICAL` (non `HIGH`) — il venv del fork upstream (`iam-proxy-italia` v3.3, ultima release) porta CVE HIGH non ancora patchate a monte, non risolvibili da questo repo. config-api/nginx restano bloccanti su HIGH+CRITICAL. Un CVE CRITICAL reale su dipendenza transitiva (es. `anyio`) va fissato forzando bump esplicito nella riga `pip install` del Dockerfile satosa (stesso pattern usato per `redis`/`sentry-sdk`), non ignorato in `.trivyignore`.

**PR Actions accoppiate** (es. `codeql-action` `init`+`analyze`, stesso SHA/versione su entrambi step): se dependabot le splitta in 2 PR separate, mergiarne una sola rompe il required check `Analyze (python)` (version mismatch tra step). Allinea manualmente lo SHA su entrambi gli step nella stessa PR, chiudi l'altra come ridondante.

**`@dependabot rebase` è no-op se il branch è già up-to-date con main** (non forza rebuild CI — utile per verificare se un fail Trivy era solo timing, patch Debian non ancora rilasciata al momento del build). Usa `@dependabot recreate` per forzare push fresco — ATTENZIONE: chiude la PR corrente e ne apre una NUOVA con numero diverso.

**Mai push diretto su `main`**, nemmeno per fix minimi/urgenti — sempre branch + PR. `main` è protetto (required check CodeQL); il push diretto viene spesso rifiutato se il remote è avanti, ma non affidarsi a quello come rete di sicurezza.

**`gh run view --job X --log-failed`** spesso ritorna solo step di cleanup ("UNKNOWN STEP"), non l'errore vero. Usa `gh run view --job X --log | grep -iE "##\[error\]|CRITICAL"` sul log completo.

`config-api/.coverage` è un file binario tracciato in git (pre-esistente) — non aggiungerlo/modificarlo nei commit, `git checkout -- config-api/.coverage` prima di committare dopo un run locale con `--cov`.

Merge PR: repo usa solo squash (`gh pr merge --squash --delete-branch`), nessun merge commit in storia.

**`main` protetto** (ruleset "Main Branch", `enforcement:active`): required check `Analyze (python)` (CodeQL) SOLO — è l'unico check non path-filtrato. Gli altri (ci.yml/satosa-tests.yml/docker.yml) girano solo se cambia il path relativo (`config-api/**`/`satosa/**`/...) — richiederli come required bloccherebbe per sempre una PR che non tocca quel componente (GitHub non skippa un required check path-filtrato mai partito).
**Tutte le Action pinnate per commit SHA** (`# vX` a commento) in tutti e 5 i workflow — dependabot ecosistema `github-actions` apre PR per bump.
**`dependabot.yml` cooldown**: `default-days: 7` (minimo accettato, valori più bassi restano segnalati come "mancanti" da tool di audit), `semver-major-days: 14`, su tutti gli update block.
**`.trivyignore` a root, wired con `trivyignores:` nello step trivy-action** (mancava — il file esisteva ma non veniva letto). CVE su package `pip/_vendor/*` (es. `setuptools`/`msgpack` vendorizzati DENTRO pip stesso, mai importati dal codice app) sono falsi positivi comuni su immagini `python:3.14-slim` con pip 26.x — verificare con `pip show <pkg>` (→ "not found" se è solo vendored) prima di ignorare o meglio: se pip non serve a runtime (solo l'app WSGI/ASGI), rimuoverlo fisicamente nel Dockerfile (`python -m pip uninstall -y pip setuptools`) elimina il CVE alla radice invece di ignorarlo.
**`gh run rerun --failed` NON rilegge il workflow YAML aggiornato** — resta pinnato alla versione del file al momento del trigger originale. Un fix al workflow richiede un nuovo push/evento (su una PR dependabot: commentare `@dependabot rebase`, aspetta il bot — force-push manuale su branch dependabot è bloccato dal classificatore di sicurezza di Claude Code).
