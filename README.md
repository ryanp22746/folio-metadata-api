# Folio Metadata API

Independent metadata service for Folio. Deploy separately from the webapp on a standard Docker host. The webapp owns users, library entries, progress, and personal edits; this service owns provider integration and normalized metadata.

## Current scope

- VNDB visual novel search and detail lookup, no provider key required.
- TMDB movie and TV search/detail, enabled with a TMDB API Read Access Token.
- Stable provider-qualified IDs, source URLs, retrieval timestamps, optional fields, and IMDb IDs when supplied by TMDB.
- Bearer authentication, input validation, bounded 15-minute in-memory cache, provider pacing/backoff, request limits, timeouts, partial search results, and generated OpenAPI docs.
- No scraping, automatic title-based merging, user database, or direct IMDb integration.

## Local development

Use Python 3.12 (3.10+ supported).

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:METADATA_API_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
# Optional: set TMDB_READ_TOKEN through your local secret manager or shell.
.\.venv\Scripts\python -m uvicorn folio_metadata.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open http://127.0.0.1:8000/docs for the interactive API reference; use Authorize with your service key. OpenAPI is also available at `/openapi.json`. Local uvicorn does not automatically load `.env`; Compose does.

```powershell
$headers = @{ Authorization = "Bearer $env:METADATA_API_KEY" }
Invoke-RestMethod 'http://127.0.0.1:8000/v1/search?q=Ever17&kind=visual_novel' -Headers $headers
Invoke-RestMethod 'http://127.0.0.1:8000/v1/items/vndb/visual_novel/v17' -Headers $headers
```

## HTTP contract

| Route | Purpose |
| --- | --- |
| `GET /healthz` | Process health; does not check third-party availability |
| `GET /v1/search?q=...&kind=movie&page=1` | Search; optional kind is movie, tv, or visual_novel |
| `GET /v1/items/{provider}/{kind}/{identifier}` | Metadata for an explicitly selected source item |

Search returns `results`, `providers`, `partial`, `page`, and `more`. Without a kind, each applicable source is queried; results remain grouped, with up to 20 per media kind. Pagination is provider-local, not a globally ranked index. A provider outage leaves other results usable and marks the response partial. If all requested providers fail or are unconfigured, the response is 503. An empty successful search is 200. Invalid input is 422; invalid credentials 401; missing details 404; service quota exhaustion 429. Errors use FastAPI's `detail` envelope. Every response has a generated `X-Request-ID`.

IDs such as `tmdb:movie:11` and `vndb:visual_novel:v17` identify source records, not universal works. Do not automatically merge by title: remakes, adaptations, editions, and identical names exist. Fetch detail after the user chooses a candidate; store the source ID and timestamp alongside imported fields. Retain personal edits in the webapp and only replace fields the user opts to refresh. Search summaries may omit genres or external IDs available on detail.

Dates preserve provider precision (`2002`, `2002-08`, full dates, or VNDB's `TBA`). Descriptions are untrusted text; VNDB includes markup and is labeled accordingly. Escape text in the frontend, and sanitize any markup renderer. Image content flags are passed through for the client to apply its display preferences. This API is not a content moderation service.

## Deploy on Adam's server

1. Clone the private repository on a Linux host with Docker Compose.
2. Copy `.env.example` to `.env`; set `METADATA_API_KEY` to a random secret of at least 32 characters and optionally set `TMDB_READ_TOKEN`. Keep `.env` outside Git and restrict its permissions (`chmod 600 .env`).
3. Run `docker compose up -d --build`. Check `docker compose ps` and `curl http://127.0.0.1:8000/healthz`.
4. Route a dedicated HTTPS hostname through the host's reverse proxy to `127.0.0.1:8000`. Configure TLS, request/body limits, connection limits, and perimeter rate limits there. Leave the container bound to loopback. If the proxy is in Docker, connect both services to a private Docker network instead of publishing a public port.
5. Set the API base URL and service key in the **Folio server's** secret configuration. Make calls from the webapp backend. Never embed this shared key or provider credentials in browser JavaScript. Browser CORS is intentionally not enabled.
6. Run authenticated search and detail smoke checks. Movie/TV checks require a valid TMDB token. Confirm attribution in the webapp before launch.

Run **one replica and one worker**: cache, request quota (60 authenticated calls/minute), and upstream cooldown state are process-local. VNDB calls are spaced at least two seconds apart; cache misses wait briefly for pacing, while long upstream cooldowns fail fast as provider unavailable. Upstream 429 pauses that provider for at least 60 seconds, honoring numeric Retry-After up to one hour. No automatic retries amplify outages. VNDB also has execution-time quotas, so pacing cannot guarantee absence of 429s. Restarts clear these controls and cache. Add Redis-backed cache and distributed quotas before adding replicas or high-volume use. Provider calls time out after eight seconds per network operation; configure an overall reverse proxy deadline as well.

Container runs without root, with a read-only filesystem and dropped capabilities. No persistent data volume is required. Keep the service key only between trusted backends; public multi-tenant access needs individual credentials and per-client quotas. Log status/request IDs, not tokens or search strings. Uvicorn access logs are disabled in the container to avoid logging queries. Configure application log collection as needed. Public schema/docs contain no secrets; restrict them at the proxy if desired.

For updates, pull a reviewed commit and rebuild. Record the deployed commit; roll back by deploying the previous commit and rebuilding. Rotate keys by coordinating the API and webapp configuration and restarting. No deployment automation or server access has been assumed.

## Providers and usage obligations

- [VNDB Kana API](https://api.vndb.org/kana): free non-commercial API access with rate and execution-time limits. Follow its linked data license; artwork has separate ownership. Broader/commercial use requires reviewing the provider's terms.
- [TMDB API](https://developer.themoviedb.org/docs/authentication-application): set its API Read Access Token. [Attribution requirements](https://developer.themoviedb.org/docs/faq) include an approved TMDB logo and the notice: “This product uses the TMDB API but is not endorsed or certified by TMDB.” Put these in the webapp About/Credits area. Commercial use requires appropriate provider arrangements.
- [IMDb official access](https://data.imdb.com/documentation/api-documentation/getting-access/): requires an AWS Data Exchange subscription and credentials. An IMDb ID supplied by TMDB is only an identifier; it does not provide IMDb ratings or licensed IMDb data. Add a dedicated adapter after access is arranged.

No provider content license is granted by this repository. Keep source attribution when displaying imported metadata and verify retention/redistribution rights for your use case.

## Development

```sh
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Tests use mocked provider responses and require no external credentials. CI also builds the Docker image. Dependency versions are pinned in requirements files; Dependabot proposes updates weekly. Add providers behind `Gateway` with mapping tests and explicit ID/terms handling; preserve the v1 response contract. Breaking changes belong under `/v2`.

