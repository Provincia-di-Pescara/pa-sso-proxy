#!/bin/sh
set -e
. /.venv/bin/activate
PYTHON_VER=$(python -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')
mkdir -p /satosa-conf

# ---------------------------------------------------------------------------
# Pre-download remote metadata (demo / eIDAS IdPs) into a local directory so
# that pysaml2 never makes outbound HTTP calls at startup.
# Strategy:
#   1. Try to download with curl (10 s timeout, 2 retries, follow redirects).
#   2. On success  → overwrite the local file with fresh content.
#   3. On failure  → keep the existing file if present (stale-but-valid).
#   4. No existing file + failed download → write a minimal valid empty
#      metadata XML so pysaml2 loads without crashing (zero IdPs for that
#      provider, but the rest of the application works normally).
# ---------------------------------------------------------------------------
REMOTE_META_DIR=/satosa-conf/remote-metadata
mkdir -p "${REMOTE_META_DIR}"

_EMPTY_META='<?xml version="1.0"?><EntitiesDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata"/>'

fetch_metadata() {
  alias="$1"
  url="$2"
  dest="${REMOTE_META_DIR}/${alias}.xml"

  tmp="${dest}.tmp"
  if curl --silent --show-error --fail \
       --max-time 10 --retry 2 --retry-delay 2 \
       --location \
       --output "${tmp}" \
       "${url}" 2>/dev/null; then
    mv "${tmp}" "${dest}"
    echo "[entrypoint] metadata OK: ${alias} <- ${url}"
  else
    rm -f "${tmp}"
    if [ -f "${dest}" ]; then
      echo "[entrypoint] metadata fetch failed for '${alias}' (${url}), using cached file"
    else
      echo "[entrypoint] metadata fetch failed for '${alias}' (${url}), writing empty placeholder"
      printf '%s' "${_EMPTY_META}" > "${dest}"
    fi
  fi
}

# Read the generated spid_backend.yaml to discover which remote IdPs are
# configured, then download each one. The config-api writes the file before
# SATOSA starts (shared volume). If the file doesn't exist yet, fall back to
# downloading the known default set so a fresh deploy also works.
SPID_BACKEND_YAML=/satosa-conf/spid_backend.yaml
if [ -f "${SPID_BACKEND_YAML}" ]; then
  # Extract local paths that point into REMOTE_META_DIR and derive alias from filename.
  # The yaml lists them as:  - /satosa-conf/remote-metadata/<alias>.xml
  grep -o "${REMOTE_META_DIR}/[^'\"]*\.xml" "${SPID_BACKEND_YAML}" \
    | sort -u \
    | while read -r path; do
        alias=$(basename "${path}" .xml)
        # Resolve the URL from the matching SpidIdP record stored in the
        # SATOSA conf dir (written by config-api as remote-metadata-urls.json).
        url=$(python3 -c "
import json, sys
try:
    data = json.load(open('/satosa-conf/remote-metadata-urls.json'))
    print(data.get('${alias}', ''))
except Exception:
    print('')
" 2>/dev/null)
        if [ -n "${url}" ]; then
          fetch_metadata "${alias}" "${url}"
        fi
      done
else
  echo "[entrypoint] spid_backend.yaml not found, downloading default remote metadata set"
  fetch_metadata "spid-demo"   "https://demo.spid.gov.it/metadata.xml"
  fetch_metadata "spid-validator" "https://validator.spid.gov.it/metadata.xml"
  fetch_metadata "eidas-qa"    "https://sp-proxy.pre.eid.gov.it/spproxy/idpitmetadata"
  fetch_metadata "eidas-prod"  "https://sp-proxy.eid.gov.it/spproxy/idpitmetadata"
fi

# ---------------------------------------------------------------------------

touch /satosa-conf/.reload

if [ ! -f /satosa-conf/spid-idps-default.json ]; then
    cp /satosa_proxy/static/js/spid-idps-default.json /satosa-conf/spid-idps-default.json
fi

# Use aggregate XML from shared volume (kept fresh by config-api metadata_watcher).
# Fall back to bundled file only if config-api hasn't downloaded it yet.
if [ ! -f /satosa-conf/spid-entities-idps.xml ]; then
    cp /satosa_proxy/metadata/idp/spid-entities-idps.xml /satosa-conf/spid-entities-idps.xml
fi

mkdir -p /satosa-conf/locales

exec uwsgi \
    --chdir /satosa_proxy \
    --wsgi-file "/.venv/lib/${PYTHON_VER}/site-packages/satosa/wsgi.py" \
    --callable app \
    --http-socket 0.0.0.0:8080 \
    --workers 2 \
    --harakiri 60 \
    --buffer-size 32768 \
    --touch-reload /satosa-conf/.reload \
    --static-map /static/js/spid-idps-default.json=/satosa-conf/spid-idps-default.json \
    --static-map /static/locales/eid-it.json=/satosa-conf/locales/eid-it.json \
    --static-map /static/locales/eid-en.json=/satosa-conf/locales/eid-en.json \
    --static-map /static=/satosa_proxy/static
