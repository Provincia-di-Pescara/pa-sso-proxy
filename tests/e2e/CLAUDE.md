# Test e2e SPID (F8)

`SMOKE_E2E_SPID=true scripts/smoke-stack.sh` (workflow `spid-e2e.yml`: PR/coda solo se cambia codice SPID/OIDC, settimanale su `:latest`): override `tests/e2e/docker-compose.yaml` aggiunge **spid-saml-check** come IdP demo nella rete interna, poi `tests/e2e/spid_login.py` (solo stdlib, container sulla rete dello stack) fa `/verifica/start` → discovery → AuthnRequest → login → ACS → callback due volte: persona fisica (`ada`, verifica il CF) e, dopo `POST /admin/legal-entity/toggle` (ACS index 4 nel metadata SP, metadata ri-registrato sull'IdP demo), persona giuridica (`subject=pg`, scope `legal_entity`, `spid:Purpose=PG`, utente `leonardo`, verifica la ragione sociale "Bottega Verrocchio"). Nessuna rete esterna: il client rifiuta host fuori da `E2E_ALLOWED_HOSTS`.

Gotcha emersi (tutti già gestiti nello script):
- spid-saml-check serve **HTTP** su 8443 (`useHttps: false`), non https.
- L'IdP demo valida ogni AuthnRequest con **spid-sp-test strict**: `Destination` ammessa solo `<entityID>/samlsso` o l'entityID (`IDP_ENTITYID` = entityID del demo, imposto da spid-saml-check) → entityID del demo = `http://spid-saml-check:8443/demo`; `OrganizationDisplayName`/`OrganizationURL` vuoti = request rifiutata.
- `/api/metadata-sp/download` accetta solo URL **https** (`https.get`): il metadata SP va scritto nello store via `database.setMetadata` (node nel container), utente `validator`, store `main`.
- SATOSA legge il metadata degli IdP di test/eIDAS da `/satosa-conf/remote-metadata/<alias>.xml`. `_ensure_remote_metadata` lo riscrive da `metadata_cache` (refresh/cron) o lo riscarica se l'URL cambia (`<alias>.xml.url`); fino a #90 era scritto solo se mancante (refresh e cambio URL mai arrivati a SATOSA). Lo script e2e cancella comunque il file prima del toggle.
- Con un solo backend (CIE spento) l'authorization endpoint è `/<backend>/OIDC/authorization`: `/verifica` lo legge dalla discovery di SATOSA (fix trovato dall'e2e).
- Utenti demo in `src/config/spid_users.json` dell'immagine (password `password123`); `ada` = livello 2; con azienda: `leonardo` (livello 2), `montessori` (livello 3).
- Metadata SP cambiato (es. persona giuridica on) = va ri-registrato nello store dell'IdP demo, altrimenti la request con ACS 4 non supera i controlli.
- Smoke in locale con immagini `:latest`: fare prima `docker pull` — lo script non ripesca le immagini applicative e una `:latest` vecchia in cache sembra una regressione.
