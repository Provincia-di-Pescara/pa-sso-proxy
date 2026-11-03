# F6 — Hardening runtime

Spec: §4 F6.

## Scelte

- **Non-root vero, non "drop dei privilegi" nell'entrypoint**: satosa e config-api `USER 10001`
  nell'immagine, nginx → `nginxinc/nginx-unprivileged` (uid 101, porta 8080). Nessuna
  capability ai servizi applicativi.
- **`init-perms`** one-shot (immagine config-api, root, solo `CHOWN/DAC_OVERRIDE/FOWNER`, senza
  rete): `chown -R 10001:10001 /satosa-conf` a ogni avvio. Copre l'upgrade dei volumi di
  produzione con file scritti come root (chiave SPID `600` compresa) senza intervento manuale.
- **postgres/redis**: immagini ufficiali (entrypoint root → utente dedicato), solo le 5
  capability dell'entrypoint; redis senza persistenza (`/data` tmpfs, come prima: nessun volume).
- **`read_only: true` ovunque**, tmpfs con `mode=1777` (senza, tmpfs root 755 non scrivibile
  dagli utenti non-root).
- **Segreti `:?`**: niente più default `changeme-…`.
- **`verify-images`** con `VERIFY_IMAGES` (variabile, default `false`); `release.yml` lo attiva
  nello smoke dello stack, quindi ogni release prova anche la verifica delle firme.

## Verifica locale (fatta)

- `scripts/smoke-stack.sh` con le immagini F6: tutti gli step verdi (prima installazione,
  satosa healthy, discovery OIDC, metadata SPID firmato, nessun traceback).
- Upgrade simulato: volume con file root `600` → `init-perms` → satosa uid 10001 legge la
  chiave e scrive `.reload`.
- Trivy misconfig sui Dockerfile: 0 HIGH/CRITICAL **senza** eccezioni (rimossa `DS-0002`).

## Rischi per la produzione (da fare PRIMA del merge)

1. **Variabili Portainer**: verificare sui 2 ambienti che `POSTGRES_PASSWORD`, `ADMIN_USER`,
   `ADMIN_PASSWORD`, `SESSION_SECRET`, `SATOSA_HASH_SALT`, `SATOSA_STATE_ENCRYPTION_KEY`,
   `PROXY_HOSTNAME` siano impostate. Portainer ridistribuisce da git: una variabile mancante =
   stack fermo. Non cambiare `SATOSA_HASH_SALT` esistente.
2. **Porta nginx**: interna 8080, la porta host (`PROXY_HOST_PORT`) non cambia; nessun impatto
   sul reverse proxy esterno.
3. **Ordine**: la F6 va pubblicata con le immagini nuove (compose nuovo + immagini vecchie =
   nginx in ascolto su 80 ma mappato su 8080). Dopo il merge lanciare subito
   `release.yml -f rebuild_latest=true`; Portainer prende compose e immagini insieme solo se
   il rebuild termina prima del suo polling → in pratica: mergiare, attendere la release,
   poi ridistribuire lo stack.
4. Dopo la prima release firmata: `VERIFY_IMAGES=true` sui 2 ambienti.
