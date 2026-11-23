#!/bin/sh
# Allowlist opzionale per /admin (WebUI di amministrazione).
#
# ADMIN_ALLOWED_CIDRS: IP o CIDR ammessi, separati da virgola
# (es. 10.0.0.0/8,192.0.2.10). Gli altri ricevono 403 da nginx, prima di
# arrivare a config-api. Vuota = nessuna restrizione (opt-in): utile quando la
# restrizione la fa già il reverse proxy davanti allo stack.
# Dietro un reverse proxy serve anche NGINX_TRUSTED_PROXIES (25-real-ip.sh),
# altrimenti nginx vede l'IP del proxy e non quello del client.
#
# Scrive /etc/nginx/conf.d/admin-access.inc (tmpfs), incluso dalle location
# /admin del template. Estensione .inc: nginx.conf include solo conf.d/*.conf.
# Il file viene scritto sempre (anche vuoto) perché l'include non fallisca.
set -eu

out=/etc/nginx/conf.d/admin-access.inc
allowed="${ADMIN_ALLOWED_CIDRS:-}"

write() {
  # Errore esplicito: in ash una redirezione fallita su un blocco non ferma set -e.
  if ! printf '%s' "$1" > "$out"; then
    echo "$0: impossibile scrivere $out" >&2
    exit 1
  fi
}

if [ -z "$allowed" ]; then
  write "# ADMIN_ALLOWED_CIDRS vuota: /admin senza restrizioni di IP
"
  echo "$0: ADMIN_ALLOWED_CIDRS vuota, /admin senza restrizioni di IP"
  exit 0
fi

# Solo caratteri di indirizzi IPv4/IPv6 e CIDR: il valore finisce nella config nginx.
case "$allowed" in
  *[!0-9A-Fa-f:./,\ ]*)
    echo "$0: ADMIN_ALLOWED_CIDRS contiene caratteri non validi: $allowed" >&2
    exit 1
    ;;
esac

conf=""
for cidr in $(echo "$allowed" | tr ',' ' '); do
  conf="${conf}allow $cidr;
"
done
conf="${conf}deny all;
"
write "$conf"
echo "$0: /admin ammesso solo da: $allowed"
