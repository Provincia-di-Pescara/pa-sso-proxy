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
| `ci.yml` | PR (path), coda | pytest config-api, pip-audit, smoke Alembic su postgres |
| `satosa-tests.yml` | PR (path), coda | test host + test plugin nel container satosa (solo coda) |
| `spid-e2e.yml` | PR/coda se cambia codice SPID/OIDC, settimanale (`:latest`) | login SPID end-to-end con spid-saml-check locale (AuthnRequest validata strict da spid-sp-test) |
| `docker.yml` | coda, dispatch | build 3 immagini, smoke, Trivy — senza push |
| `security.yml` | PR, coda, main, giornaliero | dependency-review, Trivy fs (vuln/segreti/misconfig), test autofix |
| `security-autofix.yml` | giornaliero, Security fallito su main | PR di correzione pip HIGH/CRITICAL (SPID/CIE solo revisione manuale) |
| `release.yml` | tag `v*`, giornaliero 03:30 UTC, dispatch | rebuild condizionato, push per digest, Trivy differenziale, SBOM, attestazioni, firma cosign, smoke stack, tag `latest` |
| `security-alerts.yml` | giornaliero | issue + fallimento se alert code scanning high/critical aperti |
| `ghcr-cleanup.yml` | settimanale | digest orfani (report, cancellazione con `GHCR_CLEANUP_DELETE`) |
| `tool-version-check.yml`, `upstream-check.yml` | settimanale | issue per nuove versioni di tool fissati / iam-proxy-italia |
| `dependabot-automerge.yml` | PR dependabot | auto-merge patch/minor, revisione manuale per major e librerie SPID/CIE |
| `scorecard.yml` | settimanale, main | OpenSSF Scorecard |

Ogni workflow: permessi minimi a livello di job, `persist-credentials: false`,
`step-security/harden-runner` (audit), `timeout-minutes`, `concurrency`, tool a versione fissa.

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

- Auto-merge delle librerie SPID: possibile solo dopo qualche settimana di `spid-e2e.yml`
  stabile e con il job in coda; CIE resta manuale (nessun OP CIE di test locale).
- Approvazioni obbligatorie in review: oggi 0 (un solo maintainer); CODEOWNERS pronto.
- harden-runner da `audit` a `block` dopo aver raccolto gli endpoint reali.
