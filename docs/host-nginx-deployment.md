# Host Nginx Deployment

Use this option when your VM already has:

- a host-level `nginx` instance running directly on the VM
- Let's Encrypt already configured on that host `nginx`
- another site already listening on `80` and `443`

In this mode, Docker does not manage TLS or public ports.
The app runs behind an internal containerized `nginx` that only binds to `127.0.0.1`, with a separate frontend container behind it.

## Files You Need

1. Copy the host-nginx compose variables:

```bash
cp host-nginx.env.example host-nginx.env
```

2. Copy the backend application config if you have not already:

```bash
cp backend/.env.example backend/.env
```

3. Edit `host-nginx.env` and `backend/.env`.

Defaults in `host-nginx.env`:

- `APP_BASE_PATH=/morning-brief`
- `HOST_BIND_PORT=3001`
- `ADMIN_ENTRY_PATH=/ops-f3d8a1`
- `KEYCLOAK_BIND_PORT=8081`
- `KEYCLOAK_HOSTNAME=https://gerasmark.com/identity`

`APP_BASE_PATH` must keep the leading slash and must not end with a trailing slash.
`ADMIN_ENTRY_PATH` is the hidden React route that triggers the admin login flow.

## Start The Docker Stack

From the repo root on the VM:

```bash
docker compose --env-file host-nginx.env -f docker-compose.host-nginx.yml up -d --build
```

This starts:

- PostgreSQL for Keycloak
- the Keycloak server on `127.0.0.1:${KEYCLOAK_BIND_PORT}`
- the FastAPI backend on the Docker network
- the frontend container on the Docker network
- an internal `nginx` container on `127.0.0.1:3001`

The frontend is built for `/morning-brief/`, bakes in the hidden admin route from `ADMIN_ENTRY_PATH`, and the backend runs with `ROOT_PATH=/morning-brief` so API docs and generated URLs stay aligned with the external prefix.

## Backend Auth Settings

Set these in `backend/.env` on the VM before enabling auth:

- `AUTH_ENABLED=true`
- `PUBLIC_APP_URL=https://gerasmark.com/morning-brief`
- `SESSION_SECRET_KEY=<long-random-secret>`
- `AUTH_COOKIE_SECURE=true`
- `KEYCLOAK_BASE_URL=https://gerasmark.com/identity`
- `KEYCLOAK_REALM=morning-brief`
- `KEYCLOAK_CLIENT_ID=morning-brief-web`
- `KEYCLOAK_CLIENT_SECRET=<client-secret-from-keycloak>`
- `KEYCLOAK_ADMIN_ROLE=briefing_admin`

With `AUTH_ENABLED=false`, the app keeps the old local behavior and does not require Keycloak.

## Keycloak Setup

After the stack is up, open:

- `https://gerasmark.com/identity/`
- `https://gerasmark.com/identity/admin/`

Use the bootstrap credentials from `host-nginx.env` only to manage Keycloak itself.
Do not use the `master` realm for the app. Create a separate realm:

1. Create realm `morning-brief`.
2. Create a confidential OpenID Connect client `morning-brief-web`.
3. Keep Standard Flow enabled.
4. Enable client authentication and copy the generated client secret into `backend/.env` as `KEYCLOAK_CLIENT_SECRET`.
5. Set Valid redirect URIs to `https://gerasmark.com/morning-brief/api/auth/callback`.
6. Set Web Origins to `https://gerasmark.com`.
7. Create a realm role `briefing_admin`.
8. Create your user in the `morning-brief` realm.
9. Assign the `briefing_admin` role to that user.

The bootstrap Keycloak admin and your app admin user should stay separate.

## Host Nginx Config

Inside the existing `server_name gerasmark.com` block on the VM, add:

```nginx
location = /morning-brief {
    return 301 /morning-brief/;
}

location /morning-brief/ {
    proxy_pass http://127.0.0.1:3001/;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /morning-brief;

    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

location = /identity {
    return 301 /identity/;
}

location /identity/ {
    proxy_pass http://127.0.0.1:8081/;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Port 443;
}
```

That proxy strips `/morning-brief/` before the request reaches the containerized `nginx`, which is why the app image is built with the `/morning-brief/` asset base and why the backend uses `ROOT_PATH=/morning-brief`.
The trailing slash on `proxy_pass http://127.0.0.1:8081/;` is intentional so host nginx strips `/identity/` before forwarding to the Keycloak container.

## Reload Host Nginx

After editing the VM's host `nginx` config:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

If your distro does not use `systemctl`, use the equivalent service command for that VM.

## Validate The Deployment

Open:

- `https://gerasmark.com/morning-brief/`
- `https://gerasmark.com/morning-brief/health`
- `https://gerasmark.com/morning-brief/docs`
- `https://gerasmark.com/identity/`
- `https://gerasmark.com${ADMIN_ENTRY_PATH}/`

The hidden admin entry URL is not linked in the public navigation. Visiting it should redirect you to Keycloak and then return you to the admin settings page after login.

## Updating Later

When you deploy new code:

```bash
docker compose --env-file host-nginx.env -f docker-compose.host-nginx.yml up -d --build
```

Your SQLite database remains in the named Docker volume `backend_data`.
Keycloak state remains in the named Docker volume `keycloak_db_data`.
