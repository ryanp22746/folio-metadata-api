# Folio Metadata API

A standalone metadata service for Folio, deployable on a Docker host independently of the webapp. Version 0.3.0 adds music catalogs, creator discovery, and collection metadata. The webapp retains ownership of accounts, library entries, personal edits and progress.

## Integrations

| Provider | Capability | Configuration |
| --- | --- | --- |
| TMDB | Movie and TV search/detail | `TMDB_READ_TOKEN` |
| VNDB | Visual novel search/detail | None |
| MangaUpdates | Manga/manhwa/manhua search/detail | None; source attribution required |
| Open Library | Book search/work details and covers | None; human-facing lookup only |
| Spotify | Album/track search, release details, artist works, artwork and direct listening links | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`; server-side token renewal |
| Apple catalog | Supplementary US album search/detail | No key; one page of 20 results |
| MusicBrainz | Music release-group and recording search/detail | Set an operator contact in `MUSICBRAINZ_CONTACT` |
| IGDB | Game search/detail, platform data and ratings | `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET`; access token renews automatically |
| OMDb | Movie/TV ratings by IMDb ID | `OMDB_API_KEY` |
| Steam | Review summary by Steam app ID | No key; uses current `IUserReviewsService/GetAppReviews` |
| AniList | Anime/manga search/detail | Implemented but **disabled by default**; resolve permitted use before enabling |

AniList's [current terms](https://docs.anilist.co/guide/terms-of-use) restrict competing anime/manga list or tracker services, including use of media metadata. Folio may fall within this restriction. Do not treat setting `ANILIST_ENABLED=true` as permission. Confirm an allowed use or obtain an appropriate arrangement first. AniList stays disabled until that is resolved. Jikan supplies keyless anime discovery; MangaUpdates supplies manga discovery.

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
| `GET /v1/creators/find?q=...` | Possible creator matches across VNDB, TMDB, MangaUpdates, MusicBrainz and Open Library; names never establish shared identity |
| `GET /v1/creators/{provider}/{identifier}/works?page=1` | Paginated works linked to an exact creator ID in that source |
| `GET /v1/search?q=...&kind=manga&provider=mangaupdates&page=1` | Search; kind/provider filters optional |
| `GET /v1/items/{provider}/{kind}/{identifier}` | Full metadata for a selected source record |
| `GET /v1/items/{provider}/{kind}/{identifier}?enrich=true` | Detail plus optional ID-based ratings enrichment |
| `GET /v1/enrich/omdb/tt0076759` | OMDb ratings for a known IMDb title |
| `GET /v1/enrich/steam/620` | Steam aggregate review counts for a known app |

Supported kinds: `movie`, `tv`, `visual_novel`, `anime`, `manga`, `game`, `album`, `track`. OMDb and Steam are enrichment-only providers, so passing either as a search provider returns 422.

`album` maps to MusicBrainz release groups (including albums, EPs and singles); `track` maps to recordings, not a specific track on a release. `manga` includes regional comic formats such as manhwa, retained in the `format` field. MangaUpdates title search stays comics-only. Author-linked records explicitly labeled as novels can be opened as books; the detail lookup verifies the source format before returning them. Audio records remain excluded.

Search returns `results`, `providers`, `partial`, `page`, and `more`. Each status includes provider and media kind; one provider may have multiple entries. Results are grouped in stable provider/kind order, up to 20 per provider/kind. Pagination remains provider-local, not globally ranked. IGDB's `more` is conservative when a full page is returned; the next page may be empty. Use kind/provider filters to avoid unnecessary upstream work.

Unavailable or unconfigured providers leave other results usable and mark the response partial. If every requested target fails, the result is 503. Empty successful searches return 200. Missing records return 404, unsupported IDs/combinations 422, bad credentials 401, and the service request quota 429. Error bodies use FastAPI's `detail` envelope. Each response includes a generated `X-Request-ID`.

`/v1/providers` reports readiness from local configuration; it does not probe upstream availability or validate credentials.

### Safe enrichment and attribution

Items retain provider-qualified IDs, canonical source URLs, and timestamps of the upstream fetch (cache hits preserve the original timestamp). Each rating retains its label, original value/scale, and source. Scores from different populations are not averaged.

Detail responses may include bounded `portrait_urls` and `backdrop_urls` galleries alongside the default image URLs. These use images returned by the existing TMDB, IGDB, VNDB and Open Library lookups; VNDB screenshots retain the same content-safety filtering. Missing galleries default to empty arrays. The client owns artwork display preferences.

VNDB detail includes source-linked writers/scenario staff, directors, designers, artists, composers, vocalists, translators, editors and voice actors. Credit `note` preserves original-script names and edition-specific attribution. These extra fields are fetched only on detail lookup. MangaUpdates preserves author/artist roles; MusicBrainz artist credits and TMDB series creators retain their source profile links. Credits never imply a cross-provider person match.

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



Media detail responses include optional logo_url and backdrop_url fields. TMDB detail requests append image metadata, preferring English/neutral PNG title logos. IGDB detail retrieves artwork/screenshots and an optional transparent logo, requested as PNG to preserve alpha. VNDB detail can select a screenshot only with sexual=0 and violence=0; missing ratings do not qualify. Search responses remain lightweight, and absence of suitable artwork returns null. No artwork request accepts a client-supplied upstream URL.


Open Library supplies key-free book search and work details, bounded to 20 search results and an exact-work search and optional description lookup, with cached requests paced below one per second. Work IDs (OL…W) identify books; covers use the official Covers API and retain source links. Use is intended for human-facing lookup, not bulk harvesting.


### Keyless anime metadata

Jikan is enabled without additional environment settings. It reads public MyAnimeList-derived anime metadata through https://api.jikan.moe/v4. Search requests use `sfw=true`, preserve exact MyAnimeList IDs, and remove duplicate source rows. Details include ratings on their original scale, dates, studios, named staff, voice cast, episode information and source-linked access pages when supplied. Staff/cast failures leave core details usable. No viewing-region availability is inferred from streaming links.

All calls go through the existing authenticated Folio proxy and fixed-host transport. Jikan is conservatively paced at one request per 1.1 seconds with bounded caching, deadlines and Retry-After backoff. It is unofficial, read-only, and can be temporarily rate limited or unavailable. Select Anime with All providers or Jikan in the webapp; no account, API key or browser credential is needed. AniList remains a separately gated integration.


### Official MyAnimeList setup

Register a Folio application at https://myanimelist.net/apiconfig and obtain its **Client ID**. Store it as `MAL_CLIENT_ID` in the root `.env`, then restart the API. The webapp never receives this value. Public catalog search/detail use the `X-MAL-CLIENT-ID` header; this adapter does not log in to your MAL account or change your lists and does not need a Client Secret or user access token. Select Anime / mal in search. When configured, the official source is preferred over Jikan in all-provider searches, avoiding duplicate calls and an unreachable Jikan host delaying official searches. Direct Jikan selection remains available. Official metadata includes ratings, episodes, genres, studio credits, dates and available pictures; extensive person credits are only available when supplied by another linked provider. Current live verification is pending a real Client ID. The Jikan host timed out during local verification, so its mock-tested adapter is not proof of current upstream availability.
