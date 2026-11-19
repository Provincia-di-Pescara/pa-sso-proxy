#!/bin/sh
# IP reale del client dietro un reverse proxy esterno (Traefik, nginx, ...).
#
# Senza questo file nginx vede come $remote_addr l'IP del proxy davanti a lui e lo
# passa a config-api in X-Real-IP: rate limit e ban del login /admin, log di accesso
# e audit trattano tutti i client come un unico IP (5 errori di chiunque bannano tutti).
#
# NGINX_TRUSTED_PROXIES: IP o CIDR dei proxy fidati, separati da virgola
# (es. la subnet della rete Docker condivisa con Traefik: 172.19.0.0/16). Solo da
# questi si accetta X-Forwarded-For. Vuota = comportamento precedente (nessun real_ip).
#
# Eseguito dall'entrypoint ufficiale dopo 20-envsubst-on-templates.sh; scrive in
# /etc/nginx/conf.d (tmpfs), incluso nel blocco http da nginx.conf.
set -eu

out=/etc/nginx/conf.d/real-ip.conf
trusted="${NGINX_TRUSTED_PROXIES:-}"

if [ -z "$trusted" ]; then
  echo "$0: NGINX_TRUSTED_PROXIES vuota, real_ip disattivato"
  exit 0
fi

# Solo caratteri di indirizzi IPv4/IPv6 e CIDR: il valore finisce nella config nginx.
case "$trusted" in
  *[!0-9A-Fa-f:./,\ ]*)
    echo "$0: NGINX_TRUSTED_PROXIES contiene caratteri non validi: $trusted" >&2
    exit 1
    ;;
esac

conf=""
for proxy in $(echo "$trusted" | tr ',' ' '); do
  conf="${conf}set_real_ip_from $proxy;
"
done
conf="${conf}real_ip_header X-Forwarded-For;
real_ip_recursive on;"

# Errore esplicito: in ash una redirezione fallita su un blocco non ferma set -e.
if ! printf '%s\n' "$conf" > "$out"; then
  echo "$0: impossibile scrivere $out" >&2
  exit 1
fi

echo "$0: real_ip da X-Forwarded-For, proxy fidati: $trusted"
