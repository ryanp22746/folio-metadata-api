# Changelog

## 0.3.0

- Spotify and MyAnimeList integration, richer credits, artwork, and creator profiles.
- Source-qualified creator catalogs, including direct MAL studio lookup through Jikan.
- Album track listings, TV seasons/episodes, movie collections, and game series.
- Character associations and expanded cross-media discovery.
- Reading counts and metadata supporting parent-owned progress in the matching webapp.
- Missing-profile fallback, provider isolation, and regression coverage.

Validation: 91 API tests, Ruff lint and formatting. Jikan timed out during local live checks; verify from the deployment host. Container validation runs in CI.

Deploy alongside folio v0.3.0. New optional server settings: MAL_CLIENT_ID, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET. No database migration; personal libraries remain in browser storage.
