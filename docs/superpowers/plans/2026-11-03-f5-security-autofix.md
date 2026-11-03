# F5 — Correzione autonoma (`security-autofix.yml`)

Spec: §4 F5 e decisione §2.3 (SPID/CIE solo PR).

## Componenti

| File | Ruolo |
|---|---|
| `scripts/security/pip_fix.py` | `plan`: pip-audit su ogni lock + severità OSV + scelta versione; `apply --group`: pin nei `.in` |
| `scripts/security/test/` | unit test su fixture fisse (nessuna rete, mai i file vivi), job `autofix-tests` in `security.yml` |
| `.github/workflows/security-autofix.yml` | giornaliero 01:30 UTC, dopo un fallimento di `Security` su main, dispatch (`force`, `dry_run`) |

## Regole

- Solo HIGH/CRITICAL (severità OSV; severità sconosciuta = trattata come HIGH, fallire chiusi).
- Versione: la più bassa che corregge, > versione nel lock, pubblicata da ≥ 48 h (`force` salta
  solo questo), provenienza PEP 740 (attestazioni verificate da PyPI all'upload) con publisher
  **contenuto** in quelli della versione attuale. Versione attuale senza provenienza →
  "non correggibile in autonomia" (issue), mai pin alla cieca.
- Pin: dipendenza diretta → riga aggiornata; transitiva → riga nuova nel `.in` con advisory e
  condizione di rimozione. Lock rigenerato da `scripts/compile-requirements.sh`. Un pacchetto
  presente nel lock runtime non si corregge nel lock dev (vincolo `-c`).
- Commit via GraphQL `createCommitOnBranch` col token della GitHub App (commit verificati);
  file consentiti solo `requirements*.in/.txt` dei 4 target.
- Gruppi: `auto` → PR + auto-merge (coda); `manual` (pysaml2, cryptojwt, cryptography, pyeudiw,
  satosa, pyop) → PR con label `revisione-manuale`, mai auto-merge.
- Una sola PR aperta per gruppo: se esiste già, il giro salta (stato nella issue).
- Issue unica di stato (in attesa / non correggibili / manuali / in correzione), chiusa quando
  vuota.

## Differenze rispetto alla baseline ComunicaPA

- Niente npm/override: solo pip.
- Immagini base: nessun bump del digest dall'autofix. Le patch di sistema le porta il rebuild
  giornaliero (`rebuild-check.sh` cause b/c, `apk/apt upgrade` + `PKG_REFRESH`); i digest li
  aggiorna dependabot (cooldown 7 giorni). Le CVE delle librerie dentro l'immagine upstream
  iam-proxy-italia restano manuali (§2.3).
- "PR fallita → una PR per pacchetto al giro dopo" non implementato: la PR fallita resta aperta
  e visibile; il giro successivo non ne apre un'altra per lo stesso gruppo.
- Una issue di stato invece di tre.

## Verifica (fatta)

- 14 unit test verdi (scelta versione, età, provenienza diversa/assente, `force`, modifica `.in`,
  dedup runtime/dev, gruppi, severità bassa ignorata).
- `plan` reale sui lock del repo (container Linux): nessuna vulnerabilità, piano vuoto.

## Dopo il merge

`gh workflow run security-autofix.yml -f dry_run=true` → summary e issue di stato.
