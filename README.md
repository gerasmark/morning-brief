# Πρωινό Briefing

Greek morning briefing application for daily news monitoring and summarization.

## What The App Does

Every day the app builds a briefing with:
- Top stories clustered from multiple Greek news sources
- Strike and transport updates
- Weather snapshot + 3-day outlook
- Name day information
- Quote of the day
- Optional email delivery to one or more recipients

The stack:
- Backend API: FastAPI (`/api`)
- Frontend: React + Vite
- Database: SQLite (`backend/data.db`)
- Scheduler: APScheduler (daily ingestion + briefing generation + optional email delivery)
- CLI: Python terminal client (`backend/brief.py`)

## Screenshots

### Today Overview

![Today overview](docs/images/today-overview.png)

### News Grid

![News grid](docs/images/news-grid.png)

### Strikes / Transport

![Strikes and transport](docs/images/strikes-view.png)

## Pipeline Overview

1. Fetch articles from enabled sources (RSS + sitemap/JSON feeds).
2. Normalize and deduplicate articles by canonical URL/fingerprint.
3. Build daily clusters using title similarity and token overlap.
4. Rank clusters by coverage, freshness, impact signals, and source weight.
5. Generate daily summaries (top stories + strikes) through the configured LLM provider.
6. Enrich with weather, name days, and quote of the day.
7. Persist final briefing payload for Today and Archive views.
8. Optionally render the stored payload as an HTML email and send it through SMTP or an HTTPS email API.

## Quick Start

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Default frontend API config:
- `VITE_API_BASE=/api`
- `VITE_BACKEND_URL=http://localhost:8000`

Local URLs:
- Frontend: `http://localhost:5173`
- Backend API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`

## CLI

The project now includes a terminal client for people who want the briefing without the web UI.

Run it from the repo root with the backend virtualenv:

```bash
backend/.venv/bin/python backend/brief.py --help
backend/.venv/bin/python backend/brief.py today
backend/.venv/bin/python backend/brief.py archive --limit 10
backend/.venv/bin/python backend/brief.py sources list
backend/.venv/bin/python backend/brief.py sources set News247 --disable
backend/.venv/bin/python backend/brief.py generate --day 2026-03-05
backend/.venv/bin/python backend/brief.py ingest
```

Available commands:
- `today`: show today's briefing
- `day YYYY-MM-DD`: show one stored briefing
- `archive`: list archived briefings
- `sources list|set`: inspect or update sources
- `articles`: inspect ingested articles
- `generate`: build a briefing
- `ingest`: fetch articles and regenerate today's briefing
- `strikes`: preview live strike cards

Most commands support `--json` for scripting, and briefing-style commands support `--details` to include supporting source rows.
The default terminal view is a colored dashboard. Use `--no-color` or `NO_COLOR=1` if you want plain output.

## First Run Checklist

1. Start backend and verify `GET /health` returns `{"ok": true}`.
2. Start frontend and open the Today page.
3. Trigger ingestion manually (optional but useful on a fresh DB):

```bash
curl -X POST http://localhost:8000/api/admin/run-ingestion
```

4. Force briefing generation for a specific day:

```bash
curl -X POST http://localhost:8000/api/admin/generate-briefing \
  -H 'Content-Type: application/json' \
  -d '{"day":"2026-03-05"}'
```

## Scheduling

On app startup the backend:
- Initializes DB tables
- Seeds default sources
- Starts a daily scheduler job

Default schedule is `08:00` in `Europe/Athens` timezone, controlled by:
- `SCHEDULE_HOUR`
- `SCHEDULE_MINUTE`
- `TIMEZONE`

If auto-send is enabled in the Settings page, the same daily pipeline also sends the morning email after briefing generation.

## Email Delivery

Email delivery supports two transports:

- `smtp`
- `resend_api` over HTTPS (`443`)

- Sender address: `EMAIL_FROM_ADDRESS`
- Fallback sender if empty: `SMTP_USERNAME`
- Sender label: `EMAIL_FROM_NAME`
- Recipients and auto-send toggle: managed from the web `Settings` page
- Resend API key: `RESEND_API_KEY`
- Resend sender: `RESEND_FROM_ADDRESS` (default `onboarding@resend.dev`)

Manual send is available from the `Today` page. Scheduled send runs after the daily briefing job.

## LLM + Fallback Behavior

- Supported providers: `openai`, `anthropic`, `ollama`, `gemini`, `groq`, `custom`
- If summary generation fails, the briefing still returns structural data (stories, strikes, weather, etc.), while summary fields may be empty.
- Strike feed can optionally use LLM curation via `STRIKE_FEED_USE_LLM=true`.

## Production Deployment

The repo now includes a production Docker stack in `docker-compose.prod.yml`.
It builds the FastAPI backend, serves the frontend through `nginx`, and uses Certbot webroot challenges for Let's Encrypt certificates.

Basic VM flow:

```bash
cp compose.env.example .env
cp backend/.env.example backend/.env
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml run --rm certbot-init
docker compose -f docker-compose.prod.yml restart nginx
```

Full deployment notes live in `docs/production-deployment.md`.

## Docs (MkDocs Material)

Run docs locally:

```bash
pip install -r requirements-docs.txt
mkdocs serve -a 127.0.0.1:8001
```

Open `http://127.0.0.1:8001`.

Build static docs:

```bash
mkdocs build
```

## Project Structure

- `backend/` FastAPI app, ingestion, clustering/ranking, summarization, scheduler
- `backend/brief.py` CLI entrypoint for terminal usage
- `frontend/` React UI (`Today`, `Archive`, `Settings`)
- `docs/` MkDocs pages (setup, config, API, architecture)
- `mkdocs.yml` docs site config
