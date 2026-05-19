# pa-sso-proxy

SPID/CIE SSO proxy per Pubblica Amministrazione italiana.

Permette a qualsiasi applicativo dell'ente di autenticare i cittadini tramite SPID e CIE, esponendo una singola interfaccia OIDC standard. L'ente configura il proxy una volta sola; ogni app si collega come client OIDC con PKCE.

## Funzionalità

- **SPID SAML** — tutti gli IdP ufficiali AgID
- **CIE SAML** — Ministero dell'Interno
- **CIE OIDC Federation 1.0** — accreditamento portale AgID
- **Multi-client OIDC** — N applicativi per ente, configurabili via WebUI
- **WebUI di configurazione** — gestione clienti, certificati, chiavi JWK, metadata IdP
- **Rinnovo automatico certificato SPID** — cron mensile, notifica cambio metadata
- **Aggiornamento automatico metadata IdP** — cron notturno, reload graceful

## Stack

```
nginx → satosa        (SATOSA IAM proxy — SPID/CIE upstream, OIDC downstream)
      → config-api    (FastAPI + Jinja2 — WebUI + REST API + config generator)
postgres              (client registrations, config, chiavi JWK)
```

## Prerequisiti

- Docker + Docker Compose v2
- Reverse proxy esterno che passi `X-Forwarded-Proto` e `X-Forwarded-Host`
- Dominio pubblico con HTTPS (richiesto da SPID/CIE)
- Accreditamento AgID SPID e/o registrazione portale CIE OIDC

## Avvio rapido

```bash
cp .env.example .env
# Modifica .env con i dati dell'ente
docker compose up -d
```

WebUI disponibile su `http://localhost:8080/admin` (o tramite reverse proxy).

Primo avvio: ~2 minuti per download dipendenze SATOSA. Poi:
1. Accedi alla WebUI
2. Configura i dati dell'ente (Impostazioni)
3. Aggiungi i client OIDC delle tue app
4. Scarica il metadata SPID e invialo ad AgID
5. Scarica il JWKS pubblico per registrazione CIE OIDC

## Struttura repository

```
docker-compose.yaml       Stack principale
.env.example              Variabili d'ambiente
satosa/                   Configurazione SATOSA (template YAML)
config-api/               FastAPI app — WebUI + config generator
  app/
    main.py
    routes/
    templates/
    models/
    satosa_generator.py   Genera config SATOSA da DB
nginx/                    Reverse proxy interno
docs/                     Documentazione architetturale
```

## Deployment su Portainer

1. Copia `.env.example` in `.env` e compila
2. In Portainer: Stacks → Add stack → Upload → seleziona `docker-compose.yaml`
3. Incolla le variabili nella sezione "Environment variables"
4. Deploy

## Variabili d'ambiente

| Variabile | Descrizione |
|---|---|
| `PROXY_HOSTNAME` | Dominio pubblico (es. `sso.ente.it`) |
| `ADMIN_USER` | Username WebUI admin |
| `ADMIN_PASSWORD` | Password WebUI admin |
| `POSTGRES_PASSWORD` | Password database |
| `PROXY_HOST_PORT` | Porta host per nginx (es. `127.0.0.1:18080`) |
| `ORG_DISPLAY_NAME` | Nome ente visualizzato |
| `ORG_NAME` | Nome ente slug (da IndicePA) |
| `ORG_URL` | URL pubblico ente |
| `IPA_CODE` | Codice IPA ente |
| `CONTACT_EMAIL` | Email contatto tecnico |
| `CONTACT_PHONE` | Telefono contatto tecnico |
| `ORG_CITY` | Città sede ente (per SubjectDN cert SPID) |

## Integrazione app

Ogni app si registra come client OIDC dalla WebUI e riceve:

```
Authorization endpoint: https://<PROXY_HOSTNAME>/authorize
Token endpoint:         https://<PROXY_HOSTNAME>/token
JWKS endpoint:          https://<PROXY_HOSTNAME>/jwks
Issuer:                 https://<PROXY_HOSTNAME>
```

Flow: Authorization Code + PKCE (`code_challenge_method=S256`).

## Relazione con altri progetti

- **keycloak-login-proxy** — progetto precedente per Provincia di Pescara; questo repo lo sostituisce per il use case SSO cittadini
- **GovPay-Interaction-Layer** (Comune di Montesilvano) — da cui è estratto il backend CIE OIDC

## Licenza

Apache 2.0
