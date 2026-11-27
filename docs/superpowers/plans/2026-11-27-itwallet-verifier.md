# IT-Wallet verifier (OpenID4VP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** login IT-Wallet (OpenID4VP, percorso nazionale OpenID Federation) per tutti i client OIDC del proxy, gestito da pannello admin, senza database nuovi.

**Architecture:** backend `pyeudiw` `OpenID4VPBackend` (già nel venv dell'immagine base) sottoclassato da noi per i guard, con storage su redis DB 3 tramite adattatore nostro; config-api genera la config del backend, il router e i dati discovery solo se il wallet è attivo; pannello `/admin/itwallet` per chiavi EC, ambiente, onboarding (CSR) e trust mark.

**Tech Stack:** SATOSA 8.5.1 + pyeudiw (venv upstream), redis, FastAPI + SQLAlchemy + Alembic, Jinja2, `cryptography`.

**Spec:** `docs/superpowers/specs/2026-11-27-itwallet-verifier-design.md`

## Global Constraints

- Nessun servizio/database nuovo: storage `pyeudiw` su `redis://redis:6379/3` (DB 0 CIE, 1 OIDC, 2 anti-replay SPID).
- Wallet spento di default; spento = nessun file `itwallet_backend.yaml`, nessun modulo in `BACKEND_MODULES`, nessuna voce router, nessun `digital_id.itwallet`.
- Nome backend SATOSA `OpenID4VP`; Entity ID `https://<host>/OpenID4VP`; `client_id` `openid_federation:https://<host>/OpenID4VP`.
- Ingresso login: `/Saml2/disco?entityID=wallet` (mai `/spidSaml2/disco`).
- DCQL: credenziale `it-wallet-id`, `dc+sd-jwt`, `vct_values: ["urn:it-wallet:eid:1"]`, un solo `claim_set` `["given_name","family_name","birthdate","place_of_birth","tax_id_code"]`.
- Chiavi EC P-256 (ES256 firma, ECDH-ES cifratura risposta); kid = thumbprint RFC 7638.
- `sym_key` (64 hex) e `subject_id_random_value` derivati con HMAC-SHA256 da `SATOSA_HASH_SALT` con etichette `itwallet-response-code` e `itwallet-subject`; mai salvati, mai valori di esempio upstream.
- Trust handler solo `federation` (niente `x509`, niente `direct_trust_*`); `network.httpc_params.connection.ssl: true`.
- Collaudo/personalizzato = solo `__spid_verifica__`, `__admin_test__` e client con `allow_test_idps`; produzione = tutti i client abilitati. Errore client non ammesso: `TEST_IDP_VERIFICA_ONLY_ERROR`. Scope `legal_entity`: `LEGAL_ENTITY_SPID_ONLY_ERROR`.
- Admin: niente JS inline nei template (`admin.js`), POST chiavi/attivazione sotto `step_up.verify(..., action)`; testi admin solo in italiano.
- Pagine utente (discovery, QR, errori): chiavi in tutti e 5 `satosa/public/static/i18n/<lang>.json`.
- Asset statici solo locali in `satosa/public/static/` (mai hotlink).
- Commit: `git checkout -- config-api/.coverage` prima; trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Comandi di test** (Git Bash, usare `MSYS_NO_PATHCONV=1`):

- config-api: `MSYS_NO_PATHCONV=1 docker run --rm -v "C:/Users/mirko.daddiego/Documents/pa-sso-proxy/config-api:/src" -w /src "$(sed -n 's/^FROM \([^ ]*\).*/\1/p' config-api/Dockerfile | head -1)" sh -c "pip install -q --require-hashes -r requirements-dev.txt && python -m pytest -q <file>"`
- satosa (immagine `satosa-test` costruita con `docker build -t satosa-test -f satosa/Dockerfile satosa/`, plugin montati senza rebuild come in `satosa/CLAUDE.md`): `MSYS_NO_PATHCONV=1 docker run --rm --user 0 -v "C:/Users/mirko.daddiego/Documents/pa-sso-proxy/satosa/tests:/tests" -v "C:/Users/mirko.daddiego/Documents/pa-sso-proxy/satosa/plugins/itwallet_storage.py:/satosa_proxy/backends/itwallet/itwallet_storage.py" -v "C:/Users/mirko.daddiego/Documents/pa-sso-proxy/satosa/plugins/itwallet_backend.py:/satosa_proxy/backends/itwallet/__init__.py" --entrypoint sh satosa-test -c ". /.venv/bin/activate && python -m ensurepip >/dev/null && python -m pip install -q -r /tests/requirements-test.txt && cd /satosa_proxy && PYTHONPATH=/satosa_proxy pytest -q <file>"`

## Review Focus

1. Wallet spento dopo essere stato acceso: file backend rimasto in `/satosa-conf` o voce router residua → `/OpenID4VP/*` deve dare 404 e la tab sparire. Test in Task 8 (`test_disable_removes_backend_file_and_router`).
2. Stessa `response-uri` inviata due volte (retry del wallet, due worker uWSGI): il `response_code` si consuma una sola volta. Test in Task 1 (`test_consume_response_code_once_across_clients`).
3. Redis irraggiungibile: SPID/CIE devono funzionare, il wallet dà pagina d'errore, satosa non va in crash all'avvio. Test in Task 1 (`test_is_connected_false_when_redis_down`) + verifica boot in Task 13.
4. `place_of_birth` oggetto (`{"locality":"Roma"}`) e CF `TINIT-…`: gli applicativi ricevono stringa per il luogo e CF nello stesso formato SPID. Test in Task 3 (`test_place_of_birth_flattened`).
5. Cambio ambiente produzione → collaudo con applicativi di produzione già configurati: devono perdere subito la tab e il backend deve rifiutarli. Test in Task 4 (`test_test_only_blocks_production_client`) e Task 8 (`test_collaudo_writes_test_only_client_list`).

---

## PR A — runtime satosa

### Task 1: storage redis per pyeudiw

**Files:**
- Create: `satosa/plugins/itwallet_storage.py`
- Modify: `satosa/Dockerfile` (COPY in `/satosa_proxy/backends/itwallet/itwallet_storage.py`, accanto alle COPY CIE)
- Test: `satosa/tests/test_itwallet_storage.py` (nel container: serve `pyeudiw.storage.base_storage`)

**Interfaces:**
- Produces: `backends.itwallet.itwallet_storage.RedisStorage(conf: dict, url: str, connection_params: dict | None = None)` sottoclasse di `pyeudiw.storage.base_storage.BaseStorage`; `RedisCache(conf: dict, url: str, connection_params: dict | None = None)` sottoclasse di `BaseCache`. Firma `__init__` uguale a `MongoStorage`/`MongoCache` (così `init_params` resta `url` + `conf` + `connection_params`). `conf` accetta `data_ttl` (secondi, tetto 3600) e `key_prefix` (default `itw:`).

- [ ] **Step 1: censire l'interfaccia** — nel container leggere `pyeudiw/storage/base_storage.py`, `base_cache.py`, `mongo_storage.py`, `db_engine.py` e le chiamate in `pyeudiw/satosa/backends/openid4vp/**` e `pyeudiw/trust/**`; elencare in testa al modulo (docstring) i metodi chiamati dal backend VP e i campi usati da `search_session_by_field`.
- [ ] **Step 2: test che falliscono** — con `fakeredis.FakeRedis` iniettato (parametro privato `_client` o monkeypatch di `redis.Redis.from_url`):
  - `test_init_session_and_get_by_state` (init → `get_by_state(state)["document_id"]` uguale)
  - `test_get_latest_by_session_id_returns_newest`
  - `test_get_by_nonce_state_and_response_kid`
  - `test_update_request_and_response_object_roundtrip`
  - `test_consume_response_code_once_across_clients` (due istanze sullo stesso fakeredis server: prima `True`, seconda `False`)
  - `test_set_finalized_missing_document_raises` (stessa eccezione di Mongo: `ValueError` o `StorageEntryNotFound`, come da censimento)
  - `test_session_ttl_capped_at_3600` (`data_ttl=15768000` → TTL ≤ 3600)
  - `test_trust_attestation_and_anchor_roundtrip`
  - `test_openid4vci_methods_are_noop` (`get_pending_openid4vci_by_session_id` → `None`, `abandon_*` → valore neutro come Mongo con 0 documenti)
  - `test_cache_try_retrieve_overwrite_set`
  - `test_is_connected_false_when_redis_down` (URL verso porta chiusa → `False`, nessuna eccezione)
  - `test_search_session_by_field_unindexed_raises` (campo non indicizzato → eccezione esplicita)
- [ ] **Step 3: eseguire** — comando satosa con `/tests/test_itwallet_storage.py` → FAIL (modulo assente).
- [ ] **Step 4: implementare** — documenti JSON `itw:sess:<document_id>`, indici stringa `itw:idx:state:<state>`, `itw:idx:sid:<session_id>` (sorted set per data → ultimo), `itw:idx:ns:<nonce>:<state>`, `itw:idx:kid:<kid>`, più un indice per ogni campo censito allo Step 1; TTL della sessione su tutte le chiavi collegate; `consume_response_code` = `SADD itw:rc:<document_id> <code>` (1 → `True`) con stesso TTL; modifiche read-modify-write con `WATCH`/`MULTI` (retry ≤ 3) o Lua; trust `itw:trust:<type>:<entity_id>` con TTL = `exp` della chain se presente, altrimenti 86400.
- [ ] **Step 5: eseguire** → PASS.
- [ ] **Step 6: test di contratto** — `test_openid4vp_backend_with_redis_storage`: istanzia `DBEngine` con config `{"redis": {"cache": {module, class, init_params}, "storage": {...}}}` su fakeredis e chiama `init_session` → `update_request_object` → `get_by_state`; PASS.
- [ ] **Step 7: commit** — `feat(satosa): redis storage for pyeudiw OpenID4VP sessions`.

### Task 2: content-type verso pyeudiw

**Files:**
- Modify: `satosa/entrypoint.sh` (argomenti uWSGI, prima delle regole `--log-drain`/`--route-if` esistenti)

- [ ] **Step 1:** aggiungere `--route-if-not 'empty:${CONTENT_TYPE} addvar:HTTP_CONTENT_TYPE=${CONTENT_TYPE}'` con commento: pyeudiw legge `HTTP_CONTENT_TYPE` (presente solo con `uwsgi_pass`), noi usiamo `proxy_pass` HTTP; link alla segnalazione upstream quando aperta.
- [ ] **Step 2: verifica** — `sh -n satosa/entrypoint.sh`; build `satosa-test`, avvio con stack locale e wallet attivo (dopo Task 8): `curl -sk -X POST -H "Content-Type: application/x-www-form-urlencoded" --data "response=x&state=y" https://<host>/OpenID4VP/response-uri` → HTTP 401, non 500; senza wallet un POST qualsiasi su `/` resta invariato.
- [ ] **Step 3: commit** — `fix(satosa): expose Content-Type as HTTP_CONTENT_TYPE for pyeudiw`.

### Task 3: mappatura attributi

**Files:**
- Modify: `satosa/internal_attributes.yaml`
- Test: `satosa/tests/test_internal_attributes.py` (host, solo YAML) e nel container per il luogo di nascita

- [ ] **Step 1: test** — `test_openid4vp_mappings`: `fiscalnumber.openid4vp == ["tax_id_code"]`, `birthdate.openid4vp == ["birthdate"]`, `dateOfBirth.openid4vp == ["birthdate"]`, `placeOfBirth.openid4vp == ["place_of_birth"]`; `test_place_of_birth_flattened` (container): `AttributeMapper(internal_attributes).to_internal("openid4vp", {"place_of_birth": {"locality": "Roma"}})` seguito da `from_internal("openid", …)` dà `place_of_birth` stringa `"Roma"` (se il mapper non lo appiattisce, l'appiattimento va nel backend del Task 4 e il test si sposta lì con lo stesso nome).
- [ ] **Step 2:** FAIL → aggiungere le righe `openid4vp:` → PASS.
- [ ] **Step 3: commit** — `feat(satosa): map IT-Wallet claims to internal attributes`.

### Task 4: backend IT-Wallet con guard

**Files:**
- Create: `satosa/plugins/itwallet_backend.py` (COPY → `/satosa_proxy/backends/itwallet/__init__.py`)
- Modify: `satosa/Dockerfile`, `satosa/plugins/cieoidc-backend/cieoidc.py` (estrarre `_render_legal_entity_error` in funzione condivisa)
- Create: `satosa/plugins/proxy_errors.py` (COPY → `/satosa_proxy/backends/proxy_errors.py`): `render_proxy_error(context, error: dict, status: str = "403") -> Response` (corpo dell'attuale `_render_legal_entity_error`, parametrico sull'errore)
- Test: `satosa/tests/test_itwallet_backend.py`

**Interfaces:**
- Consumes: `backends.spidsaml2.LEGAL_ENTITY_SPID_ONLY_ERROR`, `TEST_IDP_VERIFICA_ONLY_ERROR`, `_legal_entity_requested(context)`, `_requesting_client_id(context)`, `VERIFICA_CLIENT_ID`.
- Produces: classe `backends.itwallet.ItWalletBackend(OpenID4VPBackend)`; chiavi config lette dal generatore (Task 8): `config["itwallet_access"] = {"test_only": bool, "allowed_client_ids": list[str]}`.

- [ ] **Step 1: test** — `test_legal_entity_rejected` (scope `legal_entity` → 403 con testo `error.legal_entity_spid_only`), `test_test_only_blocks_production_client` (`test_only=True`, client `app-x` non in lista → 403 `error.test_idp_verifica_only`), `test_test_only_allows_verifica_and_listed` (`__spid_verifica__` e client in lista → delega a `super().start_auth`), `test_production_allows_any_client`; `cieoidc` continua a passare i suoi test con `render_proxy_error`.
- [ ] **Step 2:** FAIL → implementare `start_auth(self, context, internal_request)` con i due controlli prima di `super()` → PASS (tutti i test satosa: `pytest /tests -q --ignore=/tests/test_redis_storage.py`).
- [ ] **Step 3: commit** — `feat(satosa): IT-Wallet backend with legal-entity and test-only guards`.

### Task 5: pagina QR, errori, i18n, icona

**Files:**
- Create: `satosa/public/templates/qr_code.html` (sostituisce quello upstream: stesso nome perché `pyeudiw` usa `qrcode_template: "qr_code.html"`), `satosa/public/templates/itwallet_error.html`
- Create: `satosa/public/static/itwallet/it-wallet-mark.svg` (copiato dal repo `italia/iam-proxy-italia` v3.9.0 `iam-proxy-italia-project/static/img/IT-Wallet-Mark.svg`, licenza del repo upstream annotata in `satosa/public/static/itwallet/LICENSE`), `satosa/public/static/sso/itwallet-qr.js`
- Modify: `satosa/Dockerfile` (`COPY public/static/itwallet/`), `satosa/public/static/i18n/{it,en,fr,de,es}.json`
- Test: `satosa/tests/test_i18n_catalog.py` (esistente, deve coprire le chiavi nuove), `satosa/tests/test_itwallet_templates.py`

- [ ] **Step 1: censire** — variabili passate da `pyeudiw` ai template (`pre_request_endpoint`, `status_endpoint`, handler errori): nomi esatti per QR (`qrcode_text`, `qrcode_size`, `qrcode_color`, `qrcode_logo_path`, `qrcode_expiration_time`, `state`, `status_endpoint`, `static`… come risultano dal codice).
- [ ] **Step 2: test** — `test_qr_template_renders_with_pyeudiw_context` (render con il contesto censito: contiene il link `haip-vp://` come `href` del bottone same-device e l'elemento QR), `test_qr_template_no_external_urls` (nessun `http(s)://` assoluto negli `src`/`href` statici), `test_error_template_renders` ; catalogo i18n: chiavi `itwallet.qr.title`, `itwallet.qr.instructions`, `itwallet.qr.open_app`, `itwallet.qr.expires_in`, `itwallet.qr.expired`, `itwallet.qr.retry`, `itwallet.qr.cancel`, `itwallet.error.title`, `itwallet.error.generic`, `disco.itwallet.tab`, `disco.itwallet.description`, `disco.itwallet.button`, `disco.itwallet.more_info` in tutte e 5 le lingue.
- [ ] **Step 3:** FAIL → template con lo stile della discovery (`/static/sso/` CSS esistente), QR + bottone "Apri l'app IT-Wallet" (link same-device, mostrato su mobile), conto alla rovescia, polling di `status_endpoint` come nel template upstream; testi via `data-i18n` caricati da `itwallet-qr.js` con la stessa precedenza della discovery (cookie `sso_lang` → `navigator.languages` → `it`; fallback chiave lingua → `en` → `it`) → PASS.
- [ ] **Step 4: commit** — `feat(satosa): branded IT-Wallet QR page with i18n`.

### Task 6: nginx

**Files:**
- Modify: `nginx/templates/proxy.conf.template`

- [ ] **Step 1:** `location = /.well-known/jar-issuer/OpenID4VP` → `proxy_pass` a satosa su `/OpenID4VP/.well-known/jar-issuer` (stessi header/CSP della `location /`, include security headers).
- [ ] **Step 2: verifica** — `docker compose up -d --build nginx` locale: `curl -sk -o /dev/null -w "%{http_code}"` sul path → 200 con wallet attivo, 404 spento; `nginx -t` OK. Burst `sso` (200): polling `/OpenID4VP/status` ogni 2 s per 120 s da un client resta sotto il limite (verificare il valore reale del polling dal template).
- [ ] **Step 3: commit** — `feat(nginx): path-insertion rewrite for OpenID4VP jar-issuer`.

## PR B — config-api

### Task 7: modello, migrazione, chiavi EC

**Files:**
- Create: `config-api/app/models/itwallet.py`, `config-api/alembic/versions/022_itwallet_config.py`
- Modify: `config-api/app/models/__init__.py`, `config-api/app/jwk_generator.py`
- Test: `config-api/tests/test_itwallet_model.py`, `config-api/tests/test_jwk_generator.py`

**Interfaces:**
- Produces: `ItWalletConfig` (`__tablename__ = "itwallet_config"`, riga `id=1`): `enabled: bool=False`, `environment: str|None` (`collaudo`|`produzione`|`personalizzato`), `trust_anchor_url`, `authority_hint_url`, `trust_anchor_jwks: dict|None (JSONB)`, `jwk_federation_id`, `jwk_sig_id`, `jwk_enc_id` (FK `jwk_keys.id`), `organization_name`, `client_name`, `homepage_uri`, `policy_uri`, `tos_uri`, `logo_uri`, `contact_email`, `trust_mark`, `trust_mark_id` (tutti `Text|None`).
- Produces: `generate_ec_jwk(name: str, use: Literal["federation","sig","enc"]) -> JwkKey` (P-256; `alg` = `ES256` per federation/sig, `ECDH-ES` per enc; `public_jwk` solo `kty,crv,x,y,kid,use,alg`; kid RFC 7638 su `{"crv","kty","x","y"}`).
- Produces: `derived_secret(label: str, length: int) -> str` in `config-api/app/itwallet.py` (HMAC-SHA256 di `SATOSA_HASH_SALT`, hex troncato).

- [ ] **Step 1: test** — `test_ec_jwk_public_has_no_private_fields`, `test_ec_jwk_kid_is_rfc7638` (vettore calcolato a mano nel test), `test_derived_secret_stable_and_label_separated` (`len("itwallet-response-code",64)==64`, label diverse → valori diversi), `test_migration_creates_itwallet_config` (Alembic upgrade su DB di test, idempotente come la 021).
- [ ] **Step 2:** FAIL → implementare → PASS (comando config-api).
- [ ] **Step 3: commit** — `feat(config-api): IT-Wallet config model and EC keys`.

### Task 8: generatore

**Files:**
- Modify: `config-api/app/satosa_config_generator.py`
- Create: `config-api/app/itwallet_backend_config.py` (`build_itwallet_backend(cfg: ItWalletConfig, keys: dict[str, dict], hostname: str, redis_url: str, allowed_client_ids: list[str]) -> dict`)
- Test: `config-api/tests/test_itwallet_generator.py`

**Interfaces:**
- Consumes: Task 7 (`ItWalletConfig`, `derived_secret`), Task 1 (`module: backends.itwallet.itwallet_storage`, classi `RedisStorage`/`RedisCache`), Task 4 (`module: backends.itwallet.ItWalletBackend`, `config.itwallet_access`).
- Produces: `itwallet_ready(cfg, keys) -> tuple[bool, str|None]` (motivo in italiano se incompleto: chiavi mancanti, trust anchor vuoto, ambiente non scelto), usato anche dal pannello.

- [ ] **Step 1: test**
  - `test_disabled_writes_nothing` (nessun file, `BACKEND_MODULES` solo SPID/CIE, router `entity_backends == {}`, `digital_id` senza `itwallet`)
  - `test_disable_removes_backend_file_and_router` (file presente da una generazione precedente → rimosso)
  - `test_enabled_backend_yaml` (modulo/nome `OpenID4VP`, endpoint dei 6 path, scope `urn:it-wallet:eid:1`, `response_mode: direct_post.jwt`, DCQL con il solo `claim_set` dei Global Constraints, `trust` con sola chiave `federation`, `authority_hints == [authority_hint_url]`, `trust_marks` con il trust mark se presente, storage `redis://redis:6379/3` con le classi del Task 1, `ssl: true`, `sym_key == derived_secret("itwallet-response-code",64)`, nessuna chiave privata diversa da quelle in DB)
  - `test_enabled_adds_module_router_and_disco` (`/satosa-conf/itwallet_backend.yaml` in `BACKEND_MODULES`, `entity_backends == {"wallet": "OpenID4VP"}`, `digital_id.itwallet.login_url == "/Saml2/disco?entityID=wallet"`)
  - `test_collaudo_writes_test_only_client_list` (`itwallet_access == {"test_only": True, "allowed_client_ids": [...client con allow_test_idps abilitati, "__spid_verifica__", "__admin_test__"]}`; `digital_id.itwallet.test_only is True`)
  - `test_produzione_not_test_only`
  - `test_pyeudiw_logger_not_debug` (blocco `LOGGING` di `proxy.yaml`: logger `pyeudiw` al livello di `SATOSA_LOG_LEVEL`, mai `DEBUG` di default — evita dump di VP/chiavi)
  - `test_incomplete_config_not_written` (enabled ma senza chiavi → come spento + log WARNING con il motivo di `itwallet_ready`)
- [ ] **Step 2:** FAIL → implementare (router: portare dallo spike `entity_backends` in `DefaultBackendRouter`; togliere `ITWALLET_LAB_BACKEND`) → PASS; `python -m pytest -q` intero verde.
- [ ] **Step 3: commit** — `feat(config-api): generate IT-Wallet backend config when enabled`.

### Task 9: pannello admin e onboarding

**Files:**
- Create: `config-api/app/routes/itwallet.py`, `config-api/app/templates/itwallet/config.html.j2`, `config-api/app/itwallet_csr.py` (`build_csr(fed_private_jwk: dict, hostname: str, settings: EnteSettings) -> bytes` PEM)
- Modify: `config-api/app/routes/placeholders.py` (rimuovere `/itwallet`), `config-api/app/main.py` (router), `config-api/app/templates/base.html.j2:56-58` (voce attiva, togliere SOON/disabled)
- Test: `config-api/tests/test_itwallet_routes.py`, `config-api/tests/test_itwallet_csr.py`

**Interfaces:**
- Consumes: Task 7, Task 8 (`itwallet_ready`), `step_up.verify(request, db, password, code, action)`, `generate_and_write`, `reload_satosa`.
- Rotte: `GET /admin/itwallet`; `POST /admin/itwallet/settings` (dati ente/ambiente/URL/TA JWKS); `POST /admin/itwallet/keys/generate` (step-up `itwallet-keys`; con chiavi esistenti richiede `confirm_regenerate=yes`); `POST /admin/itwallet/toggle` (`enabled=yes`, `confirmed=yes`, step-up `itwallet-toggle`; rifiuta se `itwallet_ready` falso); `POST /admin/itwallet/trust-mark`; `GET /admin/itwallet/csr` (download `itwallet-federation.csr`); `GET /admin/itwallet/jwks.json` (solo pubbliche federazione).

- [ ] **Step 1: test** — `test_itwallet_requires_login` (già coperto da `test_every_admin_route_requires_login`: verificare che includa le nuove rotte), `test_toggle_refused_when_incomplete` (messaggio `itwallet_ready`), `test_toggle_requires_step_up_and_confirm`, `test_regenerate_requires_confirmation`, `test_jwks_endpoint_public_only` (nessuna chiave `d`), `test_csr_subject_and_signature` (`CN=<host>`, `O=<org_name>`, `2.5.4.97=PA:IT-<ipa_code>`, `C=IT`, `L=<org_city>`, SAN DNS host, firma verificata con la chiave pubblica federazione), `test_trust_mark_decoded_shows_expiry`, `test_environment_change_warns_onboarding`, `test_itwallet_template_has_no_inline_js` (coperto da `test_csp_templates.py`: aggiungere il template se la lista è esplicita).
- [ ] **Step 2:** FAIL → implementare → PASS; schede: Stato, Configurazione, Chiavi, Onboarding (Entity ID, `client_id`, URL `…/OpenID4VP/.well-known/openid-federation`, JWKS, CSR, Entity Configuration decodificata letta da `SATOSA_INTERNAL_URL`), Trust mark; avviso produzione senza trust mark.
- [ ] **Step 3: commit** — `feat(config-api): IT-Wallet admin panel with onboarding data`.

### Task 10: log accessi e dashboard

**Files:**
- Modify: `config-api/app/satosa_config_generator.py` (`_ACCESS_LOG_REPORTER_PY`, blocco `provider_type`), template dashboard/log accessi dove si elencano i provider
- Test: `config-api/tests/test_access_log_reporter.py`

- [ ] **Step 1: test** — `test_itwallet_provider_type` (`context.target_backend == "OpenID4VP"` → `provider_type == "itwallet"`, `user_type == "PF"`, `fiscal_number_hash` calcolato dal CF `TINIT-…` come SPID); dashboard: `test_dashboard_shows_itwallet_provider` (riga access_log `itwallet` → etichetta "IT-Wallet" nel breakdown).
- [ ] **Step 2:** FAIL → implementare → PASS.
- [ ] **Step 3: commit** — `feat(access-log): track IT-Wallet logins`.

### Task 11: backup

**Files:**
- Modify: `config-api/app/routes/backup.py` (`_export_bundle`, `_restore_bundle`)
- Test: `config-api/tests/test_backup.py`

- [ ] **Step 1: test** — `test_backup_roundtrip_itwallet` (config + 3 chiavi esportate e ripristinate, FK coerenti), `test_restore_bundle_without_itwallet` (bundle vecchio → nessun errore, wallet spento).
- [ ] **Step 2:** FAIL → implementare → PASS.
- [ ] **Step 3: commit** — `feat(backup): include IT-Wallet config and keys`.

### Task 12: discovery

**Files:**
- Modify: `satosa/public/static/disco.html`
- Test: `satosa/tests/test_i18n_catalog.py` (chiavi `disco.itwallet.*` usate), `satosa/tests/test_disco_itwallet.py` (host: parsing HTML/JS statico)

- [ ] **Step 1: test** — `test_itwallet_tab_present_hidden_by_default` (bottone `tab-itwallet` con `style="display:none"`, pannello `panel-itwallet` `hidden`), `test_itwallet_tab_logic` (nel JS: mostrato solo se `digital_id.itwallet.login_url` e `!LEGAL_ENTITY` e (`!itwallet.test_only` o `VERIFICA`) — asserzioni su stringhe del sorgente come i test esistenti della discovery).
- [ ] **Step 2:** FAIL → tab e pannello sul modello eIDAS (icona `/static/itwallet/it-wallet-mark.svg`, bottone "Entra con IT-Wallet" → `login_url`) → PASS.
- [ ] **Step 3: commit** — `feat(disco): IT-Wallet tab`.

### Task 13: documentazione, collaudo end-to-end, pulizia spike

**Files:**
- Modify: `docs/itwallet-registration.md` (riscritto: cosa fa il proxy, dati per la richiesta IPZS/AgID dalla scheda Onboarding, trust mark, limiti), `CLAUDE.md` (sezione IT-Wallet: redis DB 3, content-type, guard, file generati, collaudo = test-only), `publiccode.yml` solo se cambia la descrizione funzionalità
- Create: `docs/itwallet-lab.md` (procedura manuale del lab upstream dallo spike: clone longpaths, init, hosts PowerShell, seed utente issuer, TLS front, registrazione sul TA, giro wallet demo)

- [ ] **Step 1: collaudo** — stack locale (immagini `:local`) collegata al lab upstream come nello spike, wallet attivo in ambiente `personalizzato`: login dal test client admin → `fiscal_number` `["TINIT-RSSMRA85M01H501U"]`, `birthdate`, `place_of_birth` stringa; client senza `allow_test_idps` → pagina `error.test_idp_verifica_only`; scope `legal_entity` → `error.legal_entity_spid_only`; spegnimento → `/OpenID4VP/.well-known/openid-federation` 404 e tab assente; `docker compose stop redis` → login SPID demo da `/verifica` funziona, wallet pagina d'errore.
- [ ] **Step 2: pulizia** — eliminare il branch locale `spike/itwallet-lab`, ripristinare `.env` da `scratchpad/lab/env.backup`, nessun riferimento a `ITWALLET_LAB_BACKEND`.
- [ ] **Step 3: commit** — `docs: IT-Wallet onboarding and lab procedure`.

## Consegna

- PR A (Task 1–6) e PR B (Task 7–13) separate; B dipende da A (moduli e classi satosa). Merge solo su richiesta, con `gh pr merge <n> --auto`.
- Prima del merge di A: aprire la segnalazione upstream `pyeudiw` per `HTTP_CONTENT_TYPE` (link nel commento del Task 2).
