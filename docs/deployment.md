# Deployment

## Portainer (raccomandato)

### Primo deploy

1. In Portainer: **Stacks → Add stack**
2. Name: `pa-sso-proxy`
3. Upload `docker-compose.yaml`
4. Nella sezione **Environment variables** aggiungere tutte le variabili da `.env.example`
5. **Deploy the stack**

Primo avvio: attendi 2-3 minuti per inizializzazione DB e dipendenze SATOSA.

### Accesso WebUI

- Direct: `http://<HOST>:<PROXY_HOST_PORT>/admin`
- Via reverse proxy: `https://<PROXY_HOSTNAME>/admin`

Login con `ADMIN_USER` / `ADMIN_PASSWORD`, poi codice TOTP (vedi sotto).

### 2FA admin (TOTP)

Il secondo fattore è obbligatorio. Al primo login (o dopo un reset) viene mostrato un QR code:
scansionalo con un'app di autenticazione (FreeOTP, Aegis, Google Authenticator…) e inserisci il
codice a 6 cifre per completare l'attivazione. Dai login successivi viene chiesto solo il codice.

**Telefono perso — reset da console** (nessun restart):

```bash
docker compose exec config-api python -m app.cli reset-2fa
```

**Reset da `.env`** (se non hai accesso alla console del container): imposta
`ADMIN_2FA_RESET=true`, riavvia config-api, poi **rimuovi la variabile** — finché resta a `true`
il 2FA viene azzerato a ogni avvio (un banner rosso nella WebUI lo ricorda).

In entrambi i casi al login successivo viene richiesta una nuova attivazione.

**Sviluppo locale:** `ADMIN_2FA_ENABLED=false` disattiva il 2FA (login con sola password, banner
rosso su tutte le pagine). Mai in produzione.

**Attenzione a `SESSION_SECRET`:** il secret TOTP è cifrato con una chiave derivata da
`SESSION_SECRET`. Se lo cambi, il login si blocca con "Secret 2FA non decifrabile": esegui il reset
da console e riattiva il 2FA.

Il TOTP **non** è incluso nel backup JSON: dopo un ripristino su DB nuovo il 2FA va riattivato
al primo login.

## Docker Compose (manuale)

```bash
cp .env.example .env
# Modifica .env
docker compose up -d
docker compose logs -f
```

## Reverse proxy nginx (esempio)

```nginx
server {
    listen 443 ssl;
    server_name sso.ente.it;

    location / {
        proxy_pass http://127.0.0.1:18080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }
}
```

`X-Forwarded-Proto` e `X-Forwarded-Host` sono obbligatori — SATOSA li usa per generare redirect URI.

## Integrazione app (client OIDC)

### Setup client

1. WebUI → **Clienti → Aggiungi client**
2. Compila: nome, redirect URI, scopes
3. Copia `client_id` e `client_secret` (mostrato una sola volta)

### Endpoint OIDC

```
Authorization: https://<PROXY_HOSTNAME>/authorize
Token:         https://<PROXY_HOSTNAME>/token
JWKS:          https://<PROXY_HOSTNAME>/jwks
Issuer:        https://<PROXY_HOSTNAME>
```

Flow: Authorization Code + PKCE (`code_challenge_method=S256`).

## Claim ricevuti

| Claim | SPID | CIE |
|---|---|---|
| `fiscalNumber` | ✓ | ✓ |
| `familyName` | ✓ | ✓ |
| `name` | ✓ | ✓ |
| `dateOfBirth` | ✓ | ✓ |
| `email` | opzionale | opzionale |

## Volumi Docker

| Volume | Contenuto | Persistere? |
|---|---|---|
| `proxy_db_data_pg18` | PostgreSQL 18 | **Sì** — contiene config, client e log accessi |
| `proxy_satosa_conf` | Config SATOSA | Ricostruibile |
| `proxy_db_data` | PostgreSQL 16 (fino alla v0.9.9) | Sorgente della migrazione automatica, poi solo rollback |
| `proxy_db_upgrade` | Dump + marker della migrazione 16 → 18 | Eliminabile a migrazione verificata |

## Upgrade PostgreSQL 16 → 18

Dalla v0.9.10 lo stack usa `postgres:18` con un volume nuovo (`proxy_db_data_pg18`, montato su
`/var/lib/postgresql`). I dati di una major precedente non sono leggibili dalla 18, e l'immagine
18 si rifiuta di partire sul vecchio mount `/var/lib/postgresql/data`.

**La migrazione è automatica: basta aggiornare lo stack** (in Portainer: aggiorna il compose →
"Update the stack" con "Re-pull image"). Nessun accesso shell richiesto. Al deploy:

1. `db-upgrade-dump` (`postgres:16`) trova i dati PG16 nel volume `proxy_db_data` e ne fa il
   dump nel volume `proxy_db_upgrade`. Se il vecchio PostgreSQL è ancora in esecuzione legge da
   lì, altrimenti avvia temporaneamente PG16 sul volume.
2. `postgres` (18) parte solo dopo che il dump è riuscito, su un volume vuoto.
3. `db-upgrade-restore` (`postgres:18`) carica il dump in una singola transazione e scrive il
   marker `restored`.
4. `config-api` parte solo dopo il restore: Alembic non trova migrazioni pendenti e i dati sono
   quelli di prima (client, IdP, certificati, log accessi).

Il login resta fermo per il tempo del deploy (circa un minuto con pochi MB di dati). Nei deploy
successivi, e sulle installazioni nuove, i due servizi escono subito con "niente da fare": in
Portainer compaiono come container **Exited (0)**, è normale.

Sicurezze:
- se il dump fallisce PostgreSQL 18 non parte e lo stack resta fermo senza toccare nulla: il
  volume PG16 è intatto, basta rimettere la versione precedente;
- se il restore fallisce config-api non parte e il database 18 resta vuoto (transazione
  annullata): al deploy successivo il restore viene ritentato;
- se il database 18 contiene già tabelle (migrazione fatta a mano) il restore viene saltato con un
  avviso nei log di `db-upgrade-restore`, senza sovrascrivere nulla.

Log della migrazione: container `db-upgrade-dump` e `db-upgrade-restore` (righe `[db-upgrade-…]`).

**Rollback**: rimetti il compose della versione precedente (`postgres:16`,
`proxy_db_data:/var/lib/postgresql/data`) e aggiorna lo stack: si riparte dal volume PG16 intatto.
Le scritture fatte su PG18 nel frattempo (log accessi, modifiche da WebUI) si perdono.

Quando la 18 è stabile i volumi `proxy_db_data` e `proxy_db_upgrade` si possono eliminare (in
Portainer: Volumes). I servizi `db-upgrade-*` verranno rimossi in una versione futura.

### Migrazione manuale (fallback, richiede shell)

Solo se quella automatica non è utilizzabile. Dalla directory dello stack, prima di aggiornare il
compose:

```bash
docker compose stop nginx satosa config-api
docker compose exec -T postgres pg_dump -U proxy -d proxy -Fc > proxy-pg16.dump
# aggiorna docker-compose.yaml, poi avvia SOLO postgres 18 (config-api deve restare fermo)
docker compose up -d --no-deps postgres
docker compose exec -T postgres pg_restore -U proxy -d proxy --no-owner --exit-on-error < proxy-pg16.dump
docker compose up -d
```

## Troubleshooting

**SATOSA non parte**: `docker compose logs satosa` — spesso errore YAML config generato.

**Metadata SP non generato**: almeno un IdP SPID deve essere abilitato.

**CIE OIDC entity configuration non firmata**: verificare che le chiavi JWK siano generate (WebUI → CIE OIDC) e che sia avvenuto il reload di SATOSA.

**redirect_uri mismatch**: la URI deve corrispondere esattamente (incluso trailing slash) a quella in WebUI.
