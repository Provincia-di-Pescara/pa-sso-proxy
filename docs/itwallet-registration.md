# IT-Wallet — Verifier (Relying Party) e onboarding

Il proxy può accettare l'IT-Wallet come terzo metodo di accesso (accanto a
SPID e CIE): il cittadino inquadra un QR con l'app, presenta la credenziale
(IT-Wallet ID, SD-JWT) e l'applicativo riceve gli stessi claim OIDC di SPID
(`given_name`, `family_name`, `birthdate`, `place_of_birth`, `fiscal_number`).
Il backend è `pyeudiw` (OpenID4VP) dentro SATOSA; la configurazione si fa da
WebUI `/admin/itwallet`. Procedura per provarlo in locale senza
accreditamento: `docs/itwallet-lab.md`.

## Cosa fa il proxy

- Abilitazione dalla scheda **Stato**: il backend viene generato solo con
  configurazione completa (`itwallet_ready`), altrimenti IT-Wallet resta spento
  e la tab sparisce dalla discovery.
- **Trust anchor non serve per iniziare**: in `collaudo`/`personalizzato` si
  attiva anche senza; la Entity Configuration viene pubblicata (con
  `authority_hints` vuoto) così IPZS la può leggere durante l'onboarding. Il
  login col wallet funziona solo dopo aver inserito il trust anchor ricevuto.
  In `produzione` il trust anchor è obbligatorio.
- Chiavi: rigenerarle non cancella le precedenti, che restano nello
  **Storico chiavi** e si riattivano (tornano JWKS e CSR di quel set). Chiavi e
  attivazione chiedono solo una conferma.
- Chiavi EC P-256 generate da config-api (federazione + applicative); i
  segreti derivati vengono da `SATOSA_HASH_SALT`.
- Sessioni OpenID4VP su Redis DB 3 (chiavi `itw:<hash>:`, TTL <= 1 h; l'hash
  dipende da ambiente e trust anchor, così cambiandoli trust e cache in
  memoria ripartono da zero e un issuer di collaudo non vale in produzione).
  Redis senza persistenza: un riavvio perde solo i login wallet in corso.
- **Solo persona fisica**: con scope `legal_entity` il login IT-Wallet è
  rifiutato (il wallet non ha identità PG).
- Ambienti `collaudo`/`personalizzato` = **solo client di test** (`/verifica`,
  client admin di test a livello backend, client con `allow_test_idps`);
  `produzione` = tutti i client abilitati. Il client di test admin non vede la
  tab in modalità test (il guard server resta il confine). Un client non
  ammesso riceve la pagina d'errore `error.itwallet_test_only`.
- **Dove provare il wallet in collaudo**: `https://<PROXY_HOSTNAME>/verifica` è
  sempre raggiungibile (non serve abilitare gli IdP SPID Demo/Validator) e il
  suo client `__spid_verifica__` è sempre tra quelli ammessi dal wallet in
  `collaudo`/`personalizzato`. In alternativa: un client con
  `allow_test_idps`.
- Access log con `provider_type=itwallet`; configurazione e chiavi nel backup.

## Attori e ruoli

| Ente | Ruolo |
|---|---|
| **AgID** | Regolatore, sorveglianza, registro IT-Wallet, verifica requisiti Relying Party |
| **IPZS** | Gestisce il Trust Anchor tecnico (canale federativo di onboarding) e gli attestati identificativi |
| **PagoPA** | Fornitore della soluzione wallet pubblica (app IO) |

Base normativa: DL 2 marzo 2024, n. 19 (Sistema IT-Wallet nel CAD). Per la
sperimentazione: **Determinazione AgID 164/2026, Spazio di Sperimentazione**.
Contatti AgID: direzione.generale@agid.gov.it, PEC protocollo@pec.agid.gov.it.
Non risulta un portale self-service pubblico per i Relying Party.

## Percorso di onboarding (nazionale, OpenID Federation)

Fonte: https://italia.github.io/eid-wallet-it-docs/versione-corrente/en/
(sezione 8, "Federation Entities Onboarding Process"; 10.3.4/10.3.5 per
Entity Configuration e metadata RP).

1. Dalla scheda **Onboarding** di `/admin/itwallet` si ricavano i dati della
   richiesta: Entity ID (`https://<PROXY_HOSTNAME>/OpenID4VP`), `client_id`,
   URL dell'Entity Configuration (`/OpenID4VP/.well-known/openid-federation`),
   JWKS di federazione, **CSR** (PKCS#10 sulle sole Federation Entity Keys),
   anteprima dell'Entity Configuration EC.
2. Inviare la richiesta tecnica (Entity ID + JWK + CSR) alla Federation
   Authority (IPZS) tramite il canale indicato da AgID per lo Spazio di
   Sperimentazione.
3. Validazione ed emissione del certificato X.509; recupero del Subordinate
   Statement via `/fetch`.
4. Inserire nella scheda **Trust mark** il trust mark di registrazione
   rilasciato (non generabile autonomamente) e impostare Trust Anchor /
   `authority_hints`; l'Entity Configuration pubblicata viene aggiornata.

Nessun SLA trovato nella documentazione.

## Limiti e punti aperti

- **Entity Configuration `iss`/`sub`**: oggi
  `openid_federation:https://<host>/OpenID4VP` (comportamento di pyeudiw,
  identico allo spike di laboratorio). **Da verificare con IPZS durante
  l'onboarding** se il prefisso è accettato.
- **SICUREZZA - endpoint `jar_issuer`**: in pyeudiw 2.9.0 l'endpoint
  `jar_issuer` pubblica `metadata_jwks` comprensivo della parte privata `d`.
  Non è configurato di proposito. Non riattivarlo senza una sottoclasse che
  esponga solo la parte pubblica. Segnalazione upstream da aprire. Nessuna
  regola nginx `/.well-known/jar-issuer/...`: va aggiunta solo insieme a un
  endpoint sicuro.
- Il codice fiscale arriva come `TINIT-<CF>` dal claim `tax_id_code`
  (opzionale nel DCQL del verifier): gli applicativi lo ricevono in
  `fiscal_number` come lista a un elemento.
- `place_of_birth` è appiattito a `["<località>"]` e arriva all'applicativo solo
  se il client chiede quel claim.
- Credenziali del wallet di test a vita breve (vedi lab).
- Ambiente di test per operatori privati dichiarato da maggio 2026 (fonte
  stampa, non primaria).

## Fonti primarie consultate

- https://italia.github.io/eid-wallet-it-docs/versione-corrente/en/ — Italian Wallet Implementation Profile
- https://github.com/italia/eudi-wallet-it-python — libreria RP (pyeudiw)
- https://italia.github.io/eudi-wallet-it-python/ — API docs
- https://www.agid.gov.it/en/it-wallet — pagina ufficiale AgID
