# Registrazione CIE OIDC Federation

## Prerequisiti

Stack deployato e raggiungibile su HTTPS. SATOSA deve esporre:
```
https://<PROXY_HOSTNAME>/.well-known/openid-federation
```

## Procedura

### 1. Generare le chiavi JWK

WebUI → **CIE OIDC → Genera chiavi federation**

Vengono creati 3 keypair RSA 2048:
- `jwk-federation` (firma entity configuration — non esposto)
- `jwk-core-sig` (firma OIDC requests — esposto in JWKS)
- `jwk-core-enc` (cifratura — esposto in JWKS)

### 2. Scaricare il JWKS pubblico

WebUI → **CIE OIDC → Scarica JWKS pubblico**

Formato:
```json
{
    "keys": [
        { "kty": "RSA", "use": "sig", "kid": "...", "e": "AQAB", "n": "..." },
        { "kty": "RSA", "use": "enc", "kid": "...", "e": "AQAB", "n": "..." }
    ]
}
```

### 3. Verificare l'endpoint

```bash
curl https://<PROXY_HOSTNAME>/.well-known/openid-federation
# Deve restituire un JWT firmato con jwk-federation
```

### 4. Registrazione portale AgID/CIE

- **URL (Entity ID)**: `https://<PROXY_HOSTNAME>`
- **JWKS**: incollare il contenuto del file scaricato

Il portale verificherà che `{url}/.well-known/openid-federation` sia raggiungibile e correttamente firmato.

### 5. Post-registrazione

Verificare il flusso completo: WebUI → **Dashboard → Test CIE OIDC**.

## Rinnovo chiavi

1. WebUI → CIE OIDC → Rigenera chiavi
2. Scaricare nuovo JWKS pubblico
3. Aggiornare registrazione portale AgID con il nuovo JWKS
