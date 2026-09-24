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
| `proxy_db_data` | PostgreSQL | **Sì** — contiene config e client |
| `proxy_satosa_conf` | Config SATOSA | Ricostruibile |

## Troubleshooting

**SATOSA non parte**: `docker compose logs satosa` — spesso errore YAML config generato.

**Metadata SP non generato**: almeno un IdP SPID deve essere abilitato.

**CIE OIDC entity configuration non firmata**: verificare che le chiavi JWK siano generate (WebUI → CIE OIDC) e che sia avvenuto il reload di SATOSA.

**redirect_uri mismatch**: la URI deve corrispondere esattamente (incluso trailing slash) a quella in WebUI.
