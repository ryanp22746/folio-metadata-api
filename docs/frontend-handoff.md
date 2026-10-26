# Frontend handoff — 2026-10-24

Verified locally: TMDB movie search (Interstellar, 20 results); IGDB game search (Portal 2, 19 results), game detail and Steam enrichment through the webapp proxy. MangaUpdates, VNDB and MusicBrainz searches also passed. Both integration PRs are merged. Credentials live in ignored local .env files.

Remaining provider setup:
- OMDb key and live ratings verification.
- AniList remains disabled pending resolution of its usage restrictions.

Frontend priorities:
- Integrate live discovery into the main search experience and clearly distinguish or replace sample catalog data.
- Style results, covers, details, pagination and loading/empty/error states.
- Show provider attribution, provenance, original rating scales and Steam review summaries.
- Verify import, duplicate warnings, preservation of personal edits and persistence end to end. Shared IDs establish duplicates; title-only matches prompt rather than merge.
- Include Manga consistently in navigation and filters.

Before public hosting:
- User authentication and server-side library storage. Current storage is per-browser localStorage without transactional cross-tab duplicate protection.
- TLS/reverse proxy, production secrets, access controls, backups and operator contact; follow deployment.md. Shared quotas/cache are required before multiple API replicas.
- Provider attribution/terms review, including TMDB logo/notice and permitted AniList use.
- Convenient, repeatable local start/restart workflow.


Subsequent frontend implementation: main live search, predictive spacing queries, calibrated relevance, genre/platform/year/library/source filters, detailed source ratings, MusicBrainz artwork, Apple album fallback, conservative shared-ID grouping, selectable album editions, favorite/removal/Undo actions, semantic themes and responsive progress controls are implemented locally. OMDb credentials, AniList permitted use, authenticated server-side library storage and production hosting remain outstanding.
