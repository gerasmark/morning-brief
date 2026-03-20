# API

Base URL: `http://localhost:8000`

## Health

- `GET /health`

Returns:

```json
{"ok": true}
```

## Briefings

- `GET /api/briefings/today`
- `GET /api/briefings`
- `GET /api/briefings/{YYYY-MM-DD}`

Notes:
- `GET /api/briefings/today` auto-generates today briefing if missing.
- If today briefing exists, weather data is refreshed on read.
- `GET /api/briefings/{YYYY-MM-DD}` returns `404` when no briefing exists.
- Strike items are live feed data, so historical days can return empty `strikes`.

Example (today payload shape):

```json
{
  "id": "uuid",
  "day": "2026-03-05",
  "weather": {"city": "Αθήνα"},
  "birthdays": {"names": ["Ανθή"]},
  "quote_of_day": {"quote": "...", "author": "..."},
  "top_summary_md": "...",
  "strike_summary_md": "...",
  "top_stories": [],
  "strikes": []
}
```

## Sources

- `GET /api/sources`
- `PATCH /api/sources/{id}`

`PATCH` body fields (all optional):
- `enabled` (`bool`)
- `weight` (`float`, range `0.0` to `5.0`)
- `feed_url` (`string|null`)
- `sitemap_url` (`string|null`)
- `type` (`rss|sitemap`)

## Articles and clusters

- `GET /api/articles?source=<name>&limit=<n>`
- `GET /api/clusters/{cluster_id}`

Query params for `/api/articles`:
- `source`: exact source name
- `limit`: `1..5000` (default `500`)

Special behavior:
- For source `Ναυτεμπορική`/`naftemporiki`, sorting prioritizes homepage main-feed entries.

## Admin

- `POST /api/admin/run-ingestion`
- `POST /api/admin/generate-briefing`
- `POST /api/admin/send-briefing-email`
- `GET /api/admin/strikes/live`
- `GET /api/admin/strikes/live?debug=true`

`POST /api/admin/run-ingestion`:
- Runs source ingestion
- Regenerates briefing for current day
- Returns source-level stats (`fetched`, `inserted`, HTTP status distribution)

`POST /api/admin/generate-briefing` body:

```json
{"day":"2026-03-05"}
```

If `day` is omitted, current Athens day is used.

`POST /api/admin/send-briefing-email` body:

```json
{"day":"2026-03-05","recipient_emails":["name@example.com","team@example.com"]}
```

Notes:
- If `recipient_emails` is omitted, the backend uses the saved recipients from the Settings page.
- The response includes sender address, subject, and recipient count.

`GET /api/admin/strikes/live` query params:
- `limit`: `1..1000` (default `200`)
- `debug`: include source debugging metadata

## Email Delivery Settings

- `GET /api/delivery/email-settings`
- `PUT /api/delivery/email-settings`

`PUT /api/delivery/email-settings` body:

```json
{
  "transport": "resend_api",
  "auto_send_enabled": true,
  "recipient_emails": ["name@example.com", "team@example.com"]
}
```

Response fields:
- `sender_address`: the configured sender for the selected transport (`EMAIL_FROM_ADDRESS` / `SMTP_USERNAME` for SMTP, `RESEND_FROM_ADDRESS` for Resend)
- `sender_name`: display name used in the `From` header
- `transport`: selected transport (`smtp` or `resend_api`)
- `available_transports`: transport options supported by the backend
- `active_transport_ready`: whether the selected transport is ready to send
- `transport_readiness`: readiness map for each transport
- `schedule_hour`, `schedule_minute`, `timezone`: the daily schedule used for auto-send
- `recipient_emails`: saved recipient list

Common errors:
- `404` for missing source/briefing/cluster
- Validation errors for malformed date or invalid payload fields
- `400` for invalid recipient email addresses or missing transport config

## Explore interactively

Use FastAPI Swagger UI at `http://localhost:8000/docs`.
