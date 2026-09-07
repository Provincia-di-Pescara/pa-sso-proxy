# IT-Wallet — Stato integrazione e registrazione (ricerca, nessun codice)

Documento di ricerca preparatorio, non guida operativa: **nessun backend
SATOSA per IT-Wallet esiste ancora in questo repo** (verificato: zero
riferimenti a `wallet`/`itwallet`/`openid4vp` in `satosa_generator.py` o
`satosa/`). A differenza di `docs/cie-oidc-registration.md`/
`docs/spid-registration.md`, qui non c'è ancora una WebUI da usare — solo
i requisiti raccolti per quando si deciderà di costruirla.

## Attori e ruoli

| Ente | Ruolo |
|---|---|
| **AGID** | Regolatore, sorveglianza, registro IT-Wallet, verifica requisiti Relying Party |
| **IPZS** | Gestisce il Trust Anchor tecnico (canale federativo di onboarding), unico fornitore del registro/attestati identificativi |
| **PagoPA** | Fornitore della soluzione wallet pubblica (via app IO) |

Base normativa: DL 2 marzo 2024, n. 19 (istituisce il Sistema IT-Wallet
nel CAD). Le Linee guida definiscono le modalità di accreditamento per i
fornitori privati di soluzioni IT-Wallet — la registrazione **Relying
Party** (verifier, il nostro caso) è un processo distinto e meno
documentato pubblicamente.

**Nessun portale self-service pubblico trovato.** Per l'accreditamento
come Relying Party, il canale attuale è il contatto diretto AGID:
- email: direzione.generale@agid.gov.it
- PEC: protocollo@pec.agid.gov.it

Ambiente di test per operatori privati disponibile da **maggio 2026**
(fonte: stampa specializzata, non verificato su fonte AGID primaria).

## Processo di onboarding federativo (da eid-wallet-it-docs)

Fonte: https://italia.github.io/eid-wallet-it-docs/versione-corrente/en/
(sezione 8, "Federation Entities Onboarding Process").

Prerequisiti tecnici prima della richiesta:
1. Generare almeno 2 coppie di chiavi EC — una per la federazione
   (firma Entity Configuration), una per le operazioni applicative
2. Preparare certificati autofirmati per le chiavi applicative
3. Pubblicare Entity Configuration su `/.well-known/openid-federation`
4. Preparare CSR (PKCS#10) con le sole Federation Entity Keys

Procedura (4 step):
1. Invio richiesta tecnica (Entity ID + JWK + CSR) alla Federation Authority (IPZS)
2. Validazione della configuration ed emissione certificato X.509
3. Recupero Subordinate Statement via endpoint `/fetch`
4. Aggiornamento Entity Configuration con Trust Marks e `authority_hints`

Nessun SLA/tempistica trovata nella doc.

## Variabili di configurazione RP richieste

Fonte: https://italia.github.io/eid-wallet-it-docs/versione-corrente/en/
(sezioni 10.3.4 "RP Entity Configuration", 10.3.5 "RP Metadata").
Struttura molto più complessa del semplice toggle+environment di
`eidas.py` — include materiale crittografico, non solo stringhe.

**RP Entity Configuration** (JWT firmato, esposto su `/.well-known/openid-federation`):
- `iss`/`sub` — entity_id (URL del proxy)
- `iat`/`exp` — timestamp
- `authority_hints` — array, punta al Trust Anchor (IPZS)
- `jwks` — chiavi pubbliche federazione

**Metadata → `federation_entity`** (info organizzative):
- `organization_name`, `homepage_uri`, `contacts`, `tos_uri`, `policy_uri`, `logo_uri`

**Metadata → `openid_credential_verifier`** (capacità tecniche RP):
- `application_type`, `client_id`, `client_name`
- `redirect_uris`, `request_uris`, `response_uris`
- `vp_formats_supported` (es. `dc+sd-jwt`, `mso_mdoc`)
- `encrypted_response_enc_values_supported`
- `jwks` — chiavi applicative (separate da quelle di federazione)

## Cosa serve prima di poter costruire il pannello CRUD

Un pannello che salva solo queste variabili oggi le scriverebbe a vuoto
— nessun backend SATOSA le consumerebbe. Prima di un pannello utile
serve, in ordine:

1. **Backend SATOSA IT-Wallet** — plugin basato su
   `eudi-wallet-it-python` (https://github.com/italia/eudi-wallet-it-python),
   wired in `satosa_generator.py` come nuovo backend (stesso pattern di
   `eidas`/`cie`)
2. **Generazione chiavi** — almeno 2 coppie EC (federazione +
   applicative), stesso pattern di `CIE OIDC → Genera chiavi`
3. **Modello dati** — nuove colonne `EnteSettings` o tabella dedicata
   per i campi sopra (client_name, redirect_uris, vp_formats_supported
   ecc. — non tutti scalari, alcuni sono liste/oggetti)
4. **Solo a quel punto** un pannello WebUI (stesso pattern
   `templates/eidas/config.html.j2` + `routes/eidas.py`) ha senso

## Fonti primarie consultate

- https://italia.github.io/eid-wallet-it-docs/versione-corrente/en/ — Italian Wallet Implementation Profile
- https://github.com/italia/eudi-wallet-it-python — libreria RP di riferimento
- https://italia.github.io/eudi-wallet-it-python/ — API docs
- https://www.agid.gov.it/en/it-wallet — pagina ufficiale AGID (accreditamento provider privati, non RP)
- Ricerca web (non fonte primaria singola): attori AGID/IPZS/PagoPA, timeline test maggio 2026
