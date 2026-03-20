#!/bin/sh
set -eu

domain="${APP_DOMAIN:-}"
email="${LETSENCRYPT_EMAIL:-}"
staging="${LETSENCRYPT_STAGING:-0}"
force_renewal="${CERTBOT_FORCE_RENEWAL:-0}"

if [ -z "$domain" ]; then
  echo "APP_DOMAIN is required" >&2
  exit 1
fi

if [ -z "$email" ]; then
  echo "LETSENCRYPT_EMAIL is required" >&2
  exit 1
fi

staging_arg=""
if [ "$staging" = "1" ]; then
  staging_arg="--staging"
fi

force_arg=""
if [ "$force_renewal" = "1" ]; then
  force_arg="--force-renewal"
fi

exec certbot certonly \
  --webroot \
  -w /var/www/certbot \
  -d "$domain" \
  --email "$email" \
  --agree-tos \
  --no-eff-email \
  --non-interactive \
  $staging_arg \
  $force_arg
