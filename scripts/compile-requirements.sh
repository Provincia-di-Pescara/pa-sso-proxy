#!/bin/sh
# Rigenera i lock pip con hash (--require-hashes) dai file .in.
# Compila dentro container Linux con la stessa versione Python delle immagini:
# i marker di piattaforma (es. uvloop, solo non-Windows) devono essere quelli
# di produzione, non quelli del PC di chi lancia lo script.
#   config-api       → python 3.14 (config-api/Dockerfile)
#   satosa runtime   → python 3.12 (venv dell'immagine iam-proxy-italia)
#   satosa tests     → python 3.12
# Uso: scripts/compile-requirements.sh [--upgrade-package PKG ...]
set -eu
PIP_TOOLS="pip-tools==7.6.2"
root="$(cd "$(dirname "$0")/.." && pwd)"
compile() { # $1=python $2=dir $3=in $4=out, resto = argomenti extra
  py="$1"; dir="$2"; src="$3"; out="$4"; shift 4
  MSYS_NO_PATHCONV=1 docker run --rm -v "$root:/repo" -w "/repo/$dir" "python:$py-slim" sh -c \
    "pip install -q --root-user-action=ignore $PIP_TOOLS && \
     pip-compile -q --generate-hashes --allow-unsafe --strip-extras --no-emit-index-url \
       --output-file $out $* $src"
}
compile 3.14 config-api requirements.in requirements.txt "$@"
compile 3.14 config-api requirements-dev.in requirements-dev.txt "$@"
compile 3.12 satosa requirements-runtime.in requirements-runtime.txt "$@"
compile 3.12 satosa/tests requirements-test.in requirements-test.txt "$@"
