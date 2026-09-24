# 2FA (TOTP) per l'admin WebUI

Data: 2026-09-24

## Contesto

L'accesso alla WebUI (`/admin/*`) è protetto da un'unica coppia di credenziali letta da env
(`ADMIN_USER` / `ADMIN_PASSWORD`, `app/main.py` `login_post`). A login riuscito la sessione
(`SessionMiddleware`, cookie firmato con `SESSION_SECRET`, non cifrato) riceve `user` e
`last_activity`; ogni route admin verifica la presenza di `session["user"]`. Esiste già un
ban per IP dopo troppi tentativi falliti (`app/rate_limiter.py`, tabella `login_attempts`).

La WebUI controlla certificato/chiave SPID, chiavi CIE, client OIDC: la sola password è un
singolo punto di compromissione.

## Obiettivo

1. Secondo fattore **TOTP** (RFC 6238, app authenticator) obbligatorio per l'admin.
2. **Enrollment forzato**: al primo login con password (o dopo un reset) l'admin non accede ad
   alcuna pagina finché non ha attivato il TOTP.
3. **Reset** del TOTP (telefono perso) via comando console **e** via variabile `.env`.
4. **Disattivazione** del 2FA via variabile `.env` (sviluppo locale).

Fuori scope (YAGNI): codici di recupero, pagina "Sicurezza" per rigenerare il TOTP da UI,
multi-admin, WebAuthn/passkey, OTP via email.

## Variabili d'ambiente

| Variabile | Default | Effetto |
|---|---|---|
| `ADMIN_2FA_ENABLED` | `true` | Solo il valore esplicito `false` (case-insensitive) disattiva il 2FA. Assente/qualsiasi altro valore = attivo. |
| `ADMIN_2FA_RESET` | `false` | Se `true`, all'avvio di config-api cancella il TOTP configurato. |

Entrambe lette **a runtime** tramite funzioni (`is_2fa_enabled()`, `is_2fa_reset_requested()`
in `app/admin_2fa.py`), non costanti a import-time — i test le sovrascrivono con `monkeypatch`.

Aggiunte a `.env.example` (con commento esplicito "`false` SOLO per sviluppo locale") e
passate a config-api in `docker-compose.yaml` (`${ADMIN_2FA_ENABLED:-true}`,
`${ADMIN_2FA_RESET:-false}`).

## Modello

Nuova tabella `admin_totp` (`app/models/admin_totp.py`), riga singleton `id=1` (stesso pattern
di `EnteSettings`):

| Colonna | Tipo | Note |
|---|---|---|
| `id` | Integer PK | sempre 1 |
| `secret_enc` | Text, not null | secret base32 cifrato Fernet |
| `confirmed_at` | DateTime(tz), nullable | NULL = enrollment in corso, non ancora valido per il login |
| `last_used_counter` | BigInteger, nullable | time-step dell'ultimo codice accettato (anti-replay) |
| `created_at` | DateTime(tz), server_default now() | |

Migrazione Alembic `019_admin_totp.py` (down_revision `018`), con lo stesso guard
`_existing_tables()` delle migrazioni precedenti.

### Cifratura del secret

Chiave Fernet derivata da `SESSION_SECRET` via HKDF-SHA256 (`cryptography`, già dipendenza),
`info=b"pa-sso-proxy admin-totp"`, 32 byte → base64 urlsafe. Nessuna nuova variabile.

Se `SESSION_SECRET` cambia, il secret non è più decifrabile (`InvalidToken`): il login viene
**bloccato** con messaggio "Secret 2FA non decifrabile (SESSION_SECRET cambiato?). Esegui il
reset 2FA da console." — **mai** re-enrollment silenzioso, che permetterebbe a chi conosce solo
la password di legare un proprio dispositivo.

## Modulo `app/admin_2fa.py`

Logica pura, senza dipendenze FastAPI, testabile in isolamento:

- `is_2fa_enabled() -> bool`, `is_2fa_reset_requested() -> bool`
- `encrypt_secret(secret) -> str`, `decrypt_secret(token) -> str` (solleva `TotpSecretError`)
- `async get_totp(db) -> AdminTotp | None`
- `async get_or_create_pending(db) -> tuple[AdminTotp, str]` — riusa la riga non confermata se
  esiste (reload pagina di setup = stesso QR), altrimenti ne crea una con `pyotp.random_base32()`
- `async verify_code(db, row, code) -> bool` — `pyotp.TOTP.verify` con `valid_window=1`
  (±30s); calcola il time-step del codice accettato e lo rifiuta se `<= last_used_counter`;
  se valido aggiorna `last_used_counter` (e `confirmed_at` se NULL) e fa commit
- `async reset_totp(db)` — cancella la riga
- `provisioning_uri(secret, username, issuer)` — issuer = nome ente da `EnteSettings` se
  presente, altrimenti `"PA SSO Proxy"`
- `qr_svg(uri) -> str` — SVG inline generato con `segno` (nessun CDN, nessun JS)

Nuove dipendenze in `config-api/requirements.txt`: `pyotp`, `segno` (versioni pinnate).

## Flusso di login

Stato intermedio in sessione: `pending_2fa = {"user": <username>, "ts": <epoch>}`, validità
**5 minuti**. `session["user"]` viene impostato **solo** dopo il secondo fattore, quindi tutte
le route admin esistenti restano protette senza modifiche.

1. `POST /admin/login`, password corretta:
   - 2FA disattivato → comportamento attuale (imposta `user`, redirect `/admin/`).
   - 2FA attivo → `session.clear()`, imposta `pending_2fa`, poi:
     - riga confermata presente → redirect `/admin/login/2fa`
     - nessuna riga o riga non confermata → redirect `/admin/login/setup`
     - `clear_attempts` **non** viene chiamato qui (solo dopo il TOTP valido).
2. `GET/POST /admin/login/2fa` — form codice 6 cifre.
3. `GET/POST /admin/login/setup` — QR + secret in chiaro (inserimento manuale) + form codice.
4. Codice valido (sia 2fa sia setup) → `clear_attempts`, `session.clear()`, imposta `user` e
   `last_activity`, redirect `/admin/`.

Regole comuni a `/admin/login/2fa` e `/admin/login/setup`:

- `pending_2fa` assente o scaduto → `session.clear()`, redirect `/admin/login`.
- 2FA disattivato → redirect `/admin/login`.
- IP bannato (`is_ip_banned`) → pagina con errore, status 429, nessuna verifica.
- Codice errato → `record_failed_attempt` (stesso contatore/ban del login password), errore
  "Codice non valido", `pending_2fa` resta valido fino alla scadenza.
- Secret non decifrabile → errore bloccante (vedi sopra), nessun accesso.
- `/admin/login/setup` con riga già confermata → redirect `/admin/login/2fa` (non si può
  sovrascrivere un TOTP attivo passando dal setup).
- Input codice: spazi rimossi, accettate solo 6 cifre.

I nuovi path sono sotto `/admin/login/…`, già esclusi da `admin_session_expiry_middleware`.
Le route stanno in un nuovo router `app/routes/login_2fa.py`; template
`login_2fa.html.j2` e `login_setup.html.j2`, stesso layout di `login.html.j2`.

## Reset

- **Console**: `docker compose exec config-api python -m app.cli reset-2fa` — nuovo modulo
  `app/cli.py` (argparse, sottocomando `reset-2fa`), usa `AsyncSessionLocal`, chiama
  `reset_totp`, stampa esito. Idempotente (nessuna riga = messaggio "nessun 2FA configurato").
- **`.env`**: `ADMIN_2FA_RESET=true` → nel `lifespan` di `main.py`, all'avvio, `reset_totp` +
  log `WARNING` ("ADMIN_2FA_RESET attivo: 2FA admin azzerato. Rimuovere la variabile."). Ad
  ogni avvio con la variabile attiva il reset si ripete; un banner rosso su tutte le pagine
  admin ricorda di rimuoverla.

In entrambi i casi il login successivo passa dall'enrollment forzato.

## Disattivazione

`ADMIN_2FA_ENABLED=false`:
- login solo password (comportamento attuale);
- `/admin/login/2fa` e `/admin/login/setup` → redirect `/admin/login`;
- riga `admin_totp` **non** toccata: riattivando, il TOTP già configurato funziona;
- log `WARNING` all'avvio;
- banner rosso persistente su tutte le pagine admin: "2FA disattivato (ADMIN_2FA_ENABLED=false)
  — usare solo in sviluppo locale".

Banner (disattivazione e reset) iniettati in `base.html.j2` tramite variabili globali Jinja
calcolate a runtime (`app/jinja_templates.py`).

## Backup / disaster recovery

`admin_totp` **escluso** dal bundle JSON di `routes/backup.py` (export e import — il modello non
viene aggiunto alla lista esportata). Dopo un restore su DB nuovo l'admin passa dall'enrollment
forzato; nessun accesso console necessario, coerente con la procedura DR documentata.

## Documentazione

- `.env.example`: le due variabili con commenti.
- `docs/deployment.md`: sezione "2FA admin" — primo accesso/enrollment, reset da console, reset
  da `.env`, disattivazione per sviluppo locale, effetto del cambio di `SESSION_SECRET`.
- `CLAUDE.md`: variabili nella tabella env; nota che i test via curl dei form admin richiedono
  il TOTP (o `ADMIN_2FA_ENABLED=false` in locale).
- `README.md`: le due variabili nella tabella env (accanto a `ADMIN_PASSWORD`).

## Test

Fixture autouse in `tests/conftest.py` che imposta `ADMIN_2FA_ENABLED=false`: i test esistenti
che fanno `POST /admin/login` con sola password restano invariati. I test 2FA
(`tests/test_admin_2fa.py`) lo sovrascrivono a `true`.

Casi:
- password corretta con 2FA attivo → nessun accesso a `/admin/` (redirect login), redirect a
  setup se non configurato / a 2fa se configurato
- setup: codice errato rifiutato; codice corretto → `confirmed_at` valorizzato, accesso ok
- reload setup riusa lo stesso secret
- setup con riga già confermata → redirect a 2fa
- login 2fa con codice corretto → accesso; stesso codice riusato → rifiutato (replay)
- `pending_2fa` scaduto → redirect login
- codici errati ripetuti → ban IP (429)
- accesso diretto a `/admin/login/2fa` senza `pending_2fa` → redirect login
- secret non decifrabile (SESSION_SECRET diverso) → login bloccato, nessun accesso
- `ADMIN_2FA_ENABLED=false` → login solo password, route 2fa/setup redirect
- `reset_totp` via CLI e via `ADMIN_2FA_RESET` all'avvio → riga cancellata
- export backup non contiene dati TOTP
- unit test su `encrypt/decrypt`, `verify_code` (window, replay)

## Rischi e note

- Cambio di `SESSION_SECRET` = TOTP inutilizzabile → reset da console obbligatorio. Documentato.
- Cookie di sessione firmato ma non cifrato: `pending_2fa` contiene solo username e timestamp,
  mai il secret (che sta solo nel DB, cifrato).
- `ADMIN_2FA_ENABLED=false` in produzione è un rischio accettato dall'operatore: mitigato solo
  da log e banner, nessun blocco basato su hostname (romperebbe staging).
- Sessioni già aperte al deploy restano valide fino a scadenza (`SESSION_MAX_AGE`, 30 min):
  accettabile.
