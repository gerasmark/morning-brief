# Architecture

## High-Level Diagram

`Sources (RSS/Sitemap/Tag pages)` -> `Ingestion` -> `Articles (SQLite)` -> `Clustering + Ranking` -> `Daily summaries + enrichments` -> `Briefing payload` -> `React UI`

## Backend Layers

- `app/main.py`: API routes, app lifecycle, CORS, startup/shutdown wiring
- `services/ingestion.py`: fetch + normalize + dedupe article ingestion
- `services/dedupe.py`: cluster creation from recent article window
- `services/ranking.py`: ranking model for top cluster selection
- `services/summarizer.py`: LLM generation for top/strike summaries
- `services/briefing.py`: orchestration + payload assembly
- `services/scheduler.py`: APScheduler daily pipeline job

## Daily Pipeline Details

1. Source discovery
- Enabled sources are loaded from DB (`sources` table).
- Seeded defaults include RSS and sitemap/news-json sources.

2. Ingestion
- Each source is fetched concurrently with `httpx`.
- URL canonicalization + fingerprinting prevent duplicates.
- Inserts use SQLite `OR IGNORE` semantics.

3. Cluster building
- Candidate window is the latest 24h relative to target day/timezone.
- Articles are grouped using token-set fuzzy similarity + jaccard token overlap.
- Birthday-like stories are filtered from top-news clustering.

4. Ranking
- Clusters are scored using:
  - source coverage
  - article volume
  - recency decay
  - short-term spike signal
  - impact keyword signals
  - average source weight
  - homepage prominence hints
- Top list is bounded (10 to 20 items, default target 15).

5. Summarization
- Daily top summary: 1-3 short Greek paragraphs.
- Daily strike summary: short Greek bullets.
- Provider routing supports OpenAI/Anthropic/Ollama/Gemini/Groq/custom.
- If LLM output is unavailable, summary fields can remain empty.

6. Enrichment
- Weather from Open-Meteo
- Name days from eortologio.net
- Quote of the day from lexigram.gr

7. Persistence and payload
- Final selection is stored in `briefings`.
- Daily summary text is stored in dedicated tables.
- `/api/briefings/today` returns assembled payload and refreshes weather.

## Strike Feed Design

- Live strike cards come from configured tag URLs (`STRIKE_TAG_URLS`).
- Service tries `tag/feed` first, then HTML extraction fallback.
- Cards are deduped by URL and selected with source diversity (round-robin).
- Optional LLM curation can re-score and rewrite summaries.
- Strike cards are live-only; non-today briefing days return no live strike list.

## Data Model (SQLite)

Main tables:
- `sources`: source metadata + weight + enable flag
- `articles`: normalized article rows
- `clusters`, `cluster_articles`: grouped story sets
- `daily_top_summaries`, `daily_strike_summaries`: daily summary text
- `briefings`: per-day aggregate payload references

## Frontend Integration

- `Today` page reads `/api/briefings/today`
- `Archive` page reads `/api/briefings` and `/api/briefings/{day}`
- `Settings` page reads/patches `/api/sources`
- Manual admin actions (`run-ingestion`, `generate-briefing`) are available from the Today page controls
