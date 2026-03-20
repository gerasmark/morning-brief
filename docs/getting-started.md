# Getting Started

## Prerequisites

- Python 3.11+
- Node.js 18+

## 1) Start backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

On startup, the backend:
- creates DB tables (if needed)
- seeds default sources
- starts the daily scheduler job
- prepares the email settings tables used by the web UI

## 2) Use the CLI (optional)

If you want the same briefing flow without the web UI, use the terminal client:

```bash
backend/.venv/bin/python backend/brief.py --help
backend/.venv/bin/python backend/brief.py today
backend/.venv/bin/python backend/brief.py archive --limit 10
backend/.venv/bin/python backend/brief.py sources list
```

Useful flags:
- `--json` for script-friendly output
- `--details` for supporting source rows in briefing views
- `--no-color` for plain terminal output

The CLI reads `backend/.env` and uses `backend/data.db`, so it can be run from the repo root.
By default it renders a colored dashboard view. You can also disable color globally with `NO_COLOR=1`.

Example dashboard output:

![CLI dashboard](images/cli-dashboard.svg)

Example ranked story list:

![CLI top stories](images/cli-top-stories.svg)

## 3) Start frontend

```bash
cd frontend
npm install
npm run dev
```

Default dev proxy setup:
- `VITE_API_BASE=/api`
- `VITE_BACKEND_URL=http://localhost:8000`

## 4) Validate local run

Health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"ok":true}
```

Open the app:
- Frontend: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`

## 5) Trigger data pipeline manually (optional)

Trigger ingestion + briefing generation:

```bash
curl -X POST http://localhost:8000/api/admin/run-ingestion
```

Generate or regenerate briefing for a specific day:

```bash
curl -X POST http://localhost:8000/api/admin/generate-briefing \
  -H 'Content-Type: application/json' \
  -d '{"day":"2026-03-05"}'
```

CLI equivalents:

```bash
backend/.venv/bin/python backend/brief.py ingest
backend/.venv/bin/python backend/brief.py generate --day 2026-03-05
```

Email settings:

```bash
curl http://localhost:8000/api/delivery/email-settings
curl -X PUT http://localhost:8000/api/delivery/email-settings \
  -H 'Content-Type: application/json' \
  -d '{"transport":"resend_api","auto_send_enabled":true,"recipient_emails":["name@example.com","team@example.com"]}'
curl -X POST http://localhost:8000/api/admin/send-briefing-email
```

## 6) Understand scheduler timing

Defaults:
- timezone: `Europe/Athens`
- daily run time: `08:00`

Configured with:
- `TIMEZONE`
- `SCHEDULE_HOUR`
- `SCHEDULE_MINUTE`

When auto-send is enabled in Settings, the same daily run also sends the morning HTML email after the briefing is generated.
All scheduler, ingestion, and email-delivery actions are logged in backend output.
