# Provider setup

TMDB needs `TMDB_READ_TOKEN`. IGDB needs `IGDB_CLIENT_ID` and `IGDB_CLIENT_SECRET` from a confidential Twitch developer application; access tokens renew automatically. OMDb needs `OMDB_API_KEY`. VNDB, MangaUpdates and Steam public review summaries need no key. Set `MUSICBRAINZ_CONTACT` to a maintained operator contact URL or email.

AniList is implemented but disabled by default. Its current terms restrict competing anime/manga trackers, including use of media metadata. Resolve permitted use before setting `ANILIST_ENABLED=true`; the setting itself does not grant permission. See https://docs.anilist.co/guide/terms-of-use.

MangaUpdates covers manga/manhwa/manhua and retains format and source attribution. MusicBrainz albums represent release groups (including EPs/singles), and tracks represent recordings, not specific release editions. Cover Art Archive supplies ID-based album and available recording artwork.

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

Public VNDB, MangaUpdates and Steam smoke checks passed. MusicBrainz search/detail succeeded in diagnostics, with intermittent upstream 503 busy responses in other checks. TMDB and IGDB searches/details have since been verified locally with operator credentials. OMDb still needs a key. AniList uses mocked tests until permitted use is resolved.


Apple album discovery is an optional key-free supplementary source (US catalog). The shared transport caches and paces it to at most one request every three seconds. It returns one page of 20 albums, not an exhaustive catalog or a popularity chart. MusicBrainz candidates may receive advisory ranking hints only when artist and title agree; these hints never establish identity. Apple artwork must retain its linked Apple Music badge; see https://performance-partners.apple.com/search-api. MusicBrainz cover URLs use exact release-group/release IDs from https://coverartarchive.org; artwork may be missing or temporarily unavailable.


Album identity can use Apple catalog IDs published in MusicBrainz URL relations. Resolution is bounded to one leading query candidate and one official release lookup, with a strict timeout. These shared IDs permit a combined search card and preserve each source record. Display-only edition groups based on title, artist and full release date do not establish identity: clean/explicit editions remain individually selectable. The ICEMAN live check found separate Apple IDs for clean and explicit editions; they are presented as editions rather than silently merged.


Open Library supports key-free book lookup by work ID, with official covers, earliest publication year, author names and available community ratings. Search is limited to 20 records per page and uses a 64-work, TTL-limited lookup cache; optional descriptions have a two-second deadline and cannot remove the primary record. Requests use an identifying User-Agent and a 1.1-second interval. Intended for user-requested lookup, not bulk harvesting. See https://openlibrary.org/developers/api and https://openlibrary.org/dev/docs/api/covers.

Official VNDB localized titles and IGDB alternate names are preserved as alternative_titles; matching a placeholder can use these aliases without merging unrelated provider records.
# Detail information and availability

TMDB detail lookups append credits, alternative titles, official YouTube trailers,
images and regional watch providers; movie lookups also append release dates and
certifications. Availability is supplied by JustWatch through TMDB and must retain
both credits. Region offers distinguish subscription, free, ads, rental and purchase.
They do not include prices, quality or service deep links: use the returned regional
TMDB watch URL to reach the actual viewing links. An empty region means no offers
were reported, not proof that the title is unavailable. `watch_status` distinguishes
unrequested (`unknown`), successfully fetched (`ok`) and failed (`unavailable`) data.

IGDB detail lookups include developers, publishers, game modes, themes and player
perspectives. Store links come from explicit source websites or verified external
IDs. Other media use available creator, genre, platform and release fields. Credits
and release lists are bounded; optional missing information is never fabricated.

MusicBrainz album detail lookups retain explicit Spotify album URL relationships.
If needed, one bounded page of up to 20 official releases in that exact group is
checked within the existing three-second optional-link budget. URLs are canonicalized to HTTPS Spotify album IDs; title
matches never generate a Spotify ID. No Spotify credentials are needed for these
source-linked URLs. When no reliable link exists, the webapp retains a labeled search.


Spotify uses `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in the API environment only. Client Credentials tokens renew independently of IGDB/Twitch, with one retry after a 401 and shared Retry-After backoff. Development Mode requires the app owner to have Spotify Premium. This is catalog access, not a personal Spotify account/history connection. Search and artist-release pagination use ten items per request to support current Development Mode limits. Artist works include releases and searched tracks, checked against the exact Spotify artist ID; same-name people are not combined. No deprecated top-tracks, audio-features or recommendations endpoint is used. Missing popularity, label, genres and other fields remain absent; Spotify does not supply audience review scores. Release precision and source attribution are retained. Existing MusicBrainz listening links can enrich from a unique verified Spotify URL; ambiguous links remain individually selectable. Official references: https://developer.spotify.com/documentation/web-api/tutorials/client-credentials-flow , https://developer.spotify.com/documentation/web-api/concepts/quota-modes , https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide .

Album tracks: `GET /v1/albums/{spotify|apple|musicbrainz}/{id}/tracks?page=1` returns source-qualified track Media records, ordering facts, an attributed edition URL and pagination. Spotify pages contain up to 50 tracks; Apple lookup results are restricted to the requested collection. MusicBrainz chooses the earliest reported official release deterministically and labels the edition; recording IDs and available ISRCs are retained. All requests use fixed origins, normal credentials/caching/backoff, a 25-second route budget and bounded responses. The web proxy permits only these explicit routes.

CreatorRefs optionally include source-supplied descriptions, images, facts and published entity links. Descriptions are not invented when absent. Character association lookup is `GET /v1/characters/find?q=...`: one matched character and up to three attributed anime appearances, with adult exclusions and an 18-second budget. Title/creator search remains independent when that optional service fails. Spotify album-track reference: https://developer.spotify.com/documentation/web-api/reference/get-an-albums-tracks .


### Series and collections

`GET /v1/collections/{tmdb|igdb}/{movie|tv|game}/{id}?page=1` returns explicitly supplied catalog groups and a parent, when available. TMDB television entries retain their full-show ID, with separate `show-season-N` and `show-season-N-episode-N` identities. Movie collection IDs and IGDB series IDs use `collection-N`; these can be loaded through the regular item endpoint and saved independently. Show completion never changes individual season/episode completion. Movie collections are ordered by release date; specials follow numbered seasons. IGDB series membership is paged in batches of 50. DLC, expansions and bundles retain their game IDs and relationship labels. MAL, Jikan and AniList supplied relations are exposed as linked works, without inventing a universal franchise parent.

Relationship coverage depends on the catalog. Matching titles alone do not establish membership. Availability for an entire film or show is not asserted for a collection, season or episode. See [TMDB season details](https://developer.themoviedb.org/reference/tv-season-details) and [IGDB collections](https://api-docs.igdb.com/#collection).
