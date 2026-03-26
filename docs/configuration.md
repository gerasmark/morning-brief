# Configuration

Copy `backend/.env.example` to `backend/.env` and adjust only what you need.

## Core Runtime

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data.db` | SQLite connection string |
| `TIMEZONE` | `Europe/Athens` | App timezone for "today" logic and scheduler |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5173` (example) | Comma-separated CORS origins |
| `SCHEDULE_HOUR` | `8` | Daily scheduler hour |
| `SCHEDULE_MINUTE` | `0` | Daily scheduler minute |
| `PUBLIC_APP_URL` | `http://localhost:5173` | External app URL used for OIDC callback and logout redirects |

Notes:
- Relative SQLite URLs are resolved from `backend/`, so `sqlite:///./data.db` points to `backend/data.db`.
- The CLI also reads `backend/.env`, even when you run it from the repo root.
- The email auto-send feature runs on the same daily schedule as briefing generation.

## Admin Auth / Keycloak

| Variable | Default | Purpose |
|---|---|---|
| `AUTH_ENABLED` | `false` | Enable Keycloak-backed admin auth |
| `SESSION_SECRET_KEY` | `change-me-before-production` | Secret used to sign the backend session cookie |
| `AUTH_SESSION_COOKIE_NAME` | `morning_brief_admin` | Cookie name for the signed admin session |
| `AUTH_SESSION_MAX_AGE_SECONDS` | `43200` | Admin session lifetime in seconds |
| `AUTH_COOKIE_SECURE` | `false` in example | Mark the auth cookie as HTTPS-only |
| `KEYCLOAK_BASE_URL` | `http://localhost:8080` | Base URL of Keycloak, for example `https://gerasmark.com/identity` |
| `KEYCLOAK_REALM` | `morning-brief` | Keycloak realm containing your app users |
| `KEYCLOAK_CLIENT_ID` | `morning-brief-web` | Confidential OIDC client used by the backend callback flow |
| `KEYCLOAK_CLIENT_SECRET` | empty | Secret for the confidential Keycloak client |
| `KEYCLOAK_ADMIN_ROLE` | `briefing_admin` | Realm role required for admin-only UI and APIs |

Notes:
- With `AUTH_ENABLED=false`, the app keeps the old local behavior and does not require Keycloak.
- When `AUTH_ENABLED=true`, the backend protects admin APIs and the frontend hides admin controls unless the session is authenticated and has `KEYCLOAK_ADMIN_ROLE`.
- The recommended production value for `PUBLIC_APP_URL` on this VM deployment is `https://gerasmark.com/morning-brief`.

## Email Delivery

| Variable | Default | Purpose |
|---|---|---|
| `SMTP_HOST` | empty | SMTP hostname used for delivery |
| `SMTP_PORT` | `587` | SMTP port |
| `SMTP_USERNAME` | empty | SMTP login username |
| `SMTP_PASSWORD` | empty | SMTP login password |
| `SMTP_USE_TLS` | `true` | Enable STARTTLS for plain SMTP connections |
| `SMTP_USE_SSL` | `false` | Use implicit TLS (`SMTP_SSL`) instead of STARTTLS |
| `SMTP_TIMEOUT_SECONDS` | `20` | SMTP socket timeout |
| `EMAIL_FROM_ADDRESS` | empty | Sender address shown in the email |
| `EMAIL_FROM_NAME` | `Πρωινό Briefing` | Sender display name |
| `RESEND_API_KEY` | empty | Resend API key for HTTPS delivery |
| `RESEND_API_BASE_URL` | `https://api.resend.com` | Resend API base URL |
| `RESEND_TIMEOUT_SECONDS` | `20` | HTTP timeout for Resend requests |
| `RESEND_FROM_ADDRESS` | `onboarding@resend.dev` | Sender address used for Resend API delivery |

Notes:
- If `EMAIL_FROM_ADDRESS` is empty, the app falls back to `SMTP_USERNAME`.
- Recipients, auto-send, and the selected transport are stored in SQLite and managed from the web Settings page.
- `smtp` uses mail ports like `587` or `465`.
- `resend_api` uses HTTPS on port `443`.
- `resend_api` in this app defaults to `onboarding@resend.dev`.
- Resend documents `resend.dev` as a testing domain and says it can only send to the email tied to your Resend account; other recipients can return `403`.
- The app can still generate briefings even when no email transport is configured.

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
