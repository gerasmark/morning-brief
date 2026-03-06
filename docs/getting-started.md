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

## 2) Start frontend

```bash
cd frontend
npm install
npm run dev
```

Default dev proxy setup:
- `VITE_API_BASE=/api`
- `VITE_BACKEND_URL=http://localhost:8000`

## 3) Validate local run

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

## 4) Trigger data pipeline manually (optional)

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

## 5) Understand scheduler timing

Defaults:
- timezone: `Europe/Athens`
- daily run time: `08:30`

Configured with:
- `TIMEZONE`
- `SCHEDULE_HOUR`
- `SCHEDULE_MINUTE`

All scheduler and ingestion actions are logged in backend output.
