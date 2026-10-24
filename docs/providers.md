# Provider setup

TMDB needs `TMDB_READ_TOKEN`. IGDB needs `IGDB_CLIENT_ID` and `IGDB_CLIENT_SECRET` from a confidential Twitch developer application; access tokens renew automatically. OMDb needs `OMDB_API_KEY`. VNDB, MangaUpdates and Steam public review summaries need no key. Set `MUSICBRAINZ_CONTACT` to a maintained operator contact URL or email.

AniList is implemented but disabled by default. Its current terms restrict competing anime/manga trackers, including use of media metadata. Resolve permitted use before setting `ANILIST_ENABLED=true`; the setting itself does not grant permission. See https://docs.anilist.co/guide/terms-of-use.

MangaUpdates covers manga/manhwa/manhua and retains format and source attribution. MusicBrainz albums represent release groups (including EPs/singles), and tracks represent recordings, not specific release editions. Cover Art Archive is not integrated.

OMDb supplies ratings by explicit IMDb ID; it is not direct IMDb API access. Ratings retain original scales and sources. Steam uses the current IUserReviewsService/GetAppReviews endpoint and returns aggregate counts, not individual reviews. Totals cover all languages/purchase types with off-topic activity excluded.

Follow each provider's attribution and licensing terms before launch. TMDB requires its approved logo and notice: “This product uses the TMDB API but is not endorsed or certified by TMDB.” MangaUpdates requires credit. Review commercial-use requirements for all providers; public access does not grant unrestricted redistribution rights.

Official references:
- https://developer.themoviedb.org/docs/faq
- https://api.vndb.org/kana
- https://api.mangaupdates.com/
- https://api-docs.igdb.com/
- https://musicbrainz.org/doc/MusicBrainz_API
- https://www.omdbapi.com/
- https://partner.steamgames.com/doc/webapi/IUserReviewsService

Public VNDB, MangaUpdates and Steam smoke checks passed. MusicBrainz search/detail succeeded in diagnostics, with intermittent upstream 503 busy responses in other checks. Credentialed TMDB/IGDB/OMDb live verification remains pending operator credentials. AniList uses mocked tests until permitted use is resolved.
