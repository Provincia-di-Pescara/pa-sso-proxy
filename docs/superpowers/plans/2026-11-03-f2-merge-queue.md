# F2 — Merge queue

Spec: `docs/superpowers/specs/2026-11-03-ci-cd-security-baseline-design.md` §4 F2.

## Obiettivo

Ogni commit che entra in `main` è testato così com'è (PR sopra main aggiornato), senza policy
strict né `update-behind.yml`. Controlli pesanti solo in coda.

## Ordine (vincolante)

La coda va attivata **dopo** il merge della PR con i trigger `merge_group`: se la coda esiste
prima, il gruppo non avvia `CI gate` e resta fermo fino al timeout.

1. PR F2 (questo branch) — workflow con `merge_group`, mergiata **senza** coda (strict ancora
   attivo, come oggi).
2. Ruleset `Main Branch` via API: aggiungere `merge_queue`, `strict` → false.
3. Prova: PR di test (es. commento in un file `docs/`) → `gh pr merge --auto` → entra in coda,
   `CI gate` in coda verde, merge eseguito.
4. Prova negativa (facoltativa): PR che rompe un test solo-coda → espulsa dalla coda.
5. PR Dependabot aperte: `@dependabot rebase` (portano ancora `codeql.yml`/`update-behind`
   vecchi) → auto-merge → coda.

## Modifiche ai workflow (PR)

| File | Modifica |
|---|---|
| `ci-gate.yml` | `on: merge_group`; SHA = `pull_request.head.sha \|\| merge_group.head_sha`; concurrency per PR o `merge_group.head_ref`; timeout 55 min (< 60 della coda) |
| `ci.yml` | + `merge_group`; − `push` su main (doppione della coda); `smoke-config-api-postgres` solo fuori dalla PR |
| `satosa-tests.yml` | + `merge_group`; − `push` su main; `test-satosa-plugins-docker` solo fuori dalla PR |
| `docker.yml` | − `pull_request`, + `merge_group`: build + smoke + Trivy in coda **senza** login/push/tag `sha-` (tag locale `queue`) |
| `publiccode-validate.yml` | + `merge_group` |
| `dependabot-automerge.yml` | `gh pr merge --auto` senza `--squash` (lo impone la coda) |
| `update-behind.yml` | rimosso |
| `CLAUDE.md` | sezione `main` protetto: coda, cosa gira dove, come mergiare |

## Ruleset (passo 2)

`PUT repos/Provincia-di-Pescara/pa-sso-proxy/rulesets/22436189` con le regole attuali più:

```json
{"type":"merge_queue","parameters":{
  "merge_method":"SQUASH","grouping_strategy":"ALLGREEN",
  "max_entries_to_build":5,"max_entries_to_merge":5,
  "min_entries_to_merge":1,"min_entries_to_merge_wait_minutes":5,
  "check_response_timeout_minutes":60}}
```

e `strict_required_status_checks_policy: false` in `required_status_checks`.

## Rischi

- **Workflow nuovo senza `merge_group`** → non gira in coda, il gate non lo vede. Regola in
  CLAUDE.md.
- **`docker.yml` in coda che pubblica**: escluso esplicitamente (login, push e tag `sha-` con
  `!= merge_group`). Verificare nel log della prima coda che lo step Push sia `skipped`.
- **CodeQL default setup in coda**: il gate attende anche i check di app esterne
  (`CodeQL`); se il default setup non partisse su `merge_group` il gate non resterebbe
  appeso (vede solo i check esistenti) e la regola `code_scanning` resta sulla PR.
- **Errore nei comandi gh con coda attiva**: `--squash`/`--admin` rifiutati o ignorati; usare
  `--auto`.

## Fatto quando

- una PR qualunque passa dalla coda e viene mergiata senza intervento;
- una PR Dependabot patch passa da auto-merge → coda → main;
- nel run `docker.yml` della coda lo step Push è `skipped`.
