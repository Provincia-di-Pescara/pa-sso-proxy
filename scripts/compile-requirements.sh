#!/bin/sh
# Rigenera i lock pip con hash (--require-hashes) dai file .in.
# Compila dentro container Linux con la stessa versione Python delle immagini:
# i marker di piattaforma (es. uvloop, solo non-Windows) devono essere quelli
# di produzione, non quelli del PC di chi lancia lo script.
#   config-api       → python 3.15 (FROM di config-api/Dockerfile)
#   satosa runtime   → python 3.12 (venv dell'immagine iam-proxy-italia;
#                      FROM di scripts/pip-compile/Dockerfile)
#   satosa tests     → python 3.12
#   pip-tools stesso → scripts/pip-compile/requirements.txt
# Immagini per digest e pip-tools installato con --require-hashes: lo script gira
# anche in security-autofix.yml, nello stesso job del token della GitHub App, e i
# lock che produce finiscono in produzione (un tag flottante o un pip-tools
# compromesso potrebbero alterarli).
# Uso: scripts/compile-requirements.sh [--upgrade-package PKG ...]
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
from_image() { # $1=Dockerfile → immagine "tag@sha256:…" della prima riga FROM
  img="$(sed -n 's/^FROM \([^ ]*\).*/\1/p' "$1" | head -1)"
  case "$img" in
    *@sha256:*) printf '%s' "$img" ;;
    *) echo "$1: FROM senza digest ($img)" >&2; exit 1 ;;
  esac
}
PY315="$(from_image "$root/config-api/Dockerfile")"
PY312="$(from_image "$root/scripts/pip-compile/Dockerfile")"
compile() { # $1=immagine $2=dir $3=in $4=out, resto = argomenti extra
  image="$1"; dir="$2"; src="$3"; out="$4"; shift 4
  MSYS_NO_PATHCONV=1 docker run --rm -v "$root:/repo" -w "/repo/$dir" "$image" sh -c \
    "pip install -q --root-user-action=ignore --require-hashes \
       -r /repo/scripts/pip-compile/requirements.txt && \
     pip-compile -q --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url \
       --output-file $out $* $src"
}
compile "$PY312" scripts/pip-compile requirements.in requirements.txt "$@"
compile "$PY315" config-api requirements.in requirements.txt "$@"
compile "$PY315" config-api requirements-dev.in requirements-dev.txt "$@"
compile "$PY312" satosa requirements-runtime.in requirements-runtime.txt "$@"
compile "$PY312" satosa/tests requirements-test.in requirements-test.txt "$@"
