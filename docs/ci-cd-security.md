# CI/CD e sicurezza della supply chain

Stato dell'allineamento alla baseline ComunicaPA
(spec: `docs/superpowers/specs/2026-11-03-ci-cd-security-baseline-design.md`).

## Repository

| Controllo | Dove |
|---|---|
| `main` protetto: PR obbligatoria, solo squash, thread risolti, merge queue, required check unico `CI gate` | ruleset "Main Branch" |
| Nessun alert CodeQL nuovo (errori, sicurezza high+) | ruleset, regola `code_scanning` |
| Tag `v*` immutabili salvo admin | ruleset `release-tags` |
| Action consentite solo da elenco, pin per SHA obbligatorio | Settings → Actions |
| CodeQL default setup (suite extended) | Settings → Code security |
| Secret scanning + push protection, Dependabot security updates, segnalazione privata vulnerabilità | Settings → Code security |
| OpenSSF Scorecard settimanale | `scorecard.yml` |
| Proprietari del codice | `.github/CODEOWNERS` |

## Workflow

| Workflow | Quando | Cosa |
|---|---|---|
| `ci-gate.yml` | PR, merge queue | aspetta tutti i run dello stesso SHA; unico required check |
| `ci.yml` | PR (path), coda | pytest config-api (report HTML di copertura come artifact `coverage-*`, 7 giorni), pip-audit, smoke Alembic su postgres |
| `satosa-tests.yml` | PR (path), coda | test host + test plugin nel container satosa (solo coda) |
| `spid-e2e.yml` | PR/coda se cambia codice SPID/OIDC, settimanale (`:latest`) | login SPID end-to-end con spid-saml-check locale (AuthnRequest validata strict da spid-sp-test) |
| `docker.yml` | coda, dispatch | build 3 immagini, smoke, Trivy (soglia assoluta + differenziale vs `:latest`, `scripts/trivy-diff.sh` preso dalla base della coda in `.base`, così la PR non può indebolire il gate che la giudica; `.trivyignore.yaml` resta quello della PR, visibile in review) — senza push |
| `security.yml` | PR, coda, main, giornaliero | dependency-review, Trivy fs (vuln/segreti/misconfig), test autofix |
| `security-autofix.yml` | giornaliero, Security fallito su main | PR di correzione pip HIGH/CRITICAL (SPID/CIE solo revisione manuale) |
| `release.yml` | tag `v*`, giornaliero 03:30 UTC, dispatch | rebuild condizionato, push per digest, Trivy differenziale, SBOM, attestazioni (`attest-build-provenance` + `actions/attest` con `sbom-path`; `attest-sbom` è deprecata), firma cosign, smoke stack, tag `latest` |
| `security-alerts.yml` | giornaliero | issue + fallimento se alert code scanning high/critical aperti |
| `ghcr-cleanup.yml` | settimanale | digest orfani (report, cancellazione con `GHCR_CLEANUP_DELETE`) |
| `tool-version-check.yml` | settimanale (lunedì) | Trivy: PR di aggiornamento (token GitHub App, permesso `workflows`, dopo 3 giorni, mai auto-merge); pip-audit: issue `toolchain` dopo 7 giorni |
| `upstream-check.yml` | settimanale | issue per nuove release di iam-proxy-italia |
| `dependabot-automerge.yml` | PR dependabot | auto-merge patch/minor, revisione manuale per major e librerie SPID/CIE |
| `scorecard.yml` | settimanale, main | OpenSSF Scorecard |

Ogni workflow: permessi minimi a livello di job, `persist-credentials: false`,
`step-security/harden-runner` (`block`, endpoint consentiti per job; Docker Hub serve i layer da più CDN, vanno consentiti tutti: `production.cloudflare.docker.com`, `production.cloudfront.docker.com`, `docker-images-prod.s3.dualstack.us-east-1.amazonaws.com`), `timeout-minutes`, `concurrency`, tool a versione fissa.

## Dipendenze

- pip: `.in` + lock con hash, install `--require-hashes` (+ `--no-deps` e `pip check` nei Dockerfile).
- Immagini base e servizi del compose fissati per digest.
- Dependabot giornaliero con cooldown 7 giorni (14 per le major pip); security update senza cooldown.

## Immagini e runtime

- Firma cosign keyless, attestazioni provenance e SBOM CycloneDX su ogni immagine pubblicata.
- Container non-root, `cap_drop: ALL`, `no-new-privileges`, filesystem read-only.
- `VERIFY_IMAGES=true`: lo stack parte solo con firme valide di `release.yml`.
- Verifica manuale e rollback: `docs/deployment.md`.

## Aperto

- Librerie SPID/CIE e immagine base iam-proxy-italia: revisione manuale, per scelta (non
  si automatizza: vedi CLAUDE.md, checklist aggiornamento immagine base).
- Approvazioni obbligatorie in review: oggi 0 (un solo maintainer); CODEOWNERS pronto.
