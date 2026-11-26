# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Comandi rapidi

```bash
docker compose up -d --build   # build + avvia stack (in .env: VERIFY_IMAGES=false, immagini locali non firmate)
docker compose logs -f config-api
docker compose logs -f satosa
docker compose restart satosa  # dopo modifica manuale a satosa-conf

# Test (da eseguire nella directory config-api/; dipendenze: pip install --require-hashes -r requirements-dev.txt)
cd config-api && pytest                              # tutti i test
cd config-api && pytest tests/test_satosa_config_generator.py -v  # singolo file
cd config-api && pytest tests/test_eidas.py::test_name -v         # singolo test
```

`docker compose port nginx 8080` (nginx-unprivileged, porta interna 8080) per trovare la porta host esposta (es. `18080`) quando serve `curl`/testare form admin dal terminale — config-api non è esposto direttamente sull'host, solo dietro nginx.

Test flussi SATOSA via script su `http://localhost:<porta>`: il cookie `satosa_state` è `Secure; SameSite=None`, quindi httpx/curl non lo rimandano su http → SATOSA perde lo stato (scope, client) e il comportamento sembra sbagliato. Estrai `satosa_state=...` dal `Set-Cookie` della `/OIDC/authorization` e passalo a mano come header `Cookie`.

`POST /admin/eidas/toggle` da form: checkbox `eidas_enabled=yes` per abilitare (assente = disabilita), **richiede anche `confirmed=yes`** altrimenti redirect a warning senza applicare nulla (stesso `window.confirm()` della UI) — utile saperlo per test via curl/script.

Sessione admin (`app/admin_sessions.py`): cookie con solo `user`+`sid`, stato in memoria del processo (un solo worker uvicorn: con `--workers` va spostato in DB/redis). Logout revoca, riavvio di config-api chiude tutte le sessioni, inattività `SESSION_MAX_AGE` e durata `ADMIN_SESSION_MAX_LIFETIME` misurate lato server. Il middleware `admin_guard_middleware` rifiuta POST/PUT/PATCH/DELETE su `/admin` da altra origine (403: `Sec-Fetch-Site`, poi `Origin`, poi `Referer`, confronto solo host; nessuno dei tre = client non browser, ammesso) e rimanda al login ogni `/admin` non pubblico senza sessione valida (test `test_every_admin_route_requires_login`). Cookie `Secure` (`SESSION_HTTPS_ONLY`, default true; i test lo mettono a false in `conftest.py` prima dell'import di `app.main`). Mai segreti nella sessione (firmata, non cifrata). Secondo fattore: oltre al ban per IP, blocco globale dopo `TOTP_MAX_FAILURES` codici errati (chiave `totp:global` in `login_attempts`).

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

### Metadata IdP

- **SPID aggregate**: scaricato programmaticamente a startup da `https://registry.spid.gov.it/metadata/idp/spid-entities-idps.xml`, cached in `/satosa-conf/spid-entities-idps.xml` (con hash-check). Fallback al file bundled nell'immagine solo se il volume file manca.
- **Altri IdP** (CIE, eIDAS, test): URL metadata per singolo IdP; cron notturno aggiorna DB → rigenera config → reload SATOSA.

Reload graceful uWSGI: zero downtime (worker swap in-flight).

**Metadata scaricati validati prima dell'uso** (`app/saml_metadata.py`, `check_idp_metadata`: defusedxml, radice `md:Entit(y|ies)Descriptor`, almeno un `IDPSSODescriptor` con certificato, max 20 MB): aggregato, fetch per IdP, cache DB e download diretto nel generatore. Non valido → resta la versione precedente (log ERROR). Motivo: XML troncato = `SAMLError` all'avvio del backend → giù tutto SATOSA (anche CIE); pagina HTML con 200 = 0 IdP SPID. **Aggregato SPID: firma AgID verificata** (`verify_aggregate_signature`, `signxml`) col certificato pinnato `config-api/app/certs/agid-spid-metadata.pem` (valido fino al 2034-06-24; override `SPID_AGGREGATE_SIGNING_CERT` = percorso). Si scrive solo il contenuto coperto dalla firma (niente signature wrapping). Firma non valida → file precedente + log ERROR "SPID aggregate scartato": al rinnovo del cert AgID gli IdP restano quelli di prima finché non si aggiorna il PEM, nessun outage. Come ce ne si accorge: workflow `agid-cert-check.yml` (giornaliero, issue `spid-registry` se il cert pubblicato cambia o il pinnato scade entro 90 gg) e banner rosso in dashboard da `/satosa-conf/.spid-aggregate-status.json` (scritto a ogni fetch: aggregato scartato, download fallito, o lista ferma da ≥3 giorni). Nuovo PEM: verificarlo da fonte AgID, non solo dal file scaricato.
`error_code` in access_log: SPID = `<message_key>:<classe eccezione>` (`access_log_error_code`), mai il testo dell'eccezione (può contenere pezzi della risposta SAML); CIE = codice OAuth dell'OP ripulito. `_download_metadata`/`fetch_idp_metadata`: solo http(s) (urllib apriva anche `file://`).

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
| `SATOSA_LOG_LEVEL` | config-api → blocco `LOGGING` di `proxy.yaml` (default `INFO`; mai `DEBUG` in prod, vedi "Log SATOSA") |
| `CF_HASH_KEY` | Alias di SATOSA_HASH_SALT usato in `access_log_reporter.py` generato; generare con `openssl rand -hex 32`, mai committare |

## Relazione con altri repository

- **keycloak-login-proxy** (Provincia-di-Pescara) — progetto precedente Keycloak-based. Fonte per: tema HTML, script Python certificato SPID, lista IdP SPID.
- **GovPay-Interaction-Layer** (Comune-di-Montesilvano) — fonte originale per il backend CIE OIDC. Il codice è stato integrato nel repository e ora risiede in `satosa/plugins/` come codice nativo del progetto. Non è necessario ricopiarlo da sorgenti esterne.

## Note implementative importanti

### Certificato SPID
SubjectDN richiesto da AgID: `CN=<domain>, O=<ente>, 2.5.4.83=<entityId>, 2.5.4.97=PA:IT-<IPA_CODE>, C=IT, L=<città>`. Vedi `keycloak-login-proxy/scripts/manage-spid-cert.py` per implementazione Python con `cryptography`.

### CIE OIDC Federation
Il backend CIE OIDC usa 3 JWK separati: `jwk-federation` (firma entity configuration), `jwk-core-sig` (firma OIDC requests), `jwk-core-enc` (cifratura). Il config-api genera questi keypair e li espone in WebUI con tab separato "Portale CIE" (solo federation key, **solo parte pubblica** `kty/kid/e/n` — verificato accettato dal portale; fino a v0.9.11 esportava anche `d/p/q/...`, mai rimettere i campi privati) e "SATOSA interno" (public).

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

**Callback CIE monouso** (port di iam-proxy-italia v3.4.0, che da noi non arriva perché `authorization_callback_endpoint.py` è un override): la sessione legata a `state` è consumata PRIMA di riscattare il `code` (`consume_session`, in `redis_storage.py` atomico con marker `cie:used:<state>` SET NX); un secondo callback con lo stesso `state` → `Authorization already used`, nessuna richiesta al token endpoint. Upstream cambia questi file? Riportare le modifiche a mano negli override.

**id_token CIE validato oltre la firma** (`validate_id_token_claims` nel callback): `iss` (= `issuer` dell'OP o entity ID della trust chain, slash finale tollerato), `aud` contiene il client (+ `azp` se più audience), `exp`/`iat` con 120 s di tolleranza, `nonce` = quello salvato in sessione all'authorization. Prima solo firma + `at_hash`. Login CIE rotto dopo un aggiornamento dell'OP con log "id_token rifiutato: ..." = guardare il motivo, non togliere il controllo.

**Istanza di riferimento funzionante:** `https://pagopa-prx.comune.montesilvano.pe.it/` (govpay-interaction-layer Comune di Montesilvano). Per debug confrontare `/.well-known/openid-federation` con quella istanza.

### eIDAS
Il nodo eIDAS italiano usa lo **stesso backend SAML2** di SPID (`spid_backend`). La differenza è nel metadata SP: quando `eidas_enabled=True` in `ente_settings`, `satosa_config_generator.py` imposta `ficep_enable: true` in `spidsaml2.py`, che aggiunge ACS index 99 ("eIDAS Natural Person Minimum") e 100 ("eIDAS Natural Person Full") al metadata SP.

**Abilitare eIDAS modifica il metadata SPID** → richiede ri-validazione AgID. La WebUI mostra warning con `window.confirm()` prima di procedere. Verificato in produzione: l'accesso SPID già validato continua a funzionare (ACS 99/100 solo aggiunti); eIDAS funziona solo dopo l'aggiornamento del registro AgID.

URL metadata IdP eIDAS: QA `https://sp-proxy.pre.eid.gov.it/spproxy/idpitmetadata`, Prod `https://sp-proxy.eid.gov.it/spproxy/idpitmetadata`.

**FICEP nel registro SPID**: da novembre 2026 il registro AgID elenca il nodo eIDAS (`https://sp-proxy.eid.gov.it/spproxy/idpit`, senza logo) tra gli IdP SPID. Si gestisce solo dalla tab eIDAS: la sync del registro non lo importa (riga già esistente → disabilitata), la tab "Provider SPID" e la discovery SPID lo escludono (`FICEP_ENTITY_IDS` in `spid_seeder.py`). Guard in `authn_request`: un entity_id in `sp_config.ficep_entity_ids` è rifiutato (`EIDAS_NOT_ENABLED_ERROR`) se eIDAS è spento (`ficep_enable`) o non è l'ambiente configurato (`ficep_entity_id`) — il FICEP è nel metadata aggregato SPID, quindi senza guard sarebbe raggiungibile aprendo a mano l'URL di login.

### SPID persona giuridica
Quando un client OIDC chiede lo scope `legal_entity`, il backend SPID (`spidsaml2.py`) aggiunge all'`AuthnRequest` l'estensione `<spid:Purpose>PG</spid:Purpose>` (Avviso AgID n.18 v.2, identità Tipo 3/4 uso professionale) e imposta `attribute_consuming_service_index` sull'ACS dedicato (index `4`) invece del default index 0. Questo ACS dichiara sia gli attributi persona fisica sia quelli azienda (`companyName`, `registeredOffice`, `ivaCode`); è creato in `__create_metadata` quando `legal_entity_enable: true` in `sp_config` (derivato da `ente_settings.legal_entity_enabled`). Lato OIDC, i claim azienda sono rilasciati solo per lo scope `legal_entity` (non per `profile`), per minimizzazione dati — vedi `extra_scopes` in `_oidc_frontend_yaml`.

**Abilitare persona giuridica modifica il metadata SPID** (nuovo ACS) → richiede ri-validazione AgID, stesso avviso già presente per eIDAS. Verificato in produzione: prima dell'aggiornamento del registro AgID la persona fisica continua a funzionare (ACS 0 già registrato), la persona giuridica fallisce — gli IdP leggono il metadata dal registro AgID, non da `/metadata` del proxy, e non trovano l'ACS index 4. Non è un bug del proxy.

**Flusso persona giuridica = solo SPID.** Con scope `legal_entity`, `SpidSAMLBackend.disco_query` aggiunge `legal_entity=1` all'URL della discovery (`disco.html` è statica, non legge lo stato SATOSA): la pagina nasconde le tab CIE/eIDAS e mostra un avviso. Guard lato server (URL di login aperti a mano): `authn_request` rifiuta l'`entity_id` FICEP e `CieOidcBackend.start_auth` rifiuta CIE, entrambi con la pagina d'errore del proxy (403, `LEGAL_ENTITY_SPID_ONLY_ERROR`), non redirect al client. Motivo: ACS eIDAS 99/100 sono solo "Natural Person" e CIE non ha identità PG — nessuno dei due può restituire i claim aziendali.

### i18n pagine utente
Discovery, pagina di errore e messaggi dei backend in `it/en/fr/de/es`. Fonte unica: `satosa/public/static/i18n/<lang>.json` (chiavi piatte; suffisso `_html` = markup, applicato con `innerHTML` dalla discovery). Server: `satosa/plugins/i18n.py` (`resolve_lang(context)`, `t(lang, key)`); client: stessa logica in `disco.html`. Precedenza: cookie `sso_lang` (tendina) → `ui_locales` OIDC (passato alla discovery come `lang=` da `disco_query`) → `Accept-Language`/`navigator.languages` → `it`. Fallback chiave: lingua → `en` → `it`.
**Gotcha:** `sso_lang` è `SameSite=Lax` → non arriva sull'ACS SPID (POST cross-site dall'IdP). Per questo `authn_request` salva la lingua risolta in `context.state[i18n.STATE_KEY]` e `resolve_lang` la usa subito dopo il cookie. `/verifica` NON manda `ui_locales` (scelta utente: niente lingua forzata, anche in validazione AgID segue il browser) — un `ui_locales` fisso lì batte il browser e sembra "rilevamento lingua rotto".

**Nuova stringa = chiave in tutti e 5 i JSON**: `satosa/tests/test_i18n_catalog.py` (job host di satosa-tests.yml, skip nel container) fallisce su chiavi mancanti, placeholder diversi, markup fuori da chiavi `_html`, chiavi usate in disco/plugin/template ma assenti. `handle_error` prende `message_key`/`troubleshoot_key`, non testo; dettagli tecnici in `detail` (non tradotti, mostrati come codice errore). `lang_context=` risolve la lingua senza fare redirect al client (usato dal blocco persona giuridica).

`eid-<lang>.json` (config-api) = solo dati ente/URL, identici nelle 5 lingue; servito da `--static-map /static/locales=/satosa-conf/locales`. `/verifica` e WebUI admin restano solo in italiano.

### Anti-replay assertion SPID
`allow_unsolicited: True` (i worker uWSGI non condividono `outstanding_queries`), quindi InResponseTo + state non bastano contro il riuso di Response + cookie catturati. Dopo `Saml2ResponseValidator.run()` `spidsaml2.mark_assertions_used` registra gli ID delle assertion (`spid:used:<sha256(issuer|id)>`, SET NX, TTL 24 h) su Redis **DB 2** (`replay_cache_url` nel backend; DB 0 = CIE, 1 = frontend OIDC). Riuso → pagina d'errore. Redis giù → login rifiutato (fail closed: Redis serve comunque al frontend OIDC).

### Storico certificati e metadata SPID/eIDAS
`SpidCert.is_active` (un solo `True` alla volta, applicativo non DB) sostituisce la selezione "ultimo per data" in tutti i punti che leggono il cert attivo (`idps.py`, `dashboard.py`, `eidas.py`, `backup.py`). Storico consultabile in `/admin/certs`: export cert/chiave, riattivazione, eliminazione dei non-attivi.

`spid_metadata_version` = registro dei metadata generati: `spidsaml2.py` invia lo snapshot fire-and-forget a `POST /internal/spid-metadata-snapshot` dopo ogni `__create_metadata`; config-api salva una riga solo se l'**impronta** (`metadata_fingerprint` in `app/metadata_profile.py`) cambia rispetto all'ultima riga generata (ordinata per `id.desc()`, mai `created_at`). L'impronta ignora firma, `ID`/`validUntil`/`cacheDuration`, prefissi XML e whitespace. Niente `UNIQUE(source, content_hash)`: un ciclo A→B→A deve creare la terza riga.

**Gotcha prefissi (risolto, v0.12):** pysaml2 7.5.5 (iam-proxy-italia v3.4.0) non registra più `md`/`ds` all'import → stesso contenuto serializzato `ns0:`/`ns1:` → hash del testo diverso → riga "nuova" a ogni deploy che cambia pysaml2 (visto in prod il 2026-11-05). `spidsaml2.py` registra `METADATA_NS_PREFIXES` prima di creare il metadata; il `semantic_hash` inviato da satosa è ignorato.

**Profilo validato = parametri, non documento** (`spid_metadata_profile`, spec `docs/superpowers/specs/2026-11-10-spid-metadata-validated-profile-design.md`): "Segna validato" fotografa la configurazione ATTUALE (cert + `cert_fingerprint`, dati ente/contatti, toggle eIDAS/ambiente/PG, entityID, impronta dell'ultimo metadata); uno solo `validated`, i precedenti `archived`. La tab "Profilo validato" mostra le differenze parametro per parametro e l'avviso "parametri uguali, documento diverso" (nuova immagine). "Ripristina" riapplica i parametri (anche gli IdP `eidas-qa`/`eidas-prod`, come il toggle eIDAS) e, con conferma `confirm_cert=yes`, riattiva il cert del profilo; poi rigenera. Il cert del profilo validato non si elimina.

**Override solo per metadata caricati a mano**: "Esponi" vale solo per righe `uploaded` (scrive `/satosa-conf/spid_sp_metadata_override.xml`, servito da `_metadata_endpoint`, rifiutato se symlink — `O_NOFOLLOW`). Prima valeva anche per le righe generate e il file bloccava il metadata pubblicato su una versione vecchia: le modifiche successive (es. eIDAS riacceso) non venivano pubblicate. `normalize_metadata_history` (avvio config-api, idempotente) ricalcola le impronte, crea il profilo validato dalla vecchia riga `is_validated` e rimuove l'override se non c'è una riga `uploaded` esposta. `is_validated`/`is_exposed` delle righe generate restano solo per questa migrazione.

**Gotcha:** mai hardcodare URL assoluti verso `pagopa-prx.comune.montesilvano.pe.it` (o altra istanza di riferimento esterna) in codice servito in produzione — è solo per confronto/debug (vedi sezione "Relazione con altri repository"). Successo una volta in `satosa_config_generator.py` (`logo_uri` di spid-demo/spid-validator) copiato per errore da lì invece che puntare ad asset locale in `satosa/public/static/`. Se serve un'icona statica, va sempre in `satosa/public/static/` e referenziata con path relativo, mai un dominio esterno (nemmeno GitHub raw — fragile, hotlink).

### SATOSA OIDC multi-client
La sezione `clients` nel config OIDC di SATOSA è generata da `satosa_generator.py`. Ogni client ha: `client_id`, `client_secret` (hash), `redirect_uris`, `allowed_scopes`. Il generator scrive il file e triggera reload.

`oidc_clients.client_secret_plain` è **cifrato a riposo** (`app/secret_box.py`, `EncryptedString`: Fernet con chiave HKDF da `SATOSA_HASH_SALT`, prefisso `enc:v1:`; righe in chiaro lette come sono e cifrate all'avvio da `encrypt_legacy_rows`). SATOSA vuole il secret in chiaro: lo YAML in `/satosa-conf` resta in chiaro per forza. `client_secret_hash` = sempre bcrypt (anche `__admin_test__`). Il test client admin tiene risultato del login e `id_token` in memoria (`_STORE`), nel cookie solo un riferimento. Redirect URI validate al salvataggio (`validate_redirect_uris`: https, http solo loopback, niente `#`/credenziali/`*`).

**Scope per client applicati da noi, non da SATOSA/pyop**: `allowed_scopes` finisce in `oidc_clients.json` ma né SATOSA né pyop lo leggono, e pyop rilascia anche i claim chiesti col parametro `claims` a prescindere dallo scope. `OIDCFrontendWithEndSession.handle_authn_request` (sorgente generato in `_OIDC_FRONTEND_EXT_PY`) toglie scope non consentiti e chiavi di `claims` fuori dai claim degli scope consentiti (`scope2claims` + `extra_scopes`), PRIMA di `super()` (anche la `oidc_request` salvata nello stato è filtrata); log WARNING "scope/claim non consentiti rimossi". Un applicativo che "perde" dati dopo un deploy = scope mancanti nel client, non un bug (caso reale: `legal_entity` non spuntato → login come persona fisica, nessun errore). Per questo il frontend segnala cosa toglie a `POST /internal/scope-rejected` (thread, fire-and-forget) e la dashboard mostra il banner "Applicativi che chiedono dati non consentiti" (`app/scope_rejections.py`, in memoria, ultimi 7 giorni, azzerato per client al salvataggio del client). `end_session` fa redirect solo verso l'origine (schema+host+porta) di una `redirect_uri` registrata da un client abilitato (prima: open redirect). Test: `tests/test_oidc_frontend_ext.py` (stub satosa/oic).

Client speciale `__spid_verifica__`: nessun record DB — secret derivato deterministicamente da `SATOSA_HASH_SALT` via HMAC-SHA256. Iniettato nel config SATOSA solo quando almeno un IdP con alias `spid-demo` o `spid-validator` è abilitato.

### Plugin SATOSA generati a runtime
`satosa_config_generator.py` scrive moduli Python in `/satosa-conf/` a ogni rigenerazione config (es. `default_backend_router.py`, `oidc_frontend_ext.py`, `access_log_reporter.py`). Questi file sono caricati da SATOSA via `CUSTOM_PLUGIN_MODULE_PATHS: ["/satosa-conf"]`. Non modificarli direttamente in satosa-conf — vengono sovrascritti al prossimo reload.

### Access log pipeline
Ogni auth SATOSA completata (successo o errore) → `POST http://config-api:8000/internal/access-log` (rete Docker interna, nginx non lo espone, nessuna autenticazione necessaria). Endpoint fire-and-forget: risponde sempre 200, errori DB non bloccano SATOSA.

Colonne tabella `access_log`: `provider_type`, `client_id`, `result`, `error_code`, `idp_entity_id`, `user_type` (PF/PG), `fiscal_number_hash` (HMAC-SHA256 del CF — pseudonimizzazione GDPR). Retention 24 mesi: cron 1° del mese aggrega in `access_stats_monthly` (UNIQUE su year/month/idp/provider/user_type/client), poi cancella righe vecchie. `access_stats_monthly` è forever, no PII.

`user_type` (in `_detect_user_type` del reporter generato): PG se ci sono attributi azienda (`companyName`/`ivaCode`) — con SPID Tipo 4 (`Purpose=PG`) `fiscalNumber` è il CF della **persona fisica** che opera, non la P.IVA. Il vecchio criterio "fiscal number di 11 cifre" resta solo come fallback. Gli attributi SPID (anche `companyName`/`ivaCode`/`fiscal_number`) arrivano come **liste** a un elemento: template e client devono gestire sia stringa sia lista. Test del reporter: `tests/test_access_log_reporter.py` carica il sorgente generato stubbando `satosa` in `sys.modules`.

### Pagina /verifica
Pagina pubblica (no login admin) per validazione AgID. Gate: 404 se nessun IdP con alias `spid-demo` o `spid-validator` è abilitato. Flusso PKCE completo via `__spid_verifica__` client. URL: `https://<hostname>/verifica`. Mandare questo link ad AgID per la sessione di validazione.

**IdP di test (demo, validator AgID) solo da `/verifica` e dai client con `allow_test_idps`**: accettano identità inventate, quindi un applicativo di produzione non deve mai poterli usare. Il flag per client (`oidc_clients.allow_test_idps`, form Client OIDC, badge "IdP test" in lista) serve a collaudare un'app col Demo. Discovery: `spid-idps-default.json` li marca `"test": true`, `disco_query` aggiunge `verifica=1` per `__spid_verifica__` e per i client in `sp_config.test_idp_client_ids` (scritto dal generatore, solo client abilitati) e `disco.html` li mostra solo con quel flag. Guard server (URL di login aperti a mano): `authn_request` rifiuta un entity_id presente nei file `sp_config.test_idp_metadata_files` se il client non è ammesso → pagina d'errore del proxy `TEST_IDP_VERIFICA_ONLY_ERROR`. Vale anche per il test client admin (`__admin_test__`). Con solo IdP di test abilitati la discovery degli applicativi usa la lista fallback di produzione.

Selettore persona fisica/giuridica su `/verifica` visibile solo con `legal_entity_enabled`: `subject=pg` aggiunge scope `legal_entity` + claim aziendali richiesti; il generatore dà lo scope `legal_entity` a `__spid_verifica__` solo in quel caso (senza ACS 4 nel metadata il login PG fallirebbe). `subject=pg` con persona giuridica disattivata → ricade silenziosamente su persona fisica.

### Dipendenze pip e parsing XML
Test dei plugin `satosa/plugins/` (solo nel container, venv upstream, venv ripulito): vedi `satosa/CLAUDE.md`.

**Dipendenze pip = file `.in` + lock con hash** (F3): si modificano SOLO i `.in` (`config-api/requirements.in` runtime, `requirements-dev.in` = runtime + test vincolato con `-c requirements.txt`, `satosa/requirements-runtime.in`, `satosa/tests/requirements-test.in`), poi `scripts/compile-requirements.sh` rigenera i `.txt` (pip-compile `--generate-hashes`, dirette + transitive). Lo script compila **dentro container Linux** con la Python di produzione (3.15 config-api, 3.12 satosa = venv upstream): compilare su Windows sbaglia i marker (es. `uvloop` sparisce). Install ovunque con `--require-hashes` (Dockerfile anche `--no-deps` + `pip check`; satosa: `pip check` dopo le rimozioni dal venv upstream, fallisce la build se un pacchetto tenuto perde una dipendenza). Dependabot riconosce l'header pip-compile e aggiorna `.in` + `.txt` insieme. `pip-audit --require-hashes --disable-pip` su dev config-api, test e runtime satosa.

**Parsing XML da input non fidato (upload admin, ecc.)**: usare sempre `defusedxml.ElementTree`, mai `xml.etree.ElementTree` stdlib (XXE/billion-laughs anche da utente autenticato). Dipendenza già in `config-api/requirements.txt`.

### Hardening runtime (F6)
`docker-compose.yaml`: su TUTTI i servizi `no-new-privileges`, `cap_drop: ALL`, `read_only: true` (anchor `x-hardening`). satosa e config-api girano come **uid 10001** (`USER` nei Dockerfile), nginx = `nginxinc/nginx-unprivileged` (uid 101, **porta 8080** nel container; il template ascolta su 8080, compose mappa `${PROXY_HOST_PORT}:8080`): nessuna capability. postgres/redis (ufficiali, partono root) riaggiungono solo `CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID`. Scritture solo su volumi e tmpfs dichiarati; **i tmpfs vanno montati con `:mode=1777`** (senza, root 755 → nginx "conf.d is not writable", app non-root senza /tmp). redis senza persistenza: `/data` in tmpfs.

**Proprietà di `/satosa-conf`**: i Dockerfile di satosa e config-api creano `/satosa-conf` di 10001; un volume nominato vuoto la eredita al primo mount (Docker e Podman), quindi niente chown a runtime. Il servizio one-shot `init-perms` (chown root a ogni avvio, F6) è stato rimosso dopo che aveva sistemato i volumi di produzione pre-F6. **Rollback a un'immagine pre-F6 (root)**: i file che scrive nel volume restano di root e, tornando avanti, le scritture di 10001 falliscono — serve un chown una tantum (es. reintrodurre per un deploy un servizio `user: 0` con `chown -R 10001:10001 /satosa-conf`, come in `b64d62e`).

Servizio one-shot **`verify-images`** (cosign `-dev`, ha la shell): con `VERIFY_IMAGES=true` verifica le firme keyless di `SATOSA_IMAGE`/`CONFIG_API_IMAGE`/`NGINX_IMAGE` (identità `release.yml@refs/(tags/v.*|heads/main)`); fallita → app create ma non avviate. Variabile, non profilo. **Default `true`** (anche con variabile assente): in sviluppo con `docker compose up --build` serve `VERIFY_IMAGES=false` nel `.env` (immagini locali non firmate). `scripts/smoke-stack.sh` scrive il suo env-file (default `false`, `release.yml` passa `true`).

**Segreti obbligatori** con `${VAR:?}`: `POSTGRES_PASSWORD`, `ADMIN_USER`, `ADMIN_PASSWORD`, `SESSION_SECRET`, `SATOSA_HASH_SALT`, `SATOSA_STATE_ENCRYPTION_KEY`, `PROXY_HOSTNAME` — prima i default `changeme-…` facevano partire lo stack con chiavi note. Uno stack Portainer senza una di queste variabili NON si avvia più.

Debug in container non-root: `docker compose exec -u 0 <servizio> sh` se serve root; i test plugin nel container satosa girano con `--user 0` (installano nel venv).

### Test e2e SPID (F8)
`SMOKE_E2E_SPID=true scripts/smoke-stack.sh` (workflow `spid-e2e.yml`): login SPID completo contro spid-saml-check, persona fisica e giuridica. Dettagli e gotcha: `tests/e2e/CLAUDE.md`.

### Disaster recovery (volumi/container azzerati)
Procedura testata end-to-end (volumi DB/`proxy_satosa_conf` distrutti con `docker compose down -v`, rebuild, restore): `docker compose up -d` → login WebUI (con 2FA: enrollment TOTP nuovo, il TOTP non è nel backup) → `POST /admin/backup/import` con l'ultimo bundle cifrato + passphrase + password admin (+ codice TOTP nuovo) → **nessun accesso console necessario**, `satosa` si auto-guarisce entro ~1-2 minuti (crash iniziale su cert mancante → `restart: unless-stopped` lo rilancia → al riavvio trova cert/chiavi già scritti dal restore).

Due prerequisiti, entrambi già a posto in questo repo:
- Bundle sempre cifrato (`app/backup_crypto.py`: AES-256-GCM, scrypt, header come AAD, limiti sui parametri KDF letti dal file); import in chiaro rifiutato (scelta utente, anche se invalida i backup vecchi). Export/import = POST con step-up (`app/step_up.py`: password + TOTP non già usato; fallimenti nel ban per IP). La passphrase non è recuperabile.
- `backup_import` deve scrivere `write_spid_cert()`/`write_jwks_files()` su `/satosa-conf/` (non solo il DB) — `generate_and_write()` da solo non lo fa.
- `nginx` in `docker-compose.yaml` deve dipendere da `satosa` con `condition: service_started`, **non** `service_healthy` — altrimenti deadlock al primo boot da volumi vuoti (nginx aspetta satosa sano, satosa diventa sano solo dopo un restore che passa da nginx) che richiede `docker start <container>` manuale per sbloccare.

### nginx: upstream risolti a runtime
`proxy_pass` passa sempre da variabile (`$config_api_upstream`/`$satosa_upstream`) + `resolver ${NGINX_LOCAL_RESOLVERS} valid=10s`, mai hostname fisso. Con hostname fisso nginx risolve il nome una volta all'avvio: un redeploy (git pull → stack ricreata) che cambia IP a un upstream lascia nginx sul vecchio IP → `502 connect() failed (113: Host is unreachable)` finché nginx non viene riavviato (incidente prod 2026-10-21, config-api irraggiungibile, satosa salvo per caso). `NGINX_LOCAL_RESOLVERS` viene da `/etc/resolv.conf` (entrypoint ufficiale, abilitato da `NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1` nel Dockerfile): funziona sia su Docker (`127.0.0.11`) sia su Podman (aardvark-dns, la prod gira su Podman/RHEL). Non hardcodare `127.0.0.11`: è solo Docker. Healthcheck nginx in compose verifica entrambi gli upstream passando da nginx.

**Header, CSP, rate limit, allowlist admin**: ogni location include `/etc/nginx/snippets/security-headers.conf` (un `add_header` in una location annulla quelli ereditati: niente header a livello server). CSP `/admin` e `/verifica` = `script-src 'self'`: **niente JS inline nei template** (né `<script>` né `onclick`/`onsubmit`/`javascript:`), comportamenti via attributi `data-confirm`/`data-copy`/`data-copy-from`/`data-submit`/`data-tabs`/`data-chip-toggle` gestiti da `config-api/app/static/js/admin.js` (dati per JS: `<script type="application/json">`); `tests/test_csp_templates.py` lo verifica. `'unsafe-inline'` resta solo su `style-src` (attributi `style`). nginx passa `Host $http_host` (con porta) su `/admin`: il controllo CSRF confronta `Origin` con `Host`, e con `$host` su porta non standard il login era rifiutato.

**Autoescape Jinja forzato** (`templates.env.autoescape = True` in `app/jinja_templates.py`): Starlette usa `select_autoescape()` che vale solo per `.html/.htm/.xml`, i nostri `.html.j2` restavano senza escape. Non toglierlo; HTML voluto solo con `|safe` su valori generati da noi.

**Font self-hosted** (GDPR: niente IP dei visitatori a Google/Bunny): `config-api/app/static/fonts/` (servita anche come `/verifica/static/fonts`, perché `/admin/static` può stare dietro `ADMIN_ALLOWED_CIDRS`) e `satosa/public/static/sso/fonts/`, woff2 latin+latin-ext da `@fontsource` 5.3.0 con `fonts.css` e licenze OFL. Font nuovo = file locale, mai `@import`/`<link>` esterni (test lo blocca). `limit_req` zone `admin_login` (`^~ /admin/login`) e `sso`. `ADMIN_ALLOWED_CIDRS` opt-in → `26-admin-access.sh` scrive `conf.d/admin-access.inc` (sempre, anche vuoto: l'include non deve fallire; `.inc` perché nginx.conf include solo `*.conf`). postgres/redis solo su rete `backend` (`internal: true`), nginx solo su `proxy-internal`. Test rate limit in locale: serve un upstream vivo, con upstream assente ogni richiesta aspetta il timeout del resolver e il limite non scatta mai.

### Log SATOSA
Senza `LOGGING` in `proxy.yaml` il fork SATOSA (`proxy_server.make_app`) applica un default **DEBUG hardcoded**, e a DEBUG `generate_configuration_plugin` del backend CIE stampa la config completa, **chiavi private JWK (`jwks_core`/`jwks_federation`) incluse**. `_satosa_logging()` in `satosa_config_generator.py` scrive sempre `LOGGING` (livello da `SATOSA_LOG_LEVEL`, default `INFO`, valore invalido → `INFO`). Log satosa di istanze < v0.9.16 vanno trattati come contenenti segreti.

**Healthcheck fuori dai log di accesso** (rumore: 1 riga ogni 10-30 s per servizio): `satosa/entrypoint.sh` solo per `GET /.well-known/openid-configuration` (da 127.0.0.1: `--log-drain` sulla riga con status 200; con `X-Real-IP` loopback, cioè healthcheck nginx: `--route-if ... donotlog:`, deciso prima della risposta, un fallimento lo logga nginx), nginx `map $access_loggable` (loopback via `$realip_remote_addr`, solo status 200, `/health` e openid-configuration), config-api `app/log_filters.py` (`GET /health` 200 su `uvicorn.access`). Healthcheck fallito = resta nel log. Le stesse richieste degli applicativi restano loggate.

### PostgreSQL 18
`postgres:18` con volume `proxy_db_data_pg18` montato su `/var/lib/postgresql` (non `/data`): dalla 18 l'immagine usa `PGDATA=/var/lib/postgresql/18/docker` e **si rifiuta di partire** se trova dati sul vecchio mount `/var/lib/postgresql/data`.

**Prossima major (19+): serve di nuovo una migrazione dati, e senza shell** (prod = solo Portainer, 2 ambienti, nessun altro ente). Schema usato per 16→18 in v0.9.10 (commit `66e781e`, rimosso in v0.9.11 dopo la migrazione): volume nuovo `proxy_db_data_pgNN` + due servizi one-shot nel compose con script inline in `command:` (niente bind mount; ogni `$` di shell scritto `$$`) — `db-upgrade-dump` (immagine vecchia major) → dump in volume dedicato, `postgres` dipende da lui (`service_completed_successfully`); `db-upgrade-restore` (nuova major, dopo postgres healthy) → `pg_restore --single-transaction` + marker; `config-api` dipende dal restore (altrimenti Alembic/seed popolano il DB vuoto prima). Compose ferma il vecchio postgres PRIMA del dump → serve il ramo "avvio temporaneo sul volume" (`gosu postgres pg_ctl ... -o "-c listen_addresses=''"`). Test da rifare: stack acceso → redeploy (checksum md5 per tabella + sequenze), redeploy ripetuto, installazione nuova, DB nuovo già popolato.

Test locale dello stack con `-p <nome>` separato: l'immagine GHCR `:latest` in cache può essere vecchia di mesi (Alembic "Can't locate revision") → `CONFIG_API_IMAGE=pa-sso-proxy-config-api:local SATOSA_IMAGE=pa-sso-proxy-satosa:local`; un DB ripristinato su volume `satosa-conf` nuovo non ha cert/chiavi (li scrive solo l'import backup WebUI) → satosa 500 "no python application", non è colpa del DB.

### CI/CD e rilascio
Dettagli (workflow, merge queue, `release.yml`, dependabot, autofix pip, Trivy, CodeQL, harden-runner, GitHub App): skill `ci-cd-release` (`.claude/skills/ci-cd-release/SKILL.md`). **Caricarla prima** di toccare workflow, ruleset, `dependabot.yml`, `FROM`/digest dei Dockerfile, o di diagnosticare un run fallito / gestire una PR dependabot. Regole sempre valide:

- **Mai push diretto su `main`**, nemmeno per fix minimi/urgenti — sempre branch + PR (il ruleset lo rifiuta).
- **Merge di una PR**: `gh pr merge <n> --auto` (merge queue, squash imposto). Niente `--squash`/`--admin`.
- **Tag `v*` protetti**: un tag pubblicato non si sposta. Prima di creare un tag: `release.yml` con `dry_run=true` su main.
- **Collaudo prima della produzione = tag pre-release `vX.Y.Z-rc.N`**: pubblica solo `:X.Y.Z-rc.N` e `:sha-…`, mai `:latest` (la produzione non lo vede). Si può mettere su un branch di integrazione non ancora mergiato: il workflow gira con il `release.yml` del commit taggato. Un tag `vX.Y.Z` normale va SEMPRE anche su `:latest` = produzione.
- **Pubblicare = andare in produzione** (Portainer riscarica `:latest` da solo): solo `release.yml` pubblica, niente rebuild senza causa.
- **Aggiornamento immagine base iam-proxy-italia = sempre manuale, mai automatizzarlo** (checklist nella skill).
- `config-api/.coverage` è un binario tracciato: `git checkout -- config-api/.coverage` prima di committare dopo un run con `--cov`.
- Nuova action di terze parti: va aggiunta all'elenco consentito PRIMA del merge; tutte le Action pinnate per commit SHA.
- Mai `pip install pkg==x` inline nei Dockerfile (dependabot non lo vede); mai eccezioni Trivy senza `paths`; CVE CRITICAL reale = bump, non ignore.
