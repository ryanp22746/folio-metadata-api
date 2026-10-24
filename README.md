# Folio Metadata API

A standalone metadata service for Folio, deployable on a Docker host independently of the webapp. Version 0.2 supports eight providers. The webapp retains ownership of accounts, library entries, personal edits and progress.

## Integrations

| Provider | Capability | Configuration |
| --- | --- | --- |
| TMDB | Movie and TV search/detail | `TMDB_READ_TOKEN` |
| VNDB | Visual novel search/detail | None |
| MangaUpdates | Manga/manhwa/manhua search/detail | None; source attribution required |
| MusicBrainz | Music release-group and recording search/detail | Set an operator contact in `MUSICBRAINZ_CONTACT` |
| IGDB | Game search/detail, platform data and ratings | `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET`; access token renews automatically |
| OMDb | Movie/TV ratings by IMDb ID | `OMDB_API_KEY` |
| Steam | Review summary by Steam app ID | No key; uses current `IUserReviewsService/GetAppReviews` |
| AniList | Anime/manga search/detail | Implemented but **disabled by default**; resolve permitted use before enabling |

AniList's [current terms](https://docs.anilist.co/guide/terms-of-use) restrict competing anime/manga list or tracker services, including use of media metadata. Folio may fall within this restriction. Do not treat setting `ANILIST_ENABLED=true` as permission. Confirm an allowed use or obtain an appropriate arrangement first. Until then, anime discovery through this adapter is unavailable; MangaUpdates supplies manga discovery.

See [provider setup and limitations](docs/providers.md) for credentials, usage obligations, source semantics, and known constraints. Credentials are configured on the server, never accepted from the browser or committed to Git.

## Run locally

Use Python 3.12 (3.10+ supported). PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
$env:METADATA_API_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
.\.venv\Scripts\python -m uvicorn folio_metadata.app:app --host 127.0.0.1 --port 8000 --no-access-log
```

Set provider environment variables as needed. Local uvicorn does not load `.env` automatically; Docker Compose does. Open [interactive documentation](http://127.0.0.1:8000/docs), click Authorize, and enter the service key. The generated schema is at `/openapi.json`.

## API contract

All `/v1` routes require `Authorization: Bearer <METADATA_API_KEY>`.

| Route | Purpose |
| --- | --- |
| `GET /healthz` | Process health, independent of third-party outages |
| `GET /v1/providers` | Configuration readiness, supported media kinds and capabilities |
| `GET /v1/search?q=...&kind=manga&provider=mangaupdates&page=1` | Search; kind/provider filters optional |
| `GET /v1/items/{provider}/{kind}/{identifier}` | Full metadata for a selected source record |
| `GET /v1/items/{provider}/{kind}/{identifier}?enrich=true` | Detail plus optional ID-based ratings enrichment |
| `GET /v1/enrich/omdb/tt0076759` | OMDb ratings for a known IMDb title |
| `GET /v1/enrich/steam/620` | Steam aggregate review counts for a known app |

Supported kinds: `movie`, `tv`, `visual_novel`, `anime`, `manga`, `game`, `album`, `track`. OMDb and Steam are enrichment-only providers, so passing either as a search provider returns 422.

`album` maps to MusicBrainz release groups (including albums, EPs and singles); `track` maps to recordings, not a specific track on a release. `manga` includes regional comic formats such as manhwa, retained in the `format` field. Prose novels and audio records are excluded from MangaUpdates discovery.

Search returns `results`, `providers`, `partial`, `page`, and `more`. Each status includes provider and media kind; one provider may have multiple entries. Results are grouped in stable provider/kind order, up to 20 per provider/kind. Pagination remains provider-local, not globally ranked. IGDB's `more` is conservative when a full page is returned; the next page may be empty. Use kind/provider filters to avoid unnecessary upstream work.

Unavailable or unconfigured providers leave other results usable and mark the response partial. If every requested target fails, the result is 503. Empty successful searches return 200. Missing records return 404, unsupported IDs/combinations 422, bad credentials 401, and the service request quota 429. Error bodies use FastAPI's `detail` envelope. Each response includes a generated `X-Request-ID`.

`/v1/providers` reports readiness from local configuration; it does not probe upstream availability or validate credentials.

### Safe enrichment and attribution

Items retain provider-qualified IDs, canonical source URLs, and timestamps of the upstream fetch (cache hits preserve the original timestamp). Each rating retains its label, original value/scale, and source. Scores from different populations are not averaged.

With `enrich=true`, TMDB detail uses its known IMDb ID for OMDb. IGDB detail uses an unambiguous Steam app URL supplied by IGDB for Steam review summaries. Missing IDs cause no speculative lookup. Multiple Steam IDs are considered ambiguous. Enrichment outages leave primary metadata intact and appear in `enrichment_status`. Results are kept separately in `enrichments`; personal or primary fields are never overwritten.

Steam summaries cover all languages and purchase types with off-topic activity excluded. Zero reviews yields a null percentage. Individual review text and user identifiers are not returned. OMDb is a separate provider, not direct licensed IMDb access.

Descriptions are untrusted provider content and labeled `text`, `html`, or `vndb_markup`. Escape plain text and sanitize rich text before rendering. Dates preserve known precision; do not invent January 1 for a year-only date. Images may have separate rights and content restrictions.

## Deploy later

Follow [the server runbook](docs/deployment.md). It covers environment configuration, Docker Compose, TLS/reverse proxy, secrets, checks, updates and rollback. The service runs as a non-root user with a read-only filesystem, no database, and no required persistent volumes.

One process / one replica is currently supported. Cache and provider quota state are in memory. Add shared cache and distributed rate limiting before horizontal scaling. This is suitable for an initial low-traffic deployment; credentials and live provider checks are still required before launch.

## Validation

```sh
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

Tests use deterministic HTTP fixtures and include authentication, provider mapping, pagination, OAuth refresh, malformed responses, partial results, cache bounds, pacing and deadlines. CI also builds and starts the hardened container.

Opt-in public live checks:

```sh
python -m scripts.smoke
python -m scripts.smoke --provider tmdb --provider igdb --provider omdb
```

The second command requires credentials in the environment. AniList is tested with mocks by default; a live check requires explicitly enabling permitted use and selecting `--provider anilist`. Live checks can fail during provider outages and are intentionally separate from CI. They print only provider names and exception types, never credential-bearing URLs.

## Structure

- `adapters/`: provider queries and normalization.
- `transport.py`: fixed upstream origins, bounded responses/cache, pacing, cooldowns, OAuth and deadlines.
- `gateway.py`: capability registry and orchestration.
- `models.py`: typed public contract.
- `app.py`: authenticated versioned routes.
- `config.py`: validated environment configuration.

Add providers through an adapter and registry entry with mapping/failure tests. Preserve the v1 contract; breaking changes belong in a new version. Dependency updates are proposed by Dependabot. No webapp integration or deployment to a remote server is performed by this repository.

