# IT-Wallet — laboratorio locale (Windows)

Prova end-to-end senza accreditamento: si usa il lab di upstream
iam-proxy-italia v3.9.0 (issuer OpenID4VCI, wallet demo, trust anchor di test)
e il nostro stack come verifier. Solo ambiente `personalizzato`, quindi client
di test (`/verifica` o client con `allow_test_idps`).

## 1. Lab upstream

```powershell
git -c core.longpaths=true -c core.autocrlf=false clone --branch v3.9.0 https://github.com/italia/iam-proxy-italia.git
```

Non usare `run-docker-compose.sh` (richiede sudo e `/etc/hosts`): inizializzare
a mano i file di configurazione come fa lo script, poi avviare:

```powershell
$env:COMPOSE_PROFILES = "oidc"
docker compose -p iamlab up -d
```

Il lab upstream usa MongoDB (pyeudiw upstream); il nostro stack usa Redis.

## 2. Hosts (PowerShell come amministratore)

```powershell
[System.IO.File]::AppendAllText("$env:SystemRoot\System32\drivers\etc\hosts", "`r`n127.0.0.1 iam-proxy-italia.example.org demo-wi.example.org trust-anchor.example.org cie-provider.example.org sso-lab.example.org # iamlab`r`n")
```

Rimozione a fine prova:

```powershell
$h="$env:SystemRoot\System32\drivers\etc\hosts"; (Get-Content $h) | Where-Object { $_ -notmatch '# iamlab' } | Set-Content $h -Encoding ascii; ipconfig /flushdns
```

## 3. Utente demo dell'issuer

Col solo profilo `oidc` l'utente non viene seminato (500 "User ... not found"
su `/OpenID4VCI/credential`):

```powershell
$env:MSYS_NO_PATHCONV = 1
docker exec iam-proxy-italia python /satosa_proxy/conf/frontends/openid4vci/seed_users.py
```

## 4. Il nostro stack nel lab

- `.env` locale: `PROXY_HOSTNAME=sso-lab.example.org`, `ADMIN_2FA_ENABLED=false`,
  `VERIFY_IMAGES=false` (salvare prima una copia del `.env`; immagini `:local`).
- Collegare i nostri container alla rete `iam-proxy-italia`, così wallet e
  trust anchor raggiungono il verifier.
- TLS: aggiungere a `satosa-nginx` di upstream un server block extra per
  `sso-lab.example.org` che fa proxy verso il nostro nginx (porta 8080).
  Certificato autofirmato: nel browser (o Playwright) ignorare gli errori HTTPS.

## 5. Configurazione e registrazione

1. `/admin/itwallet`, in quest'ordine: **generare le chiavi** → **configurare**
   (ambiente `personalizzato`, Trust Anchor
   `http://trust-anchor.example.org:5002`) → **attivare** (l'attivazione è
   rifiutata finché mancano le chiavi).
2. Admin del trust anchor (spid-cie-oidc-django): creare un
   `FederationDescendant` con l'Entity ID dalla scheda Onboarding
   (`https://sso-lab.example.org/OpenID4VP`), JWKS di federazione e profilo
   `credential-verifier`.
3. Verificare che `/OpenID4VP/.well-known/openid-federation` risponda 200.

## 6. Giro con il wallet demo

1. Wallet demo (`demo-wi.example.org`): ottiene l'IT-Wallet ID dall'issuer
   (login CIE finto `user`/`oidcuser`). Password del wallet demo: `wallet`.
2. Da `/verifica` (o dal test client admin a livello backend) scegliere la
   tab IT-Wallet: compare il QR. `/verifica` è sempre raggiungibile, anche
   senza IdP SPID Demo/Validator abilitati: con il wallet in
   `collaudo`/`personalizzato` è il percorso di test pronto all'uso.
3. Caricare il QR nel wallet demo (screenshot dell'SVG con margine, nel
   campo file) e presentare la credenziale.
4. Atteso: `given_name`, `family_name`, `birthdate`, `fiscal_number`
   `["TINIT-<CF>"]`. `place_of_birth` arriva come lista `["<località>"]` e
   solo se il client chiede quel claim (scope/`claims`): nel giro e2e da
   `/verifica` non compariva nello userinfo perché `/verifica` non lo chiede.

La credenziale dura circa 6 minuti: se scade, riavviare
`wallet-instance-demo` per riemetterla.

Controlli utili: client senza `allow_test_idps` -> pagina
`error.itwallet_test_only`; scope `legal_entity` ->
`error.legal_entity_spid_only`; IT-Wallet spento ->
`/OpenID4VP/.well-known/openid-federation` 404 e tab assente;
`docker compose stop redis` -> il wallet dà pagina d'errore, SPID continua.

## 7. Pulizia

Rimuovere la riga hosts (comando sopra), `docker compose -p iamlab down -v`,
ripristinare il `.env` dalla copia.
