# Production Deployment

This project now includes a production Docker stack for a VM deployment with:

- a FastAPI backend container
- an `nginx` container that serves the built frontend and proxies `/api`
- Let's Encrypt certificate bootstrap with Certbot webroot challenges
- automatic certificate renewal in a background container

## Prerequisites

- Docker Engine with Docker Compose plugin installed on the VM
- a public DNS `A` record pointing your domain to the VM IP
- ports `80` and `443` open on the VM firewall

## Files You Need

1. Copy the compose variables file:

```bash
cp compose.env.example .env
```

2. Copy the backend application config:

```bash
cp backend/.env.example backend/.env
```

3. Edit both files before the first production boot.

## Required Settings

In the repo-root `.env`:

- `APP_DOMAIN`: the public domain that points to the VM
- `LETSENCRYPT_EMAIL`: email used for Let's Encrypt notices
- `LETSENCRYPT_STAGING`: leave `0` for real certificates
- `CERTBOT_FORCE_RENEWAL`: keep `0` unless you need to replace an existing cert

In `backend/.env`:

- set the LLM provider credentials you actually use
- set SMTP or Resend settings if you want email delivery
- if you still call the API from another origin, update `CORS_ALLOW_ORIGINS`

The production stack forces SQLite to `backend/data/data.db` inside a named Docker volume, so your data survives container rebuilds.

## First Production Boot

Run these commands from the repo root on the VM:

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml run --rm certbot-init
docker compose -f docker-compose.prod.yml restart nginx
```

What each step does:

- `up -d --build` builds the backend and frontend images, starts the app, and exposes HTTP on port `80`
- `certbot-init` requests the first certificate for `APP_DOMAIN`
- `restart nginx` reloads the proxy so it begins serving HTTPS with the new certificate immediately

After that, open:

- `https://YOUR_DOMAIN`
- `https://YOUR_DOMAIN/health`
- `https://YOUR_DOMAIN/docs`

## Renewal Behavior

- `certbot-renew` stays running and executes `certbot renew` on a loop
- `nginx` regenerates and reloads its config on a loop so renewed certs are picked up without manual intervention

Default intervals are:

- `NGINX_RELOAD_INTERVAL_SECONDS=21600` (6 hours)
- `CERTBOT_RENEW_INTERVAL_SECONDS=43200` (12 hours)

## Updating The Deployment

When you ship code changes:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Your named volumes keep:

- SQLite data
- Let's Encrypt certificates
- ACME challenge webroot files

## Staging Certificates

If you want to test the certificate flow against Let's Encrypt staging first:

1. Set `LETSENCRYPT_STAGING=1`
2. Run `docker compose -f docker-compose.prod.yml run --rm certbot-init`
3. When you are ready for a real certificate, switch `LETSENCRYPT_STAGING=0`
4. Set `CERTBOT_FORCE_RENEWAL=1`
5. Run `docker compose -f docker-compose.prod.yml run --rm certbot-init` again
6. Set `CERTBOT_FORCE_RENEWAL=0`

## Operational Notes

- The backend is not exposed directly to the public internet; only `nginx` publishes ports.
- The frontend uses `/api`, so the browser and API share the same origin in production.
- If DNS is not pointing to the VM yet, the Let's Encrypt request will fail. Start with plain HTTP, fix DNS, then rerun `certbot-init`.
