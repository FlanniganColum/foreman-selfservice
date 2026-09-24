#!/bin/sh
set -eu
mkdir -p /etc/nginx/certs
if [ ! -s /etc/nginx/certs/fullchain.pem ] || [ ! -s /etc/nginx/certs/privkey.pem ]; then
  host="${PORTAL_HOSTNAME:-localhost}"
  san="DNS:${host},DNS:localhost,IP:127.0.0.1"
  if echo "$host" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
    san="IP:${host},DNS:localhost,IP:127.0.0.1"
  fi
  echo "No TLS certificate mounted; generating self-signed development certificate for ${host}."
  openssl req -x509 -nodes -newkey rsa:3072 -days 365 \
    -keyout /etc/nginx/certs/privkey.pem \
    -out /etc/nginx/certs/fullchain.pem \
    -subj "/CN=${host}" \
    -addext "subjectAltName=${san}"
fi
