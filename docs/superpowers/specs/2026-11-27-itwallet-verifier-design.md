# IT-Wallet verifier (OpenID4VP) — design

Data: 2026-11-27. Stato: proposta.

## Intento

Gli applicativi dell'ente accettano il login con **IT-Wallet** (app IO o altre soluzioni
IT-Wallet) come oggi accettano SPID, CIE ed eIDAS: nessuna modifica lato applicativo, stessi
claim OIDC (`fiscal_number`, `given_name`, `family_name`, `birthdate`, …).

Perché ora: l'ente vuole chiedere al ministero (IPZS come Federation Authority, AgID per la
registrazione — Determinazione AgID 164/2026, Spazio di Sperimentazione) di fare i test. Per
farlo serve un'istanza che pubblichi una Entity Configuration da verifier e produca i dati di
onboarding (Entity ID, chiavi pubbliche, CSR). Questo lavoro rende il proxy pronto per quella
richiesta e, dopo l'onboarding, per l'uso reale.

## Base di partenza (spike 2026-11-27)

Spike su lab locale iam-proxy-italia v3.9.0 (trust anchor, issuer OpenID4VCI, wallet demo):
il nostro satosa con il backend `pyeudiw` (già nel venv dell'immagine base) ha completato un
login wallet → OpenID4VP → frontend OIDC → client, con `fiscal_number` `TINIT-<CF>` (stesso
formato SPID) e `birthdate`. Problemi trovati, tutti da risolvere qui:

1. `pyeudiw` salva sessioni e cache trust solo su MongoDB (`mongo_storage`/`mongo_cache`).
2. `pyeudiw` legge `context.http_headers["HTTP_CONTENT_TYPE"]` sulla `response-uri`: esiste
   solo se nginx parla a uWSGI con `uwsgi_pass`; noi usiamo `proxy_pass` HTTP → `KeyError`,
   500. Nello spike aggirato con `UWSGI_ROUTE_IF_NOT=empty:${CONTENT_TYPE}
   addvar:HTTP_CONTENT_TYPE=${CONTENT_TYPE}`.
3. Il nostro `satosa/internal_attributes.yaml` non ha la mappatura `openid4vp` per CF, data e
   luogo di nascita: il CF si perdeva.
4. Il router generato non conosce il wallet; l'ingresso deve essere
   `/Saml2/disco?entityID=wallet` (su `/spidSaml2/disco` risponde il backend SPID →
   `UnknownSystemEntity`).
5. Il log accessi registra i login wallet come `provider_type=spid`.

## Obiettivi

- Pannello admin **IT Wallet** (oggi placeholder "SOON") che gestisce tutto: attivazione,
  ambiente, chiavi, dati ente, dati per l'onboarding, trust mark. Spento di default.
- Attivo → il generatore scrive la config del backend OpenID4VP, il router lo instrada, la
  discovery mostra la tab IT-Wallet. Spento → nessuna traccia nella config SATOSA né in
  discovery (come eIDAS e CIE OIDC).
- **Nessun database nuovo**: storage di `pyeudiw` su redis (già nello stack).
- Claim agli applicativi identici a SPID per persona fisica, CF obbligatorio.
- Pagina QR con il nostro aspetto (come la discovery) e le 5 lingue.
- Dati per l'onboarding esportabili dal pannello.

## Non obiettivi

- Emissione di credenziali (OpenID4VCI): siamo solo verifier.
- Percorso europeo EUDIW (access certificate + registration certificate X.509, Trusted
  Lists): la richiesta al ministero passa dal percorso nazionale (OpenID Federation + Trust
  Mark di registrazione). Il trust handler `x509` resta fuori; da riprendere quando le
  regole EUDIW saranno operative.
- Persona giuridica via wallet (non esiste attestato PG): con scope `legal_entity` la tab
  wallet resta nascosta e il backend rifiuta, come per CIE ed eIDAS.
- Attestati diversi dall'IT-Wallet ID (patente, PID EUDIW, mdoc): fuori ora.
- Correggere `pyeudiw` upstream: si propone la correzione (punto 2) a parte, ma qui non si
  dipende da quando arriva.

## Anti-obiettivi (fallimento anche se funziona)

- MongoDB o un altro servizio nello stack.
- Wallet raggiungibile con il pannello spento (anche aprendo a mano gli URL del backend).
- Chiavi private nel bundle di export pubblico o nei log; config `pyeudiw` scritta con le
  chiavi/esempi di upstream (`metadata_jwks`, `sym_key`, `subject_id_random_value` di
  esempio sono pubblici).
- Un applicativo che chiede `legal_entity` e ottiene un login wallet come persona fisica.
- Un riavvio di redis che rompe il proxy (deve perdere solo i login wallet in corso).

## Vincoli

- Stack: nginx (`proxy_pass` HTTP verso uWSGI `--http-socket`), satosa uid 10001
  `read_only`, config-api FastAPI + postgres, redis senza persistenza (tmpfs). Redis DB 0 =
  CIE, 1 = frontend OIDC, 2 = anti-replay SPID.
- `pyeudiw` è quello del venv dell'immagine base (oggi 2.6.0 nell'immagine pubblicata
  `iam-proxy-italia:latest@sha256:bb54…`, mentre il sorgente v3.9.0 dichiara 2.9.0): nessun
  pin nostro, aggiornamento base sempre manuale. Il codice nostro usa solo le interfacce
  pubbliche (`BaseStorage`, `BaseCache`, backend `OpenID4VPBackend`).
- CSP: le pagine servite da satosa hanno CSP minima (`frame-ancestors`/`base-uri`/
  `object-src`), il template QR upstream usa script inline: va bene lì, non sotto `/admin`.
  Il pannello admin segue la regola "niente JS inline" (`admin.js`).
- Admin: step-up/2FA come per le altre sezioni sensibili; POST con controllo origine.
- Generatore: moduli Python scritti in `/satosa-conf` a ogni rigenerazione, plugin statici
  in `satosa/plugins/` copiati nell'immagine (pattern CIE: `redis_storage.py`).
- Nuova stringa utente = chiave in tutti e 5 i JSON i18n (test catalogo).
- Backup cifrato: deve includere config e chiavi wallet (disaster recovery senza console).

## Approcci considerati (storage)

1. **Adattatore redis (scelto).** Classe nostra che implementa `BaseStorage` + `BaseCache` di
   `pyeudiw` su redis DB 3, caricata da `pyeudiw` via `module`/`class` nella config (già
   dinamico, `dynamic_class_loader`). Pro: zero servizi nuovi, stesso schema di CIE/SPID.
   Contro: redis non persistente → un riavvio perde i login wallet in corso (2-6 min) e la
   cache trust (si ricostruisce). Utente: "il riavvio è caso estremo", accettato.
2. Adattatore postgres: persistente, ma satosa oggi non tocca postgres; servirebbero
   credenziali e tabelle condivise con config-api. Scartato.
3. MongoDB: scartato dall'utente (niente DB nuovi).

## Design

### 1. Storage redis per pyeudiw (`satosa/plugins/itwallet_storage.py`)

- `RedisStorage(BaseStorage)` e `RedisCache(BaseCache)`, stesso modulo, URL redis dalla
  config (`redis://redis:6379/3`). Prefisso chiavi `itw:`.
- Sessioni: documento JSON per `document_id` (`itw:sess:<document_id>`) + indici
  secondari a chiave singola per le ricerche usate dal backend: `state`, `session_id`
  (ultima sessione: `get_latest_by_session_id`), `state+nonce`, kid di cifratura della
  risposta, campo generico per `search_session_by_field` sui soli campi effettivamente usati
  dal backend (da censire in implementazione; un campo non indicizzato → errore esplicito,
  non scansione).
- TTL su tutto: sessione = `data_ttl` della config ma con tetto (proposta 1 h: i flussi
  durano minuti; il valore upstream di 6 mesi non serve a noi e su redis in tmpfs è memoria).
  Indici con lo stesso TTL della sessione.
- Atomicità: `consume_response_code` con `SADD` su un set per documento (ritorno 1 = primo
  consumo) o script Lua; `set_finalized`/`update_*`/`set_session_fields` con `WATCH`/
  `MULTI` o Lua per evitare scritture perse tra worker uWSGI.
- Trust (attestation, anchor, source): documenti per `entity_id`, TTL legato a `exp` della
  trust chain quando presente, altrimenti 24 h.
- `RedisCache`: `try_retrieve`/`overwrite`/`set` su `itw:cache:<name>`.
- Metodi OpenID4VCI (`get_pending_openid4vci_by_session_id`, `abandon_openid4vci_*`,
  `add_dpop_proof_and_attestation`) chiamati anche dal backend VP (`abandon_linked_openid`
  6 occorrenze nello spike): implementati in modo coerente (nessuna sessione VCI = no-op
  documentato), non `NotImplementedError` se il backend VP li chiama.
- Redis giù → `is_connected` falso, errori `pyeudiw` normali → pagina d'errore wallet, il
  resto del proxy funziona (SPID/CIE non toccati).
- Test unitari con `fakeredis` (o redis vero nel container dei test satosa), più un test di
  contratto: il backend `OpenID4VPBackend` reale con il nostro storage nel container satosa.

### 2. Content-type (`HTTP_CONTENT_TYPE`)

Regola uWSGI permanente in `satosa/entrypoint.sh`:
`--route-if-not 'empty:${CONTENT_TYPE} addvar:HTTP_CONTENT_TYPE=${CONTENT_TYPE}'`
(prima delle regole di log). Commento con il motivo e il riferimento alla segnalazione
upstream. Proposta upstream separata (`.get()` in `_check_http_post_headers`). Verifica: un
POST `application/x-www-form-urlencoded` alla `response-uri` arriva a `pyeudiw` (401 JWE
non valido, non 500).

### 3. Mappatura attributi (`satosa/internal_attributes.yaml`)

`openid4vp: [tax_id_code]` su `fiscalnumber`, `openid4vp: [birthdate]` su `birthdate` (e
`dateOfBirth`), `openid4vp: [place_of_birth]` su `placeOfBirth`. Nome/cognome già mappati.
`place_of_birth` arriva come oggetto (`{"locality": "Roma"}`): rilasciare la `locality`
come stringa se il frontend OIDC non lo gestisce (da verificare in implementazione; i
template client gestiscono già stringa o lista).

### 4. Modello dati e pannello (config-api)

Tabella `itwallet_config` (riga unica `id=1`, migrazione Alembic 022), pattern `CieConfig`:

- `enabled` (bool, default false), `environment` (`collaudo` | `produzione` | `personalizzato`).
- `trust_anchor_url`, `authority_hint_url` (modificabili; valori IPZS: vedi §11),
  `trust_anchor_jwks` (JSON opzionale, chiavi del TA
  da fissare se l'ambiente lo richiede).
- `jwk_federation_id`, `jwk_sig_id`, `jwk_enc_id` → `jwk_keys` (EC P-256, non RSA: ES256 per
  firma, ECDH-ES per cifratura risposta). `jwk_generator.py` estesa a EC con kid RFC 7638.
- `organization_name`, `homepage_uri`, `policy_uri`, `tos_uri`, `logo_uri`, `contacts` (PEC
  ente come per CIE) → `federation_entity`; `client_name` → metadata verifier. Default dai
  dati ente.
- `trust_mark` (JWT incollato dopo l'onboarding, come CIE), `trust_mark_id`.
- Segreti derivati, non salvati: `response_code.sym_key` e
  `user_attributes.subject_id_random_value` = HMAC da `SATOSA_HASH_SALT` con etichette
  distinte (pattern `__spid_verifica__`).

Pannello `/admin/itwallet` (sostituisce il placeholder, toglie "SOON"):

- Stato e attivazione (toggle con conferma; attivare senza chiavi o senza trust anchor →
  errore chiaro, non config rotta).
- Ambiente e URL trust anchor.
- Chiavi: genera tutte / rigenera singola (conferma: invalida l'onboarding).
- Dati ente per i metadata.
- **Onboarding** (scheda dedicata): Entity ID (`https://<host>/OpenID4VP`), `client_id`
  (`openid_federation:https://<host>/OpenID4VP`), URL Entity Configuration, JWKS pubblico
  federazione (solo `kty/crv/x/y/kid/use/alg`, mai privati), download **CSR PKCS#10** firmata
  con la chiave di federazione (richiesta dal processo di onboarding IPZS), link
  all'anteprima della Entity Configuration decodificata.
- Trust mark: campo per incollarlo; mostrato decodificato con scadenza.
- Rotte POST sotto step-up dove toccano chiavi; template senza JS inline.

### 5. Generatore

Se `itwallet_config.enabled` e completo:

- scrive `/satosa-conf/itwallet_backend.yaml` (nome backend `OpenID4VP`, modulo
  `pyeudiw.satosa.backends.openid4vp.openid4vp.OpenID4VPBackend`), costruito da zero da
  config-api (non copiando l'esempio upstream): endpoint upstream (`/pre-request`,
  `/request-uri`, `/response-uri`, `/status`, `/redirect-uri`; niente `jar_issuer`: in pyeudiw
  2.9.0 pubblica le chiavi private),
  `authorization` (`haip-vp`, scope `urn:it-wallet:eid:1`, `direct_post.jwt`), DCQL con
  **un solo `claim_set` che include `tax_id_code`**, `metadata` verifier, trust solo
  `federation` (TA, authority hints, trust mark, jwks federazione), `storage` = classi del
  punto 1 su `redis://…/3`, `network.httpc_params.connection.ssl: true`;
- aggiunge il backend a `BACKEND_MODULES`;
- router: `entity_backends: {"wallet": "OpenID4VP"}` (lo spike ha già il codice:
  `DefaultBackendRouter` con mappa entità → backend);
- `eid-<lang>.json`: `digital_id.itwallet.login_url = /Saml2/disco?entityID=wallet`.

Spento: niente file backend (rimosso se presente), niente modulo, niente voce router, niente
`login_url` → `/OpenID4VP/*` risponde 404 come un backend inesistente.

### 6. Discovery e pagina QR

- `disco.html`: tab "IT-Wallet" (icona ufficiale IT-Wallet in `satosa/public/static/`,
  mai hotlink) mostrata solo con `login_url` e non con `legal_entity=1`; pannello con
  descrizione e bottone "Entra con IT-Wallet". Niente scelta del wallet (la lista di
  upstream è finta): il QR/link è unico, lo apre il wallet installato.
- Pagina QR: template nostro (`satosa/templates/` o override del `qr_code.html` upstream)
  con lo stile della discovery, i18n con `i18n.py` (5 lingue), QR + link same-device
  (`haip-vp://`) su mobile, polling dello stato già fornito da `pyeudiw` (`/status`).
- Pagine d'errore `pyeudiw` (`error.html`, `authorization_error.html`) ricondotte alla
  pagina d'errore del proxy dove possibile.

### 7. Guard e log

- Persona giuridica: con scope `legal_entity` il backend wallet rifiuta con
  `LEGAL_ENTITY_SPID_ONLY_ERROR` (stesso schema di `CieOidcBackend.start_auth`), via
  sottoclasse nostra del backend o micro-service prima del routing.
- Access log: `provider_type = "itwallet"` (riconoscendo il backend `OpenID4VP` nel
  reporter generato), `user_type = PF`, `idp_entity_id` = issuer della credenziale se
  disponibile, `fiscal_number_hash` come SPID. Dashboard e statistiche mensili: nuovo tipo
  visibile senza rompere i grafici esistenti.
- Log `pyeudiw` a INFO senza dump di VP o chiavi (verificare il livello con
  `SATOSA_LOG_LEVEL`).

### 8. nginx

- ~~Rewrite path-insertion `/.well-known/jar-issuer/OpenID4VP`~~: rimossa (endpoint
  `jar_issuer` non configurato, pyeudiw 2.9.0 vi pubblica le chiavi private).
- `/OpenID4VP/*` sotto il rate limit `sso` esistente (location `/`); la `response-uri`
  riceve POST dal wallet (server-to-server) e lo `status` è interrogato dal browser in
  polling: verificare che `burst` regga il polling.

### 9. Backup, documentazione, test

- Backup/import: `itwallet_config` + chiavi come per CIE.
- `docs/itwallet-registration.md` riscritto: cosa fa il proxy, come compilare la richiesta
  (dati dalla scheda Onboarding), come incollare il trust mark, limiti.
- CLAUDE.md: sezione IT-Wallet (storage redis DB 3, content-type, guard PG, file generati).
- Test: config-api (modello, pannello, generatore acceso/spento, CSR, segreti derivati, log),
  satosa (storage redis, router, guard PG, catalogo i18n), smoke: con wallet spento nulla
  cambia. E2E wallet automatico fuori scopo (serve il lab upstream); la procedura manuale
  del lab dello spike va in `docs/` per il collaudo.

### 10. Collaudo e applicativi di produzione (decisione utente)

In ambiente `collaudo` (e `personalizzato`, es. lab) il wallet accetta credenziali di
prova: trattato come gli IdP di test SPID. La tab IT-Wallet e il backend sono ammessi solo
per `__spid_verifica__` (`/verifica`), `__admin_test__` e i client con `allow_test_idps`
(stesso flag e badge "IdP test" già esistenti). Discovery: `itwallet.test_only` nell'`eid`
JSON + flag `verifica=1` già passato da `disco_query` → tab visibile solo lì. Guard server:
`entityID=wallet` per un client non ammesso → pagina d'errore del proxy
`ITWALLET_TEST_ONLY_ERROR` (chiavi `error.itwallet_test_only*`, anche aprendo l'URL a mano). In `produzione` il wallet vale
per tutti i client abilitati. Il cambio ambiente rigenera config e router.

### 11. Scelte del progettista (verificabili in lettura)

- **Versione**: IT-Wallet Technical Specifications 1.4.7 LTS (percorso nazionale), con il
  `pyeudiw` del venv dell'immagine base (oggi 2.6.0). Lo storage redis implementa la
  `BaseStorage` di quella versione; un test di contratto nel container satosa (backend
  reale + nostro storage) fallisce se un aggiornamento della base cambia l'interfaccia.
  Formato del `client_id` (`openid_federation:https://<host>/OpenID4VP`), schema
  same-device (`haip-vp://`), DCQL, scope `urn:it-wallet:eid:1` e nomi claim
  (`tax_id_code`): quelli che produce `pyeudiw`, non riscritti da noi. Verificare in
  implementazione se l'immagine pubblicata v3.9.0 ha davvero 2.6.0 contro 2.9.0 del
  sorgente; un bump della base resta un passo manuale separato.
- **URL IPZS**: non pubblici, arrivano con l'onboarding. Collaudo e produzione senza
  default: campi vuoti, attivazione bloccata finché non sono compilati. Preset
  `personalizzato` per il lab upstream (`http://trust-anchor.example.org:5002`). Il JWKS del
  TA si può fissare (campo opzionale), altrimenti si usa quello pubblicato dal TA.
- **CSR**: PKCS#10 firmata con la chiave di federazione EC; soggetto come il certificato SPID
  dell'ente: `CN=<host>`, `O=<ente>`, `2.5.4.97=PA:IT-<IPA_CODE>`, `C=IT`, `L=<città>`;
  SAN DNS `<host>`. Da confrontare con il modulo IPZS quando arriva: il generatore del CSR
  è isolato in una funzione per adattarlo senza toccare il resto.
- **Trust mark**: attivazione permessa senza trust mark in collaudo/personalizzato; in
  produzione permessa con avviso evidente (il wallet può rifiutare un verifier senza
  trust mark di registrazione).
- **Chiavi e ambiente**: una entity per istanza, stesse chiavi al cambio ambiente; il
  pannello avvisa che l'onboarding va rifatto per l'ambiente nuovo. Rigenerare le chiavi
  invalida l'onboarding (conferma esplicita).

## Lasciato al builder

- Struttura interna delle chiavi redis e scelta Lua vs `WATCH`.
- Campi effettivamente usati da `search_session_by_field` (censire dal codice `pyeudiw`).
- Layout del pannello, testi (in italiano, admin non tradotto).
- Se l'override del template QR passa da `template_folder` nostro o da copia sopra quello
  upstream.
