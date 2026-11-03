# Allineamento CI/CD alla baseline di sicurezza ComunicaPA

Data: 2026-11-03 · Stato: approvata (decisioni in §2), implementazione a fasi

Riferimento: [ComunicaPA — Baseline di sicurezza CI/CD](https://github.com/Comune-di-Montesilvano/ComunicaPA/blob/main/docs/ci-cd-security-baseline.md)
(di seguito "baseline", sezioni citate come §N).

## 1. Obiettivo

1. **Rilascio automatico dei fix di sicurezza**: una vulnerabilità HIGH/CRITICAL con versione
   corretta arriva in una `latest` firmata, scansionata e provata entro ~24 h, senza intervento
   manuale (eccezioni in §2.3).
2. **Best practice di supply chain**: un solo cancello verso `main` e verso la produzione,
   tutto fissato e verificabile, privilegio minimo, fallire chiusi.

**Non obiettivi**: review di una seconda persona (unico maintainer, gap accettato come in
ComunicaPA §10), SLSA L3, secret scanning a pattern generici (licenza), IT-Wallet.

### Vincolo che cambia le priorità

Portainer in produzione **riscarica da solo `:latest`**. Pubblicare `latest` = andare in
produzione. Quindi:
- ogni controllo deve stare **prima** dell'applicazione del tag `latest`;
- un rebuild senza causa reale = riavvio inutile dello stack di produzione;
- serve un rollback per tag immediato (`latest-YYYYMMDD`).

## 2. Decisioni prese

| # | Decisione | Motivo |
|---|---|---|
| 2.1 | **Merge queue + CI gate** come unico required check (trigger `merge_group`); via policy strict e `update-behind.yml` | testa il commit esatto che entra in main, niente serializzazione/polling orario; in coda i filtri path non valgono → controlli pesanti solo lì (baseline principio 8) |
| 2.2 | **Rebuild giornaliero condizionato** (causa a/b/c, baseline §6) al posto del cron settimanale incondizionato | fix in prod entro un giorno; nessun riavvio di prod senza motivo |
| 2.3 | **Codice e librerie SPID SAML/CIE: solo PR, mai auto-merge** — `pysaml2`, `satosa`, `satosa/plugins/spidsaml2.py`, immagine base e `IAM_PROXY_REF` iam-proxy-italia, `cryptojwt`, `cryptography`, `pyeudiw` | in CI non esiste un test end-to-end del login; una regressione blocca il login di tutti i cittadini o indebolisce la verifica di firma senza che un test fallisca |
| 2.4 | **Test e2e SPID** con `italia/spid-saml-check` in container (non `demo.spid.gov.it`), **ultima fase**, dopo l'allineamento del resto | demo pubblico richiede metadata SP raggiungibile da internet (tunnel) ed è una dipendenza esterna non deterministica per un check bloccante |
| 2.5 | Fasi piccole implementate direttamente; fasi complesse precedute da un piano in `docs/superpowers/plans/` | — |

## 3. Stato attuale (gap analysis, 2026-11-03)

✅ allineato · ⚠️ parziale · ❌ assente

**Repository (§1)**
- ✅ `GITHUB_TOKEN` read-only, non approva PR · GitHub App bot con secret Actions + Dependabot
- ❌ Dependabot security updates (alert attivi, PR no) · secret scanning · push protection · private vulnerability reporting
- ❌ `allowed_actions: all`, `sha_pinning_required: false` (tutte le action sono già fissate per SHA, comprese le annidate di `trivy-action`)
- ❌ merge commit e rebase consentiti a livello repo · `delete_branch_on_merge: false`
- ⚠️ CodeQL: workflow avanzato, solo Python, suite `default`, linguaggio `actions` non analizzato
- ⚠️ 2 alert CodeQL high aperti (`py/incomplete-url-substring-sanitization`), entrambi in file di test

**Ruleset (§2)**
- ✅ `main`: deletion, non_fast_forward, nessun bypass, required check `CI gate` (strict)
- ❌ regola `pull_request` · merge queue · regola `code_scanning` · ruleset tag `v*`

**Workflow (§3)**
- ✅ SHA pinning, `timeout-minutes` ovunque, niente `pull_request_target`, input non fidati via `env:`
- ⚠️ scritture dichiarate in testa: `docker.yml` (packages), `codeql.yml` (security-events), `publiccode-validate.yml` (pull-requests), `upstream-check.yml` (issues), `dependabot-automerge.yml` (contents, inutile)
- ❌ `persist-credentials: false` · `harden-runner`
- ⚠️ `concurrency` mancante in `dependabot-automerge.yml`, `upstream-check.yml`
- ⚠️ tool non fissati: `pipx run pip-audit`, `pip install --upgrade pip`; nessun check versione Trivy
- ⚠️ run duplicati (PR + push main) di CI e build Docker
- ❌ gate differenziali: Trivy assoluto → satosa abbassato a solo CRITICAL

**Dipendenze (§5)**
- ✅ Dependabot su tutti gli ecosistemi con cooldown 7/14; esclusioni SPID/CIE e cambio Python da auto-merge
- ❌ lock con hash (solo dirette `==`, niente transitive)
- ⚠️ digest solo su satosa; `python:3.14-slim`, `nginx:alpine`, `postgres:18`, `redis:8-alpine` senza digest
- ⚠️ Dependabot settimanale; major postgres solo commentate, non `ignore`
- ❌ dependency-review · Trivy fs (segreti/misconfig) · pip-audit su `satosa/requirements-runtime.txt`
- ❌ correzione autonoma

**Release (§6)**
- ✅ build in CI, Trivy + smoke per immagine prima del push, tag `sha-<commit>`
- ⚠️ push per tag, non per digest
- ❌ rebuild condizionato (oggi settimanale incondizionato) · cosign · provenance · SBOM · smoke stack completo · pulizia ghcr

**Deploy e runtime (§7, §8)**
- ✅ solo nginx pubblica una porta, su `127.0.0.1`
- ❌ verifica firme prima dell'avvio
- ❌ config-api gira come root (nessun `USER`); satosa: `USER root` e uWSGI senza `--uid` → root
- ❌ `cap_drop`, `no-new-privileges`, `read_only`
- ❌ **segreti con default insicuri nel compose**: `SESSION_SECRET`, `SATOSA_HASH_SALT`,
  `SATOSA_STATE_ENCRYPTION_KEY` hanno default `changeme-…` invece di `:?`

**Governance (§9)**
- ⚠️ `SECURITY.md` presente, solo email
- ❌ `CODEOWNERS`, template PR, `CONTRIBUTING.md`, Scorecard, controllo periodico alert aperti

## 4. Fasi

Legenda complessità: **S** = piccola, implementazione diretta · **C** = complessa, prima piano.

```
F0 ─┐
F1 ─┴─► F2 ─┐
     F3 ─► F4 ─┴─► F5 ─► F6, F7 ─► F8
```

---

### F0 — Impostazioni repository e ruleset · S · nessuna PR

Via `gh api` su `repos/Provincia-di-Pescara/pa-sso-proxy`.

| Azione | Valore |
|---|---|
| Dependabot security updates | on (`PUT automated-security-fixes`) |
| Secret scanning + push protection | on |
| Private vulnerability reporting | on |
| Repo | `allow_merge_commit: false`, `allow_rebase_merge: false`, `delete_branch_on_merge: true` |
| Ruleset `Main Branch` | + `pull_request` (0 approvazioni, `required_review_thread_resolution: true`, `allowed_merge_methods: [squash]`); + `code_scanning` (CodeQL, `alerts: errors`, `security_alerts: high_or_higher`); strict resta fino a F2 |
| Ruleset nuovo `release-tags` | target tag `refs/tags/v*`: creation, update, deletion, non_fast_forward; bypass ruolo admin |
| Action consentite | `allowed_actions: selected`, `github_owned_allowed: true`, `verified_allowed: false`, elenco: `aquasecurity/trivy-action@*`, `aquasecurity/setup-trivy@*`, `dependabot/fetch-metadata@*`, `docker/*@*` (le 4 usate, elencate una per una), `italia/publiccode-parser-action@*`; `sha_pinning_required: true` |
| Alert CodeQL nei test | lettura del codice; se falsi positivi → dismiss `used in tests` con motivazione |
| `SECURITY.md` | link a "Report a vulnerability" (PVR) come canale primario (piccola PR) |

Rischio: la regola `code_scanning` richiede che CodeQL giri su ogni PR (oggi sì, `codeql.yml`
su `pull_request` a main). Le action future (`harden-runner`, cosign…) vanno aggiunte
all'elenco **nella stessa PR** che le introduce.

**Fatto quando**: i comandi di verifica della baseline §1 e §2 restituiscono i valori attesi.

---

### F1 — Igiene dei workflow · S · 1 PR

- `permissions: contents: read` in testa a ogni workflow; scritture solo nel job che le usa.
  `dependabot-automerge.yml`: niente `contents: write` (il merge lo fa l'App), solo
  `pull-requests: write` per label/commento.
- `persist-credentials: false` su ogni `actions/checkout` (eccezione motivata se un job fa push
  con il token del checkout — oggi nessuno).
- `step-security/harden-runner` primo step di ogni job, `egress-policy: audit`. Aggiunto
  all'elenco action consentite. L'elenco host per il futuro `block` (F4) si ricava dai log.
- `concurrency` in `dependabot-automerge.yml` (`cancel-in-progress: false`) e
  `upstream-check.yml`.
- Tool fissati: `pip-audit==<versione>` (non `pipx run` flottante), niente
  `pip install --upgrade pip` (o pip a versione fissa); Trivy `v0.76.1`.
- Nuovo `tool-version-check.yml` (settimanale, lunedì): apre una issue quando escono nuove
  versioni di Trivy / pip-audit fissati (stesso schema di `upstream-check.yml`).
- CodeQL → **default setup**, suite `extended`, linguaggi `python` + `actions`; rimuovere
  `codeql.yml`. La regola `code_scanning` di F0 continua a funzionare (stesso tool CodeQL).
- Rimuovere il commento obsoleto in `docker.yml` ("i merge dell'auto-merge non fanno partire il
  push").

**Fatto quando**: tutti i workflow verdi su una PR di prova, nessuna scrittura in testa
(`grep -L` sul blocco `permissions`), `harden-runner` presente in ogni job.

---

### F2 — Merge queue · C · piano + 1 PR + ruleset

Contenuto da dettagliare nel piano:
- `ci-gate.yml`: trigger `merge_group`; SHA da `github.event.merge_group.head_sha` (in PR
  resta `pull_request.head.sha`); `concurrency` per gruppo.
- Tutti i workflow attesi dal gate ricevono `on: merge_group`. In coda nessun filtro path →
  girano tutti; in PR restano filtrati.
- **Spostamento dei controlli pesanti in coda**: build immagini + smoke + Trivy image e
  `smoke-config-api-postgres` girano solo su `merge_group` (e su main/schedule); in PR restano
  test, pip-audit, CodeQL, publiccode. Nelle matrici il salto si fa per step, non per job
  (baseline §2: un job matrice saltato non crea i check).
- Ruleset `main`: `merge_queue` (squash, `ALLGREEN`, build/merge fino a 5, timeout 60 min),
  `strict_required_status_checks_policy: false`.
- Rimuovere `update-behind.yml`.
- `dependabot-automerge.yml` invariato (`gh pr merge --auto` con coda attiva = accoda).
- CLAUDE.md: aggiornare la sezione CI/CD (required check, coda).

**Fatto quando**: una PR Dependabot patch passa dalla coda e viene mergiata senza intervento;
una PR che rompe un test in coda viene espulsa.

---

### F3 — Dipendenze · C · piano + 1-2 PR

Contenuto da dettagliare nel piano:
- **Lock con hash**:
  - `config-api/requirements.in` (dirette) → `requirements.txt` (`pip-compile --generate-hashes`,
    versione pip-tools fissata); `requirements-dev.in` → `requirements-dev.txt` (vincolato al
    lock runtime con `-c`).
  - `satosa/requirements-runtime.in` → lock con hash. Vincolo: si installa **dentro il venv
    upstream** già popolato → il lock deve essere compatibile con i pacchetti del venv; da
    verificare se `--require-hashes` è applicabile o serve `--no-deps` + lock delle sole
    aggiunte.
  - `satosa/tests/requirements-test.txt`: lock solo se pratico (gira in CI, non in prod).
  - Dockerfile: `pip install --require-hashes --no-deps -r requirements.txt`.
  - Dependabot pip: verificare che aggiorni coppia `.in`/`.txt` con hash (supportato per
    pip-compile).
- **Digest**: `python:3.14-slim@sha256:…`, `nginx:alpine@sha256:…` (valutare tag con versione
  esplicita, es. `nginx:1.x-alpine`), `postgres:18@sha256:…`, `redis:8-alpine@sha256:…`
  (compose + service container in `ci.yml`).
- **Dependabot**: giornaliero 01:00 Europe/Rome; `ignore` major `postgres`; mantenere cooldown e
  gruppi; `cryptography` resta esclusa dal gruppo.
- **Nuovi check PR**: `actions/dependency-review-action` (HIGH+, include Actions);
  Trivy fs (`scanners: secret,misconfig` su repo, `vuln` su lockfile); pip-audit anche su
  `satosa/requirements-runtime.txt`.
- **Eccezioni**: migrare `.trivyignore` → `.trivyignore.yaml` (ID + `paths` + `statement`).
  Misconfig attese da gestire esplicitamente: utente root in satosa/config-api (fino a F6).
- Trivy fs misconfig sul compose segnalerà i default `changeme-…` / container root: si
  registrano come eccezioni temporanee con rimando a F6, non si nascondono.

**Fatto quando**: build Docker fallisce con un hash alterato; dependency-review blocca una PR di
prova con una dipendenza vulnerabile; tutte le `FROM`/`image:` hanno digest.

---

### F4 — Release · C · piano + 1 PR (sostituisce `docker.yml`)

`release.yml`, trigger: tag `v*`, schedule giornaliero 04:30 Europe/Rome, dispatch
(`dry_run`, `rebuild_latest`). Push su main/merge queue non pubblicano più (oggi `:main`):
da decidere nel piano se mantenere `:main` (nessun consumatore noto).

Job:
1. **setup / rebuild-check** (solo schedule o `dry_run`): `scripts/rebuild-check.sh` sulle 3
   `latest` (per digest). Cause: **a** commit su main dopo la label
   `org.opencontainers.image.revision`; **b** patch OS disponibili (satosa/nginx alpine →
   `apk list -u`; config-api debian → `apt list --upgradable`); **c** Trivy HIGH/CRITICAL con fix.
   Errore di verifica = causa. Nessuna causa → run verde, nessun digest nuovo. Esito nel summary
   e in label `pa-sso-proxy.rebuild.reason`.
2. **build-push ×3**: build → push **solo per digest** → Trivy (tag `v*`: bloccante HIGH/CRITICAL
   con fix, anche satosa; rebuild: blocca solo regressioni vs `latest` pubblicata) → SBOM
   CycloneDX → `actions/attest-build-provenance` + `actions/attest-sbom` → firma cosign keyless.
   Permessi job: `packages: write`, `id-token: write`, `attestations: write`.
   `harden-runner` in `block` con `allowed-endpoints`.
3. **smoke**: stack compose di produzione con i 3 digest → `scripts/smoke-stack.sh`:
   postgres/redis/satosa/config-api/nginx healthy, Alembic a head, `/health`,
   `/.well-known/openid-configuration`, metadata SPID servito e firmato, entity configuration
   CIE se configurabile senza federazione, nginx verso entrambi gli upstream, login admin
   (2FA off), log senza traceback. Dati di avvio: seed minimo (cert SPID e JWK generati) —
   da definire nel piano (oggi su volumi vuoti satosa non parte senza restore).
4. **publish ×3** (solo smoke verde): tag `vX.Y.Z` + `X.Y` (se tag), `latest`,
   `latest-YYYYMMDD`, `sha-<commit>`.
- Il "rebuild con CVE ancora presenti" pubblica se non peggiora e apre la issue
  "Vulnerabilità non risolvibile con un rebuild (<immagine>)".
- `APP_VERSION`/`app_release.txt` (footer WebUI + release Sentry): mantenere la logica attuale.
- `ghcr-cleanup.yml` (settimanale): rimuove digest orfani e relative firme/attestazioni
  (sostituisce la pulizia manuale).
- `security-alerts.yml` (giornaliero + push main): issue aperta/chiusa sugli alert code scanning
  high/critical aperti su main (Scorecard escluso). Non required.
- Documentazione: `docs/deployment.md` → verifica firma (`cosign verify` /
  `gh attestation verify`) e rollback su `latest-YYYYMMDD`.

**Fatto quando**: un merge su main produce entro la notte una `latest` firmata, con
attestazioni, verificabile con `cosign verify` (identità `release.yml`); un giorno senza cause
non produce digest nuovi; un `dry_run` stampa le cause.

---

### F5 — Correzione autonoma (`security-autofix.yml`) · C · piano + 1 PR

Trigger: giornaliero 02:30 (prima del rebuild delle 04:30), fallimento dei controlli di
sicurezza su main, dispatch (`force`, `dry_run`).

- Input: alert Dependabot aperti + pip-audit + Trivy image sulla `latest`, solo HIGH/CRITICAL con
  versione corretta.
- **pip**: versione più bassa che corregge, pubblicata da ≥ 48 h, con provenienza
  **PEP 740** dallo stesso repository delle versioni precedenti (se il pacchetto non pubblica
  attestazioni: non correggibile in autonomia → issue). Pin nel `.in`, lock ricompilato con hash.
- **Immagini base**: digest più recente dello stesso tag.
- Commit via GraphQL `createCommitOnBranch` con token GitHub App (commit verificati); il job
  fallisce se il working tree tocca file fuori da: `**/requirements*.in`, `**/requirements*.txt`,
  `**/Dockerfile` (solo righe `FROM`), `docker-compose.yaml` (solo `image:`).
- **Merge**:
  - tutto il resto → una PR con auto-merge → merge queue;
  - pacchetti di §2.3 → PR separata **senza auto-merge**, label `revisione-manuale`, corpo con
    advisory e link al changelog;
  - PR fallita → al giro dopo una PR per pacchetto; le correzioni fallite restano escluse.
- Tre issue di stato (in attesa / non correggibili / fallite), chiuse quando vuote.
- Lo script (`scripts/security/pip_fix.py` o simile) ha **test propri su fixture fisse**
  (`scripts/security/test/fixtures/`), eseguiti nella CI.

**Fatto quando**: in `dry_run` su una fixture con CVE nota l'autofix sceglie la versione giusta;
su un caso reale apre la PR che passa dalla coda e il rebuild delle 04:30 pubblica `latest`.

---

### F6 — Hardening runtime · C · piano + 1-2 PR

- **Segreti**: `SESSION_SECRET`, `SATOSA_HASH_SALT`, `SATOSA_STATE_ENCRYPTION_KEY`,
  `POSTGRES_PASSWORD`, `ADMIN_PASSWORD` → `${VAR:?messaggio}`. **Prima** verificare sui 2
  ambienti Portainer che siano tutti impostati (altrimenti lo stack non riparte) —
  attenzione: cambiare `SATOSA_HASH_SALT` cambia gli hash CF e il secret di `__spid_verifica__`.
- **config-api**: utente non-root (uid dedicato), proprietà di `/satosa-conf` gestita.
- **satosa**: uWSGI con `--uid/--gid` non-root dopo le operazioni di setup dell'entrypoint;
  verificare scrittura su `/satosa-conf` (condiviso con config-api → uid comune) e
  `--touch-reload`.
- **Compose**: `no-new-privileges:true` e `cap_drop: [ALL]` ovunque; postgres e redis
  riaggiungono `CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID`; `read_only: true` + tmpfs
  (`/tmp`, eventuali cache) — satosa/uWSGI e nginx (`/var/cache/nginx`, `/var/run`,
  `/etc/nginx/conf.d` generato da envsubst → tmpfs) da provare uno per uno.
- **verify-images**: servizio one-shot cosign nel compose, attivo con `VERIFY_IMAGES=true`
  (variabile, non `profiles`), servizi applicativi `depends_on: service_completed_successfully`.
  Default `false` al primo rilascio, poi `true` sui 2 ambienti dopo prova.
- Test di regressione: procedura disaster recovery di CLAUDE.md (volumi vuoti → import backup),
  reload uWSGI da WebUI, rotazione cert SPID, `pg_dump`/restore.

**Fatto quando**: `docker compose up` su volumi vuoti + restore funziona con tutti i servizi
non-root e read-only; uno stack con firma mancante non avvia i servizi.

---

### F7 — Governance · S · 1 PR

- `.github/CODEOWNERS` (maintainer su tutto; `.github/`, `satosa/plugins/`, Dockerfile in
  evidenza).
- `.github/pull_request_template.md`: checklist test di regressione, sicurezza, metadata SPID
  modificato (→ ri-validazione AgID), CLAUDE.md aggiornato.
- `CONTRIBUTING.md`: policy test (ogni fix ha un test), flusso branch → PR → coda, commit
  squash, niente push su main.
- `scorecard.yml` (push main + settimanale, `permissions: read-all`, risultati pubblici) +
  badge nel README; richiesta badge OpenSSF Best Practices.
- `docs/ci-cd-security.md`: stato corrente della checklist baseline (aggiornato a fine di ogni
  fase) + comandi di verifica.
- CLAUDE.md: sezione CI/CD riscritta sul nuovo flusso.

---

### F8 — Test end-to-end SPID · C · piano + 1 PR (ultima)

- Servizio `italia/spid-saml-check` (modalità demo IdP) nello stack di test, rete interna,
  nessun accesso internet.
- IdP di test abilitato via seed DB (alias `spid-validator`), client `__spid_verifica__` come RP.
- Script Playwright: `/verifica` → discovery → AuthnRequest → login IdP demo → ACS → token;
  asserzioni su firma, `fiscalNumber`, claim attesi; varianti persona giuridica ed eIDAS se
  abilitati.
- Cookie `Secure`: nginx con certificato self-signed nello stack di test.
- Trigger: job in coda che verifica se cambiano `satosa/plugins/spidsaml2.py`,
  `satosa/Dockerfile`, `satosa/requirements-runtime.*`, sezioni SPID del generatore
  (`config-api/app/satosa_config_generator.py`), altrimenti verde senza eseguire; + settimanale
  su main non bloccante (issue se fallisce).
- Verifica preliminare: modalità demo attivabile da env e metadata SP da URL interno.
- **Dopo** che il test è stabile: decidere se `pysaml2`/`satosa`/digest iam-proxy-italia
  passano ad auto-merge (CIE e `cryptography` restano manuali finché non c'è un e2e CIE).

## 5. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| `latest` = produzione: una release rotta raggiunge subito i 2 ambienti | smoke stack completo prima del tag (F4), rollback `latest-YYYYMMDD`, verify-images (F6) |
| Action non in elenco → workflow rotto | aggiungere all'elenco nella stessa PR che introduce l'action; verificare composite annidate |
| Merge queue bloccata da un check matrice saltato o da un workflow senza `merge_group` | salto per step, checklist nel piano F2, PR di prova prima di attivare |
| `--require-hashes` incompatibile col venv upstream satosa | analisi nel piano F3; fallback: lock con hash solo per le aggiunte, `--no-deps` |
| `:?` sui segreti blocca un ambiente Portainer senza variabile | verifica preventiva degli ambienti (F6) |
| Utente non-root rompe scrittura su `/satosa-conf` condiviso | uid comune tra satosa e config-api, test DR completo (F6) |
| Autofix con tool di terze parti che modifica file non previsti | allowlist di file sul commit (F5) |
| Fix SPID/CIE in attesa di review manuale troppo a lungo | issue "in attesa" + label; obiettivo di presa in carico ≤ 2 giorni lavorativi |

## 6. Verifica finale

Al termine di F7 (F8 a parte): checklist della baseline compilata in `docs/ci-cd-security.md`
con ✅ su tutte le voci tranne i gap accettati (seconda persona, SLSA L3, secret scanning
generico) e, fino a F8, l'auto-merge delle librerie SPID.
