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

`APP_BASE_PATH` must keep the leading slash and must not end with a trailing slash.

## Start The Docker Stack

From the repo root on the VM:

```bash
docker compose --env-file host-nginx.env -f docker-compose.host-nginx.yml up -d --build
```

This starts:

- the FastAPI backend on the Docker network
- the frontend container on the Docker network
- an internal `nginx` container on `127.0.0.1:3001`

The frontend is built for `/morning-brief/`, and the backend runs with `ROOT_PATH=/morning-brief` so API docs and generated URLs stay aligned with the external prefix.

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
```

That proxy strips `/morning-brief/` before the request reaches the containerized `nginx`, which is why the app image is built with the `/morning-brief/` asset base and why the backend uses `ROOT_PATH=/morning-brief`.

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

## Updating Later

When you deploy new code:

```bash
docker compose --env-file host-nginx.env -f docker-compose.host-nginx.yml up -d --build
```

Your SQLite database remains in the named Docker volume `backend_data`.
