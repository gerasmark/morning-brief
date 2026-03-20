#!/bin/sh
set -eu

interval="${CERTBOT_RENEW_INTERVAL_SECONDS:-43200}"

while true; do
  certbot renew --quiet
  sleep "$interval"
done
