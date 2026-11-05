#!/usr/bin/env bash
# Trivy differenziale: fallisce se l'immagine nuova ha vulnerabilità
# HIGH/CRITICAL con fix che l'immagine di riferimento (di solito :latest, cioè
# la produzione) non ha. Usato da release.yml (prima dei tag) e da docker.yml
# (merge queue: la regressione blocca il merge, non la release).
#
# Uso: scripts/trivy-diff.sh <immagine-nuova> <immagine-riferimento> <nome>
# Serve trivy su PATH e jq. Rispetta TRIVY_IGNOREFILE.
# Scrive un riepilogo in $GITHUB_STEP_SUMMARY se definito.
set -euo pipefail

new="${1:?immagine nuova}"
old="${2:?immagine di riferimento}"
name="${3:-$new}"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

scan() { trivy image --quiet --severity HIGH,CRITICAL --ignore-unfixed --format json "$1"; }
ids() { jq -r '[.Results[]?.Vulnerabilities[]? | "\(.VulnerabilityID) \(.PkgName) \(.Severity)"] | unique[]' "$1"; }

scan "$new" > "$work/new.json"
ids "$work/new.json" > "$work/new.txt"
if docker buildx imagetools inspect "$old" >/dev/null 2>&1; then
  scan "$old" > "$work/old.json"
  ids "$work/old.json" > "$work/old.txt"
else
  echo "::warning::$old non esiste: nessun confronto possibile"
  : > "$work/old.txt"
fi
comm -23 <(sort "$work/new.txt") <(sort "$work/old.txt") > "$work/regressions.txt"

{
  echo "### Trivy $name"
  echo "HIGH/CRITICAL con fix: nuova $(wc -l < "$work/new.txt"), riferimento $(wc -l < "$work/old.txt"), regressioni $(wc -l < "$work/regressions.txt")"
  if [ -s "$work/new.txt" ]; then echo '```'; cat "$work/new.txt"; echo '```'; fi
} >> "$summary"

if [ -s "$work/regressions.txt" ]; then
  echo "::error::Regressioni rispetto a $old:"
  cat "$work/regressions.txt"
  exit 1
fi
echo "Nessuna regressione rispetto a $old"
