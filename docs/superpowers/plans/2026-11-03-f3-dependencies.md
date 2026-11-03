# F3 — Dipendenze

Spec: `docs/superpowers/specs/2026-11-03-ci-cd-security-baseline-design.md` §4 F3.

## Decisioni

- **pip-tools (`pip-compile --generate-hashes`)**, non uv: dependabot riconosce l'header
  pip-compile e aggiorna `.in` + `.txt` insieme.
- **Compilazione in container Linux** (`scripts/compile-requirements.sh`): config-api con
  `python:3.14-slim`, satosa runtime e test con `python:3.12-slim` (venv upstream
  iam-proxy-italia = 3.12.13). Su Windows i marker di piattaforma cambiano il lock.
- **satosa runtime**: lock delle sole aggiunte al venv upstream (redis, sentry-sdk, certifi,
  urllib3), `--require-hashes --no-deps`, poi `pip check` dopo le rimozioni: fallisce la build
  se le versioni fissate o le rimozioni rompono un pacchetto tenuto. Verificato: build ok,
  `pip check` pulito, test nel container 137 passed.
- **Digest** su tutte le immagini (`FROM` e compose). Il postgres dello smoke Alembic è letto
  dal compose a runtime: niente digest duplicato nel workflow (dependabot non aggiorna i
  service container).
- **Trivy fs** assoluto (non differenziale) su PR/coda/main/giornaliero: oggi è pulito con
  l'unica eccezione `DS-0002` (root) limitata ai 3 Dockerfile fino a F6. Il gate differenziale
  serve per le immagini (F4), non per il repo.
- **dependency-review** solo su PR (confronta base/testa), HIGH+, scope runtime + development.

## File

| File | Modifica |
|---|---|
| `config-api/requirements{,-dev}.in` | nuovi (dirette) |
| `config-api/requirements{,-dev}.txt` | lock con hash |
| `satosa/requirements-runtime.{in,txt}`, `satosa/tests/requirements-test.{in,txt}` | idem |
| `scripts/compile-requirements.sh` | nuovo |
| `config-api/Dockerfile`, `satosa/Dockerfile` | `--require-hashes --no-deps` + `pip check`; digest `FROM` |
| `nginx/Dockerfile` | digest `FROM` |
| `docker-compose.yaml` | digest postgres, redis |
| `.github/dependabot.yml` | giornaliero 01:00 Europe/Rome, `ignore` major postgres |
| `.github/workflows/ci.yml`, `satosa-tests.yml` | `--require-hashes`, pip-audit anche su runtime satosa, postgres dal compose |
| `.github/workflows/security.yml` | nuovo: dependency-review, trivy-fs |
| `.trivyignore` → `.trivyignore.yaml` | ID + paths + statement, via `TRIVY_IGNOREFILE` |
| `CLAUDE.md` | sezioni dipendenze, digest, trivyignore |

## Verifica locale (fatta)

- build `config-api` e `satosa` con i lock: ok;
- `pytest` config-api con `requirements-dev.txt` (python 3.14): 260 passed;
- test plugin satosa nel container: 137 passed, 6 skipped; import dei backend ok;
- `trivy fs` 0.76.1 con `.trivyignore.yaml`: 0 HIGH/CRITICAL.

## Fatto quando

CI verde sulla PR e in coda; la prima PR dependabot pip aggiorna `.in` e `.txt` con hash.
