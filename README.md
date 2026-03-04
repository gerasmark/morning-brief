# Πρωινό Briefing (MVP)

Personal Greek news briefing app with:
- FastAPI backend (`/api`) for ingestion, clustering, ranking, summaries, weather
- React frontend for Today's briefing, archive, and source settings
- SQLite local storage
- APScheduler daily run inside FastAPI

## Structure

- `backend/`
- `frontend/`

## Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m app.seed_sources
uvicorn app.main:app --reload --port 8000
```

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Set API base in frontend:

```bash
VITE_API_BASE=http://localhost:8000/api
```

For local Vite dev with `VITE_API_BASE=/api` (default), API calls are proxied to `http://localhost:8000`.
You can override proxy target with:

```bash
VITE_BACKEND_URL=http://localhost:8000
```

## Key API endpoints

- `GET /api/briefings/today`
- `GET /api/briefings/{YYYY-MM-DD}`
- `POST /api/admin/run-ingestion`
- `POST /api/admin/generate-briefing`
- `GET /api/admin/strikes/live`
- `GET /api/sources`
- `PATCH /api/sources/{id}`
- `GET /api/clusters/{id}`

## Notes

- Summaries are generated from titles/snippets only.
- If LLM fails, no summary text is shown.
- "Με μια ματιά" daily summary is generated from top stories and returned as `top_summary_md`.
- By default, today briefing is auto-generated on first request if it doesn't exist yet.
- Optional Gemini setup for LLM:
  - `LLM_PROVIDER=gemini`
  - `GEMINI_API_KEY=...`
  - `LLM_MODEL=gemini-2.0-flash` (or another available Gemini model)
  - Optional fallback when Gemini has no response:
    - `GROQ_API_KEY=...`
    - `GROQ_FALLBACK_MODEL=openai/gpt-oss-120b`
- Weather uses Open-Meteo. If your network injects TLS certificates, set either:
  - `WEATHER_CA_BUNDLE=/path/to/root-ca.pem` (recommended)
  - or `WEATHER_SSL_VERIFY=false` (insecure)
  - or `WEATHER_ALLOW_INSECURE_FALLBACK=true` (retry insecure only after TLS failure)
- Strikes section uses dedicated tag sources (no legacy cluster bubbles):
  - `STRIKE_TAG_URLS` (comma-separated tag pages)
  - optional `STRIKE_FEED_USE_LLM=true` for LLM curation/summaries
  - `STRIKE_FEED_LIMIT` controls returned strike cards
- Top 15 list is constrained by `TOP_NEWS_SITES` (comma-separated site base URLs).

Debug strike feed from all configured sources:

```bash
curl -s "http://localhost:8000/api/admin/strikes/live?limit=500&debug=true" | jq
```
