# Configuration

Copy `backend/.env.example` to `backend/.env` and adjust only what you need.

## Core Runtime

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data.db` | SQLite connection string |
| `TIMEZONE` | `Europe/Athens` | App timezone for "today" logic and scheduler |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5173` (example) | Comma-separated CORS origins |
| `SCHEDULE_HOUR` | `8` | Daily scheduler hour |
| `SCHEDULE_MINUTE` | `30` | Daily scheduler minute |

## LLM Provider Settings

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `openai` | Provider router target (`openai`, `anthropic`, `ollama`, `gemini`, `groq`, `custom`) |
| `LLM_MODEL` | `gpt-4.1-mini` | Model identifier passed to provider |
| `OPENAI_API_KEY` | empty | OpenAI credential |
| `OPENAI_BASE_URL` | `https://api.openai.com` | OpenAI-compatible endpoint |
| `ANTHROPIC_API_KEY` | empty | Anthropic credential |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Anthropic endpoint |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `GEMINI_API_KEY` | empty | Gemini credential |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | Gemini endpoint |
| `GROQ_API_KEY` | empty | Groq credential |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq OpenAI-compatible endpoint |
| `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-120b` | Fallback model for Groq path |
| `GROQ_REASONING_EFFORT` | `medium` | Reasoning hint for Groq models |

If LLM generation fails, briefings still return with structural data. Summary fields can be empty.

## Data Source and Briefing Tuning

| Variable | Default | Purpose |
|---|---|---|
| `TOP_NEWS_SITES` | built-in CSV | Domains used when selecting top-news sources |
| `STRIKE_TAG_URLS` | built-in CSV | Tag pages used for live strike feed |
| `STRIKE_FEED_LIMIT` | `24` | Maximum strike cards selected per run |
| `STRIKE_FEED_USE_LLM` | `false` | Enable LLM scoring/summarization for strike feed |
| `BIRTHDAYS_SOURCE_URL` | `https://www.eortologio.net/` | Name-day source page |
| `BIRTHDAYS_NAMES_LIMIT` | `16` | Max names returned in birthdays panel |
| `QUOTE_OF_DAY_SOURCE_URL` | `https://www.lexigram.gr/ellinognosia/ImerasParoimia.php` | Quote source base URL |

## Weather Settings

| Variable | Default | Purpose |
|---|---|---|
| `WEATHER_LAT` | `37.9838` | Forecast latitude |
| `WEATHER_LON` | `23.7275` | Forecast longitude |
| `WEATHER_CITY_NAME` | `Αθήνα` | Display city name in response |
| `WEATHER_SSL_VERIFY` | `true` | Enable TLS verification for external calls |
| `WEATHER_CA_BUNDLE` | empty | Custom CA bundle path (preferred in corp networks) |
| `WEATHER_ALLOW_INSECURE_FALLBACK` | `false` | Retry with `verify=False` on TLS errors |

## Logging

| Variable | Default | Purpose |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Root logger level |
| `APP_LOG_LEVEL` | `INFO` | `app.*` logger level |
| `HTTPX_LOG_LEVEL` | `WARNING` | HTTP client logs |
| `UVICORN_ACCESS_LOG_LEVEL` | `WARNING` | Uvicorn access logs |

## Notes

- `WEATHER_CA_BUNDLE` is the safest fix when TLS fails in managed/corporate environments.
- `WEATHER_SSL_VERIFY=false` is insecure and should be temporary.
- Strike feed and weather services share TLS behavior variables for outbound HTTP.
