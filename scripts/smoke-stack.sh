#!/usr/bin/env bash
# Smoke test dello stack completo con le immagini da pubblicare (release.yml),
# PRIMA che ricevano il tag :latest (Portainer lo riscarica da solo: pubblicare
# = andare in produzione). Usa docker-compose.yaml di produzione, volumi vuoti.
#
# Variabili richieste: SATOSA_IMAGE, CONFIG_API_IMAGE, NGINX_IMAGE (ref con digest).
# Uso: scripts/smoke-stack.sh   (dalla root del repo)
#
# Verifica: tutti i servizi su, Alembic a head, primo avvio come una nuova
# installazione (impostazioni ente + certificato SPID generati dalla WebUI admin),
# satosa sano dopo il restart, via nginx: /health, discovery OIDC, metadata SPID
# firmato, login admin.
set -euo pipefail

: "${SATOSA_IMAGE:?}" "${CONFIG_API_IMAGE:?}" "${NGINX_IMAGE:?}"
project="smoke$$"
port="${SMOKE_PORT:-18080}"
# SMOKE_HOST/SMOKE_BIND servono solo per lanciarlo da un container (prova locale).
base="http://${SMOKE_HOST:-127.0.0.1}:${port}"
work="$(mktemp -d)"
jar="$work/cookies"
envfile="$work/.env"
rand() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

cat > "$envfile" <<EOF
PROXY_HOSTNAME=localhost
PROXY_HOST_PORT=${SMOKE_BIND:-127.0.0.1}:${port}
ADMIN_USER=admin
ADMIN_PASSWORD=$(rand)
ADMIN_2FA_ENABLED=false
SESSION_SECRET=$(rand)
POSTGRES_PASSWORD=$(rand)
SATOSA_HASH_SALT=$(rand)
SATOSA_STATE_ENCRYPTION_KEY=$(rand)
CF_HASH_KEY=$(rand)
SATOSA_IMAGE=${SATOSA_IMAGE}
CONFIG_API_IMAGE=${CONFIG_API_IMAGE}
NGINX_IMAGE=${NGINX_IMAGE}
VERIFY_IMAGES=${VERIFY_IMAGES:-false}
EOF
admin_password="$(sed -n 's/^ADMIN_PASSWORD=//p' "$envfile")"

# SMOKE_E2E_SPID=true: aggiunge spid-saml-check e il login SPID end-to-end.
e2e="${SMOKE_E2E_SPID:-false}"
compose_files=(-f docker-compose.yaml)
[ "$e2e" = "true" ] && compose_files+=(-f tests/e2e/docker-compose.yaml)
e2e_python="$(sed -n 's/^FROM //p' config-api/Dockerfile | head -1)"

dc() { docker compose -p "$project" --env-file "$envfile" "${compose_files[@]}" "$@"; }

ok=0
cleanup() {
  if [ "$ok" -ne 1 ]; then
    echo "::group::compose ps / logs"
    dc ps -a || true
    dc logs --no-color --tail 200 || true
    echo "::endgroup::"
  fi
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

step() { echo "== $*"; }
fail() { echo "::error::smoke: $*"; exit 1; }

health() { docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
  "$(dc ps -q "$1")" 2>/dev/null || echo missing; }

wait_healthy() { # $1=servizio $2=secondi
  local i
  for i in $(seq 1 $(( $2 / 5 ))); do
    [ "$(health "$1")" = "healthy" ] && { echo "   $1 healthy"; return 0; }
    sleep 5
  done
  fail "$1 non healthy dopo $2 s (stato: $(health "$1"))"
}

step "avvio stack (volumi vuoti)"
dc pull -q postgres redis
[ "$e2e" = "true" ] && dc pull -q spid-saml-check
# satosa su volumi vuoti non ha cert/chiavi e riparte in loop finché non vengono
# generati: è il comportamento atteso di una nuova installazione.
dc up -d

wait_healthy postgres 60
wait_healthy config-api 180

step "Alembic a head"
dc exec -T config-api alembic current 2>/dev/null | grep -q "(head)" || fail "alembic non a head"

step "nginx → config-api"
for i in $(seq 1 24); do curl -fsS "$base/health" >/dev/null 2>&1 && break; sleep 5; done
curl -fsS "$base/health" >/dev/null || fail "/health via nginx"

step "login admin (2FA off)"
code="$(curl -s -o /dev/null -w '%{http_code}' -c "$jar" -b "$jar" \
  --data-urlencode "username=admin" --data-urlencode "password=${admin_password}" "$base/admin/login")"
[ "$code" = "303" ] || [ "$code" = "302" ] || fail "login admin: HTTP $code"
curl -fsS -b "$jar" "$base/admin/" -o /dev/null || fail "dashboard admin dopo login"

step "impostazioni ente + certificato SPID (prima installazione)"
code="$(curl -s -o /dev/null -w '%{http_code}' -b "$jar" -c "$jar" \
  --data-urlencode "org_name=Ente di prova smoke" --data-urlencode "org_display_name=Ente di prova smoke" \
  --data-urlencode "org_url=https://ente.example.invalid" --data-urlencode "proxy_hostname=localhost" \
  --data-urlencode "ipa_code=c_smoke" --data-urlencode "org_city=Pescara" \
  --data-urlencode "contact_email=smoke@example.invalid" "$base/admin/settings")"
[ "$code" = "303" ] || [ "$code" = "302" ] || [ "$code" = "200" ] || fail "salvataggio impostazioni: HTTP $code"
loc="$(curl -s -o /dev/null -w '%{redirect_url}' -b "$jar" -X POST "$base/admin/certs/generate")"
case "$loc" in *cert_error*) fail "generazione certificato: $loc" ;; esac

step "satosa sano dopo la generazione della config"
wait_healthy satosa 300
wait_healthy nginx 120

step "discovery OIDC via nginx"
curl -fsS "$base/.well-known/openid-configuration" | jq -e '.issuer and .authorization_endpoint' >/dev/null \
  || fail "openid-configuration"

step "metadata SPID firmato via nginx"
curl -fsS "$base/spidSaml2/metadata" -o "$work/metadata.xml" || fail "metadata SPID"
grep -q "EntityDescriptor" "$work/metadata.xml" || fail "metadata SPID senza EntityDescriptor"
grep -q "SignatureValue" "$work/metadata.xml" || fail "metadata SPID non firmato"

step "nessun traceback in satosa dopo l'avvio sano"
if dc logs --no-color satosa --since 30s 2>&1 | grep -q "Traceback"; then
  dc logs --no-color --tail 80 satosa
  fail "traceback nei log di satosa"
fi

if [ "$e2e" = "true" ]; then
  step "e2e SPID: IdP demo spid-saml-check al posto di demo.spid.gov.it"
  wait_healthy spid-saml-check 180
  psql() { dc exec -T postgres psql -U proxy -d proxy -tAc "$1" | head -1 | tr -d '[:space:]'; }
  idp_id="$(psql "UPDATE spid_idps SET metadata_url='http://spid-saml-check:8443/demo/metadata.xml', metadata_hash=NULL, enabled=false WHERE alias='spid-demo' RETURNING id")"
  [ -n "$idp_id" ] || fail "IdP spid-demo assente nel DB"
  # SATOSA legge il metadata dei test IdP da remote-metadata/<alias>.xml, scaricato
  # una volta sola (all'avvio dall'URL originale): va tolto per riscaricarlo.
  dc exec -T config-api rm -f /satosa-conf/remote-metadata/spid-demo.xml
  curl -fsS -o /dev/null -b "$jar" -X POST "$base/admin/idps/$idp_id/refresh" || fail "refresh metadata IdP demo"
  curl -fsS -o /dev/null -b "$jar" -X POST "$base/admin/idps/$idp_id/toggle" || fail "abilitazione IdP demo"
  [ "$(psql "SELECT enabled AND metadata_cache IS NOT NULL FROM spid_idps WHERE id=$idp_id")" = "t" ] \
    || fail "IdP demo non abilitato o senza metadata"

  # L'API di download di spid-saml-check accetta solo URL https: il metadata SP
  # va direttamente nello store dell'IdP demo, utente "validator". Da rifare a
  # ogni cambio del metadata SP (es. ACS persona giuridica).
  register_sp() { # $1 = file metadata SP
    local sp_entity
    sp_entity="$(grep -o 'entityID="[^"]*"' "$1" | head -1 | cut -d'"' -f2)"
    [ -n "$sp_entity" ] || fail "entityID SP non trovato nel metadata"
    dc exec -T -e SP_ENTITY="$sp_entity" spid-saml-check bash -c '. ~/.nvm/nvm.sh >/dev/null; cd /spid-saml-check/src && node -e "
      const D = require(\"./server/lib/database\");
      const xml = require(\"fs\").readFileSync(0, \"utf8\");
      new D().connect().setup().setMetadata(\"validator\", \"e2e\", process.env.SP_ENTITY, \"\", \"main\", \"e2e\", xml);
    "' < "$1" || fail "registrazione metadata SP su spid-saml-check"
  }

  # Login via /verifica in un container sulla rete dello stack.
  spid_login() { # $1 = soggetto (pf|pg) $2 = utente demo $3 = testo atteso nel risultato
    docker run --rm -i --network "${project}_proxy-internal" \
      -e E2E_SUBJECT="$1" -e E2E_USER="$2" -e E2E_EXPECT="$3" \
      -e E2E_ALLOWED_HOSTS="nginx:8080,spid-saml-check:8443" \
      -e E2E_IDP_ENTITY="http://spid-saml-check:8443/demo" \
      "$e2e_python" python - < tests/e2e/spid_login.py
  }

  step "e2e SPID: metadata SP registrato su spid-saml-check"
  register_sp "$work/metadata.xml"

  # Reload graceful di satosa dopo il toggle: attesa che torni sano.
  sleep 15
  wait_healthy satosa 180

  step "e2e SPID: login persona fisica (ada) via /verifica (PKCE, token, userinfo)"
  spid_login pf ada LVLDAA85T50G702B || fail "login SPID persona fisica"

  step "e2e SPID: persona giuridica abilitata (ACS index 4 nel metadata SP)"
  curl -fsS -o /dev/null -b "$jar" --data-urlencode "legal_entity_enabled=yes" \
    --data-urlencode "confirmed=yes" "$base/admin/legal-entity/toggle" || fail "abilitazione persona giuridica"
  sleep 15
  wait_healthy satosa 180
  curl -fsS "$base/spidSaml2/metadata" -o "$work/metadata-pg.xml" || fail "metadata SPID dopo persona giuridica"
  grep -Eq 'AttributeConsumingService[^>]*index="4"' "$work/metadata-pg.xml" \
    || fail "ACS index 4 (persona giuridica) assente nel metadata SP"
  register_sp "$work/metadata-pg.xml"

  step "e2e SPID: login persona giuridica (leonardo, spid:Purpose=PG) con claim aziendali"
  spid_login pg leonardo "Bottega Verrocchio" || fail "login SPID persona giuridica"
fi

ok=1
echo "Smoke stack OK"
