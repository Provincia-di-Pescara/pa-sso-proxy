# Contribuire a pa-sso-proxy

## Flusso

1. Branch da `main` (`feat/…`, `fix/…`, `ci/…`, `docs/…`). Push diretto su `main` non ammesso.
2. Commit in stile [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `ci:`, `build:`, `docs:`…).
3. PR verso `main` compilando il template (impatto SPID/CIE, migrazioni, variabili).
4. L'unico check obbligatorio è **CI gate**: aspetta tutti i workflow della PR. Quando è verde,
   `gh pr merge <n> --auto` manda la PR in **merge queue**, che riesegue tutto (build immagini,
   smoke, Trivy, test nel container satosa) sopra `main` aggiornato e fa lo squash.
5. Le conversazioni della review vanno risolte prima del merge.

## Sviluppo locale

```bash
cp .env.example .env            # compilare i segreti obbligatori
docker compose up -d --build
cd config-api && pip install --require-hashes -r requirements-dev.txt && pytest
```

Test dei plugin SATOSA: solo nel container (vedi `CLAUDE.md`, sezione "Test satosa/plugins/").

## Test

Ogni nuova funzionalità o correzione arriva con i test che la coprono (pytest in
`config-api/tests/` o `satosa/tests/`). Il codice che legge input non fidati (header,
cookie, parametri OIDC, upload) va coperto anche da test di proprietà con
[Hypothesis](https://hypothesis.readthedocs.io/) (es. `satosa/tests/test_i18n_fuzz.py`).

## Lingua

Documentazione e commit in italiano; issue e PR sono accettate anche in inglese.

## Dipendenze

- pip: si modificano solo i file `.in`, poi `scripts/compile-requirements.sh` (lock con hash,
  compilati in container Linux). Mai `pip install pkg==x` nei Dockerfile.
- Immagini base: fissate per digest, aggiornate da Dependabot.
- Action: pin per SHA completo con `# vX`; una Action di terze parti nuova va aggiunta
  all'elenco consentito del repository **prima** del merge.

## Sicurezza

Vulnerabilità: segnalazione privata, mai issue pubbliche — vedi [SECURITY.md](SECURITY.md).
Pipeline e controlli di sicurezza: [docs/ci-cd-security.md](docs/ci-cd-security.md).
