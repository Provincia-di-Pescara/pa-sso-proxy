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

  # Use Python (guaranteed available) instead of curl (not in Alpine base image).
  # Pass URL and dest via environment variables to avoid any quoting issues.
  if _META_URL="${url}" _META_TMP="${tmp}" python3 - <<'PYEOF'
import os, sys, ssl, urllib.request
url = os.environ["_META_URL"]
tmp = os.environ["_META_TMP"]
try:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "satosa-entrypoint/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = resp.read()
    with open(tmp, "wb") as f:
        f.write(data)
    sys.exit(0)
except Exception as e:
    print(f"[entrypoint] fetch error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
  then
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

# Aggregate XML ufficiale SPID: kept fresh anche da config-api metadata_watcher
# (cron ogni 6h), ma qui tentiamo comunque un fetch fresco ad ogni avvio del
# container, cosi' un volume ricreato/pulito non parte con la copia bundled
# nell'immagine (che puo' essere vecchia di mesi e contenere certificati IdP
# gia' ruotati -> verifica firma FAILED per utenti reali).
# Su fallimento del download il file esistente sul volume NON viene toccato
# (stale-but-valid); la copia bundled e' usata solo se non esiste ancora nulla.
_AGGREGATE_DEST=/satosa-conf/spid-entities-idps.xml
_AGGREGATE_TMP="${_AGGREGATE_DEST}.tmp"
if _META_URL="https://registry.spid.gov.it/metadata/idp/spid-entities-idps.xml" _META_TMP="${_AGGREGATE_TMP}" python3 - <<'PYEOF'
import os, sys, ssl, urllib.request
url = os.environ["_META_URL"]
tmp = os.environ["_META_TMP"]
try:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "satosa-entrypoint/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = resp.read()
    with open(tmp, "wb") as f:
        f.write(data)
    sys.exit(0)
except Exception as e:
    print(f"[entrypoint] spid-entities-idps fetch error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF
then
    mv "${_AGGREGATE_TMP}" "${_AGGREGATE_DEST}"
    echo "[entrypoint] spid-entities-idps.xml aggiornato all'avvio"
else
    rm -f "${_AGGREGATE_TMP}"
    if [ -f "${_AGGREGATE_DEST}" ]; then
        echo "[entrypoint] fetch spid-entities-idps.xml fallito, uso file esistente sul volume"
    else
        echo "[entrypoint] fetch spid-entities-idps.xml fallito, nessun file sul volume: uso copia bundled"
        cp /satosa_proxy/metadata/idp/spid-entities-idps.xml "${_AGGREGATE_DEST}"
    fi
fi

mkdir -p /satosa-conf/locales

# Healthcheck fuori dal log di accesso (rumore: una riga ogni 20 s dal container,
# una ogni 30 s da nginx). Solo GET /.well-known/openid-configuration:
# - healthcheck di satosa (da 127.0.0.1): --log-drain scarta la riga di log solo
#   con status 200, un healthcheck fallito resta nel log;
# - healthcheck di nginx (X-Real-IP loopback: nginx imposta sempre
#   X-Real-IP = $remote_addr, il client non lo sceglie): routing `donotlog:`,
#   deciso prima della risposta; se fallisce lo logga nginx (status != 200).
# Le stesse richieste degli applicativi restano nel log. `last:` chiude la catena
# di routing per ogni altro path.
# Content-Type per pyeudiw: il backend OpenID4VP legge context.http_headers["HTTP_CONTENT_TYPE"],
# chiave presente solo con nginx `uwsgi_pass`; noi usiamo `proxy_pass` verso --http-socket, dove
# uWSGI espone solo CONTENT_TYPE (CGI) -> KeyError/500 sul POST response-uri. La regola va PRIMA
# di quella con `last:`, che chiude il routing per ogni altro path.
# (segnalazione upstream: https://github.com/italia/eudi-wallet-it-python/issues/560)
exec uwsgi \
    --chdir /satosa_proxy \
    --wsgi-file "/satosa_proxy/wsgi_sentry.py" \
    --callable app \
    --http-socket 0.0.0.0:8080 \
    --workers 2 \
    --harakiri 60 \
    --buffer-size 32768 \
    --touch-reload /satosa-conf/.reload \
    --static-map /static/js/spid-idps-default.json=/satosa-conf/spid-idps-default.json \
    --static-map /static/locales=/satosa-conf/locales \
    --static-map /static=/satosa_proxy/static \
    --log-drain '^\[pid: [0-9]+\|app: -?[0-9]+\|req: -?[0-9]+/[0-9]+\] 127\.0\.0\.1 \(\) \{[^}]*\} \[[^]]*\] GET /\.well-known/openid-configuration => generated [0-9]+ bytes in [0-9]+ msecs \(HTTP/1\.[01] 200\)' \
    --route-if-not 'empty:${CONTENT_TYPE} addvar:HTTP_CONTENT_TYPE=${CONTENT_TYPE}' \
    --route-if-not 'equal:${PATH_INFO};/.well-known/openid-configuration last:' \
    --route-if 'equal:${HTTP_X_REAL_IP};127.0.0.1 donotlog:'

