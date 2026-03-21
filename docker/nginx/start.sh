#!/bin/sh
set -eu

domain="${APP_DOMAIN:-}"
server_name="_"
cert_dir=""
if [ -n "$domain" ]; then
  server_name="$domain"
  cert_dir="/etc/letsencrypt/live/$domain"
fi

conf_path="/etc/nginx/conf.d/default.conf"
webroot="/var/www/certbot"
static_root="/usr/share/nginx/html"
reload_interval="${NGINX_RELOAD_INTERVAL_SECONDS:-21600}"

mkdir -p "$webroot"

render_http_only() {
  cat >"$conf_path" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $server_name;

    client_max_body_size 10m;

    location /.well-known/acme-challenge/ {
        root $webroot;
    }

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /docs {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /redoc {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /openapi.json {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location = /health {
        proxy_pass http://backend:8000/health;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        root $static_root;
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
}

render_https() {
  cat >"$conf_path" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $server_name;

    location /.well-known/acme-challenge/ {
        root $webroot;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $server_name;

    ssl_certificate $cert_dir/fullchain.pem;
    ssl_certificate_key $cert_dir/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options SAMEORIGIN;
    add_header Referrer-Policy strict-origin-when-cross-origin;

    client_max_body_size 10m;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /docs {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /redoc {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /openapi.json {
        proxy_pass http://backend:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location = /health {
        proxy_pass http://backend:8000/health;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location / {
        root $static_root;
        try_files \$uri \$uri/ /index.html;
    }
}
EOF
}

render_config() {
  if [ -n "$domain" ] && [ -f "$cert_dir/fullchain.pem" ] && [ -f "$cert_dir/privkey.pem" ]; then
    render_https
  else
    render_http_only
  fi
}

reload_loop() {
  while true; do
    sleep "$reload_interval"
    render_config
    nginx -s reload || true
  done
}

shutdown() {
  nginx -s quit >/dev/null 2>&1 || true
  exit 0
}

trap shutdown INT TERM

render_config
nginx -g "daemon off;" &
nginx_pid=$!

reload_loop &
reload_pid=$!

wait "$nginx_pid"
kill "$reload_pid" >/dev/null 2>&1 || true
wait "$reload_pid" >/dev/null 2>&1 || true
