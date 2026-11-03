#!/usr/bin/env bash
# Decide quali immagini :latest vanno ricostruite (release.yml, schedule/dry_run).
# Portainer riscarica :latest da solo: un rebuild senza motivo = riavvio inutile
# della produzione, quindi si ricostruisce SOLO su causa reale:
#   a  commit su main che toccano l'immagine dopo la revision di :latest
#      (label org.opencontainers.image.revision)
#   b  patch di sistema disponibili dentro l'immagine (apk/apt)
#   c  Trivy (DB aggiornato): HIGH/CRITICAL con fix su pacchetti di sistema
#      (le CVE delle librerie Python le corregge un commit, cioè la causa a)
# Un controllo che non riesce a verificare conta come causa (fallire chiusi).
#
# Uso: scripts/rebuild-check.sh <registry/owner/prefisso> <immagine>...
#   es. scripts/rebuild-check.sh ghcr.io/provincia-di-pescara/pa-sso-proxy satosa config-api nginx
# Output (stdout): JSON [{"image":"satosa","reason":"a: 3 commit; b: 2 pacchetti"}, ...]
#   solo le immagini da ricostruire. Log di dettaglio su stderr.
# Richiede: git (checkout completo di main), docker, jq, trivy.
set -uo pipefail

base="$1"; shift
log() { echo "[rebuild-check] $*" >&2; }

paths_for() { # file che entrano nell'immagine
  case "$1" in
    satosa) echo "satosa/" ;;
    config-api) echo "config-api/" ;;
    nginx) echo "nginx/" ;;
    *) echo "$1/" ;;
  esac
}

out="[]"
for img in "$@"; do
  ref="${base}-${img}:latest"
  reasons=()

  if ! digest="$(docker buildx imagetools inspect "$ref" --format '{{json .Manifest}}' 2>/dev/null | jq -er .digest)"; then
    log "$img: $ref non leggibile"
    out="$(jq -c --arg i "$img" --arg r "latest non leggibile" '. + [{image:$i,reason:$r}]' <<< "$out")"
    continue
  fi
  pinned="${base}-${img}@${digest}"
  log "$img: latest = $digest"
  if ! docker pull -q "$pinned" >/dev/null 2>&1; then
    out="$(jq -c --arg i "$img" --arg r "pull fallito" '. + [{image:$i,reason:$r}]' <<< "$out")"
    continue
  fi

  # a: commit dopo la revision di latest che toccano l'immagine
  rev="$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$pinned" 2>/dev/null || true)"
  if [ -z "$rev" ] || ! git cat-file -e "${rev}^{commit}" 2>/dev/null; then
    reasons+=("a: revision '${rev:-assente}' non trovata nella storia")
  else
    # shellcheck disable=SC2046
    n="$(git rev-list --count "${rev}..HEAD" -- $(paths_for "$img"))"
    [ "$n" -gt 0 ] && reasons+=("a: $n commit dopo ${rev:0:7}")
  fi

  # b: patch di sistema disponibili
  os="$(docker run --rm --user 0 --entrypoint sh "$pinned" -c '. /etc/os-release && echo "$ID"' 2>/dev/null || true)"
  case "$os" in
    alpine)
      n="$(docker run --rm --user 0 --entrypoint sh "$pinned" -c \
        'apk update -q >/dev/null 2>&1 && apk list -u 2>/dev/null | wc -l' 2>/dev/null || echo err)" ;;
    debian|ubuntu)
      n="$(docker run --rm --user 0 --entrypoint sh "$pinned" -c \
        'apt-get update -qq >/dev/null 2>&1 && apt list --upgradable 2>/dev/null | grep -c upgradable' 2>/dev/null || true)"
      n="${n:-0}" ;;
    *) n="err" ;;
  esac
  if [ "$n" = "err" ] || ! [ "$n" -eq "$n" ] 2>/dev/null; then
    reasons+=("b: controllo patch di sistema non riuscito (os='${os}')")
  elif [ "$n" -gt 0 ]; then
    reasons+=("b: $n pacchetti di sistema aggiornabili")
  fi

  # c: CVE HIGH/CRITICAL con fix sui pacchetti di sistema
  if json="$(trivy image --quiet --severity HIGH,CRITICAL --ignore-unfixed --pkg-types os \
      --format json "$pinned" 2>/dev/null)"; then
    n="$(jq '[.Results[]?.Vulnerabilities[]?] | length' <<< "$json")"
    [ "$n" -gt 0 ] && reasons+=("c: $n CVE HIGH/CRITICAL di sistema con fix")
  else
    reasons+=("c: scansione Trivy non riuscita")
  fi

  if [ "${#reasons[@]}" -gt 0 ]; then
    r="$(printf '%s; ' "${reasons[@]}")"; r="${r%; }"
    log "$img: REBUILD ($r)"
    out="$(jq -c --arg i "$img" --arg r "$r" '. + [{image:$i,reason:$r}]' <<< "$out")"
  else
    log "$img: nessuna causa, latest invariato"
  fi
done
echo "$out"
