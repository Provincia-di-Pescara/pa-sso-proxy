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

Login con `ADMIN_USER` / `ADMIN_PASSWORD`.

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

**CIE OIDC entity configuration non firmata**: verificare che le chiavi JWK siano generate (WebUI → CIE OIDC) e che SATOSA sia stato riavviato.

**redirect_uri mismatch**: la URI deve corrispondere esattamente (incluso trailing slash) a quella in WebUI.
