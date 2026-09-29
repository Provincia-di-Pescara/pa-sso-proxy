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
| `proxy_db_data` | PostgreSQL 16 (fino alla v0.9.x) | Solo come rollback dopo l'upgrade a PG18, poi eliminabile |

## Upgrade PostgreSQL 16 → 18

Dalla versione che usa `postgres:18` il database sta in un volume nuovo (`proxy_db_data_pg18`,
montato su `/var/lib/postgresql`): i dati di una major precedente non sono leggibili dalla 18 e
l'immagine 18 si rifiuta di partire sul vecchio mount `/var/lib/postgresql/data`. Il volume
PG16 (`proxy_db_data`) non viene toccato e resta come rollback.

Il login resta fermo per qualche minuto. Comandi dalla directory dello stack, **prima** di
aggiornare `docker-compose.yaml` (o l'immagine in Portainer):

```bash
# 1. Ferma le app (niente scritture durante il dump) e fai il dump dal PostgreSQL 16
docker compose stop nginx satosa config-api
docker compose exec -T postgres pg_dump -U proxy -d proxy -Fc > proxy-pg16.dump
docker compose exec -T postgres pg_restore -l < proxy-pg16.dump | grep -c "TABLE DATA"   # deve essere > 0

# 2. Aggiorna docker-compose.yaml alla nuova versione, poi avvia SOLO postgres 18
#    (config-api non deve partire prima del restore: creerebbe schema e dati iniziali)
docker compose up -d --no-deps postgres
docker compose exec -T postgres pg_isready -U proxy -d proxy

# 3. Ripristina il dump nel database vuoto
docker compose exec -T postgres pg_restore -U proxy -d proxy --no-owner --exit-on-error < proxy-pg16.dump

# 4. Avvia tutto e verifica
docker compose up -d
docker compose exec -T postgres psql -U proxy -d proxy -c "select count(*) from oidc_clients"
```

Verifica: login WebUI, dashboard con lo storico accessi, `/.well-known/openid-configuration` e
`/spidSaml2/metadata` rispondono 200, un login di prova completo.

**Rollback** (se qualcosa non va): `docker compose down`, ripristina il `docker-compose.yaml`
precedente (`postgres:16`, `proxy_db_data:/var/lib/postgresql/data`), `docker compose up -d`: si
riparte dal volume PG16 intatto. Le scritture fatte su PG18 nel frattempo (log accessi) si perdono.

Quando la 18 è stabile, il vecchio volume si elimina con `docker volume rm <progetto>_proxy_db_data`
(nome esatto con `docker volume ls`). Conservare `proxy-pg16.dump` finché non si è sicuri.

## Troubleshooting

**SATOSA non parte**: `docker compose logs satosa` — spesso errore YAML config generato.

**Metadata SP non generato**: almeno un IdP SPID deve essere abilitato.

**CIE OIDC entity configuration non firmata**: verificare che le chiavi JWK siano generate (WebUI → CIE OIDC) e che sia avvenuto il reload di SATOSA.

**redirect_uri mismatch**: la URI deve corrispondere esattamente (incluso trailing slash) a quella in WebUI.
