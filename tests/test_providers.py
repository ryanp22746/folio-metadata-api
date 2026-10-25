import asyncio
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from folio_metadata.app import create_app
from folio_metadata.config import Settings
from folio_metadata.transport import ProviderError, Transport

KEY = "provider-tests-service-key-at-least-32"
AUTH = {"Authorization": f"Bearer {KEY}"}
MBID = "c0b2899c-41ab-4907-abf0-ff1962477ff2"


def client(handler, **settings):
    return TestClient(
        create_app(settings=Settings(api_key=KEY, **settings), transport=httpx.MockTransport(handler))
    )


def no_network(request):
    raise AssertionError("This request must not reach any provider")


def test_catalog_and_missing_configuration():
    with client(no_network) as c:
        catalog = c.get("/v1/providers", headers=AUTH)
        assert len(catalog.json()) == 9
        states = {x["provider"]: x["status"] for x in catalog.json()}
        assert states["anilist"] == "disabled"
        assert states["igdb"] == states["omdb"] == states["tmdb"] == "not_configured"
        assert states["musicbrainz"] == states["mangaupdates"] == states["steam"] == "ready"
        assert c.get("/v1/providers").status_code == 401
        for url in ["/v1/items/igdb/game/1", "/v1/items/anilist/anime/1", "/v1/enrich/omdb/tt0076759"]:
            assert c.get(url, headers=AUTH).status_code == 503
        assert "SecretStr" not in catalog.text


@pytest.mark.parametrize(
    "url",
    [
        "/v1/items/musicbrainz/album/123",
        "/v1/items/igdb/movie/1",
        "/v1/items/steam/game/620",
        "/v1/enrich/steam/4294967296",
        "/v1/enrich/omdb/123",
        "/v1/items/anilist/anime/2147483648",
        "/v1/search?q=test&provider=steam",
        "/v1/search?q=test&kind=album&provider=vndb",
        "/v1/search?q=test%0Aquery",
    ],
)
def test_invalid_combinations_never_call_upstream(url):
    with client(no_network) as c:
        assert c.get(url, headers=AUTH).status_code == 422


def test_anilist_variables_partial_dates_and_graphql_failure():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        media = {
            "id": 1,
            "idMal": 1,
            "type": "ANIME",
            "title": {"romaji": "Cowboy Bebop"},
            "startDate": {"year": 1998, "month": 4, "day": None},
            "averageScore": 86,
            "description": "<b>Space</b>",
            "coverImage": None,
        }
        if payload["variables"].get("query") == "broken":
            return httpx.Response(200, json={"errors": [{"message": "secret diagnostics"}]})
        if "id" in payload["variables"]:
            return httpx.Response(200, json={"data": {"Media": media}})
        return httpx.Response(
            200, json={"data": {"Page": {"media": [media], "pageInfo": {"hasNextPage": True}}}}
        )

    with client(handler, anilist_enabled=True) as c:
        response = c.get(
            "/v1/search",
            params={"q": 'title "quoted"', "provider": "anilist", "kind": "anime", "page": 2},
            headers=AUTH,
        )
        assert response.status_code == 200
        result = response.json()["results"][0]
        assert result["release_date"] == "1998-04"
        assert result["external_ids"]["myanimelist"] == "1"
        assert result["description_format"] == "html"
        assert result["ratings"][0]["value"] == "86/100"
        assert calls[0]["variables"]["query"] == 'title "quoted"'
        assert 'title "quoted"' not in calls[0]["query"]
        assert c.get("/v1/items/anilist/anime/1", headers=AUTH).status_code == 200
        error = c.get("/v1/search?q=broken&provider=anilist&kind=anime", headers=AUTH)
        assert error.status_code == 503 and "secret diagnostics" not in error.text


def test_mangaupdates_search_detail_and_formats():
    record = {
        "series_id": 123,
        "title": "Example",
        "type": "Manhwa",
        "year": "2020",
        "url": "https://www.mangaupdates.com/series/abc",
        "image": {"url": {"original": "https://example.org/cover.jpg"}},
        "genres": [{"genre": "Action"}],
        "authors": [{"name": "Author"}],
    }

    def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["page"] == 2 and body["perpage"] == 20
            assert "Manhwa" in body["type"] and "Novel" not in body["type"]
            return httpx.Response(200, json={"results": [{"record": record}], "total_hits": 41})
        return httpx.Response(200, json=record)

    with client(handler) as c:
        data = c.get("/v1/search?q=Example&provider=mangaupdates&page=2", headers=AUTH).json()
        assert data["more"] and data["results"][0]["format"] == "Manhwa"
        item = c.get("/v1/items/mangaupdates/manga/123", headers=AUTH).json()
        assert item["creators"] == ["Author"]
        assert item["release_date"] == "2020"


def test_musicbrainz_entities_pagination_and_identification():
    def handler(request):
        assert "FolioMetadata/" in request.headers["User-Agent"]
        assert "operator@example.org" in request.headers["User-Agent"]
        kind = "recording" if "recording" in request.url.path else "release-group"
        record = {
            "id": MBID,
            "title": "Album",
            "first-release-date": "1969-09",
            "artist-credit": [{"name": "The Beatles"}],
        }
        if "query" in request.url.params:
            assert request.url.params["offset"] == "20" and request.url.params["dismax"] == "true"
            return httpx.Response(200, json={kind + "s": [record], "count": 41})
        assert "ratings" in request.url.params["inc"] and "artist-credits" in request.url.params["inc"]
        return httpx.Response(200, json=record)

    with client(handler, musicbrainz_contact="operator@example.org") as c:
        for kind in ("album", "track"):
            data = c.get(f"/v1/search?q=Album&kind={kind}&page=2", headers=AUTH).json()
            assert data["more"]
            assert data["results"][0]["creators"] == ["The Beatles"]
            assert c.get(f"/v1/items/musicbrainz/{kind}/{MBID}", headers=AUTH).status_code == 200


def test_igdb_oauth_reuse_401_refresh_and_escaped_query():
    tokens, games = [], []

    def handler(request):
        if request.url.host == "id.twitch.tv":
            body = parse_qs(request.content.decode())
            assert body["client_secret"] == ["test-client-secret"]
            assert not request.url.query
            tokens.append(body)
            return httpx.Response(200, json={"access_token": f"token-{len(tokens)}", "expires_in": 3600})
        games.append(request)
        assert request.headers["Client-ID"] == "test-client-id"
        if len(games) == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer token-2"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "Portal",
                    "slug": "portal",
                    "websites": [{"url": "https://store.steampowered.com/app/400/Portal/"}],
                }
            ],
        )

    with client(handler, igdb_client_id="test-client-id", igdb_client_secret="test-client-secret") as c:
        query = 'Portal"; where id > 0; \\ example'
        response = c.get("/v1/search", params={"q": query, "provider": "igdb", "page": 2}, headers=AUTH)
        assert response.status_code == 200
        assert games[0].content.decode().startswith(f"search {json.dumps(query)};")
        assert "offset 20;" in games[0].content.decode()
        assert response.json()["results"][0]["external_ids"]["steam"] == "400"
        assert c.get("/v1/items/igdb/game/1", headers=AUTH).status_code == 200
        assert len(tokens) == 2


def test_tmdb_omdb_enrichment_preserves_original_and_rating_scales():
    def handler(request):
        if request.url.host == "api.themoviedb.org":
            return httpx.Response(
                200, json={"id": 11, "title": "Original title", "external_ids": {"imdb_id": "tt0076759"}}
            )
        assert request.url.params["apikey"] == "test-omdb-secret"
        assert request.url.params["i"] == "tt0076759"
        return httpx.Response(
            200,
            json={
                "Response": "True",
                "imdbID": "tt0076759",
                "Title": "Other title",
                "Ratings": [
                    {"Source": "Internet Movie Database", "Value": "8.6/10"},
                    {"Source": "Rotten Tomatoes", "Value": "93%"},
                    {"Source": "Unknown", "Value": "N/A"},
                ],
            },
        )

    with client(handler, tmdb_token="test-tmdb-secret", omdb_api_key="test-omdb-secret") as c:
        response = c.get("/v1/items/tmdb/movie/11?enrich=true", headers=AUTH)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Original title"
        assert [x["value"] for x in data["enrichments"][0]["ratings"]] == ["8.6/10", "93%"]
        assert data["enrichments"][0]["source"]["provider"] == "omdb"
        assert "test-omdb-secret" not in response.text


def test_failed_enrichment_keeps_primary_item():
    def handler(request):
        if request.url.host == "api.themoviedb.org":
            return httpx.Response(200, json={"id": 11, "title": "Original", "imdb_id": "tt0076759"})
        return httpx.Response(200, json={"Response": "False", "Error": "Request limit reached!"})

    with client(handler, tmdb_token="token", omdb_api_key="token") as c:
        response = c.get("/v1/items/tmdb/movie/11?enrich=true", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["enrichments"] == []
        assert response.json()["enrichment_status"][0]["status"] == "unavailable"


@pytest.mark.parametrize("positive,negative", [(90, 10), (0, 0)])
def test_steam_summary_current_endpoint_and_zero_reviews(positive, negative):
    def handler(request):
        assert request.url.path == "/IUserReviewsService/GetAppReviews/v1/"
        query = json.loads(request.url.params["input_json"])
        assert query["appid"] == 620 and query["languages"] == ["all"]
        assert query["review_type"] == 0 and query["purchase_type"] == 1
        return httpx.Response(
            200,
            json={
                "response": {
                    "query_summary": {
                        "total_positive": positive,
                        "total_negative": negative,
                        "total_reviews": positive + negative,
                        "review_score_desc": "Very Positive",
                    },
                    "reviews": [{"author": {"steamid": "private-user-id"}}],
                }
            },
        )

    with client(handler) as c:
        response = c.get("/v1/enrich/steam/620", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["reviews"]["positive_percent"] == (90 if positive else None)
        assert "private-user-id" not in response.text


def test_search_partial_status_per_kind():
    def handler(request):
        if request.url.path == "/3/search/movie":
            return httpx.Response(200, json={"results": [], "total_pages": 0})
        return httpx.Response(500)

    with client(handler, tmdb_token="token") as c:
        response = c.get("/v1/search?q=test&provider=tmdb", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["partial"]
        assert [(x["kind"], x["status"]) for x in response.json()["providers"]] == [
            ("movie", "ok"),
            ("tv", "unavailable"),
        ]


def test_ambiguous_steam_links_are_not_enriched():
    def handler(request):
        if request.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        assert request.url.host == "api.igdb.com"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "Game",
                    "slug": "game",
                    "websites": [
                        {"url": "https://store.steampowered.com/app/1/"},
                        {"url": "https://store.steampowered.com/app/2/"},
                    ],
                }
            ],
        )

    with client(handler, igdb_client_id="id", igdb_client_secret="secret") as c:
        data = c.get("/v1/items/igdb/game/1?enrich=true", headers=AUTH).json()
        assert "steam" not in data["external_ids"] and data["enrichments"] == []


def test_transport_deadline_cache_bounds_and_backoff():
    async def run():
        async def slow(request):
            await asyncio.sleep(1)
            return httpx.Response(200, json={})

        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as http:
            transport = Transport(http, Settings(provider_timeout=0.02))
            with pytest.raises(ProviderError):
                await transport.request("vndb", "/vn", payload={})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
        ) as http:
            transport = Transport(http, Settings(cache_entries=1, tmdb_token="token"))
            await transport.request("tmdb", "/movie/1")
            transport.next_call["tmdb"] = 0
            await transport.request("tmdb", "/movie/2")
            assert len(transport.cache) == 1 and transport.cache_bytes > 0
            transport._backoff("tmdb", {"Retry-After": "7200"})
            assert transport.next_call["tmdb"] > time.monotonic() + 7100
            with pytest.raises(ProviderError):
                await transport.request("tmdb", "/movie/3")
            # Cached data remains available during upstream cooldown.
            assert (await transport.request("tmdb", "/movie/2")).data == {"ok": True}

    asyncio.run(run())


@pytest.mark.parametrize(
    "body", [None, {}, {"response": {}}, {"response": {"query_summary": {"total_reviews": 5}}}]
)
def test_malformed_steam_responses_are_not_success(body):
    with client(lambda r: httpx.Response(200, json=body)) as c:
        assert c.get("/v1/enrich/steam/620", headers=AUTH).status_code == 503


def test_environment_config_does_not_leak_secrets(monkeypatch):
    monkeypatch.setenv("OMDB_API_KEY", "super-secret-omdb-key")
    monkeypatch.setenv("ANILIST_ENABLED", "false")
    settings = Settings.from_env()
    assert settings.omdb_api_key.get_secret_value() == "super-secret-omdb-key"
    assert "super-secret-omdb-key" not in repr(settings)
    assert settings.anilist_enabled is False


def test_mangaupdates_preserves_popularity_votes():
    from folio_metadata.adapters.mangaupdates import normalize

    result = normalize({"series_id": 1, "title": "Berserk", "rating_votes": 3731}, "2026-10-24T00:00:00Z")
    assert result.rating_count == 3731


def test_music_covers_and_ratings_use_exact_musicbrainz_ids():
    from folio_metadata.adapters.musicbrainz import normalize

    album = normalize(
        {"id": MBID, "title": "Music", "rating": {"value": 4.338, "votes-count": 19}},
        "album",
        "2026-10-24T00:00:00Z",
    )
    assert album.image_url == f"https://coverartarchive.org/release-group/{MBID}/front-500"
    assert album.ratings[0].value == "4.3/5"
    assert album.rating_count == 19
    track = normalize({"id": MBID, "title": "Recording"}, "track", "2026-10-24T00:00:00Z")
    assert track.image_url is None


def test_music_catalog_hints_are_not_identity_matches():
    def handler(request):
        if request.url.host == "itunes.apple.com":
            return httpx.Response(
                200, json={"results": [{"collectionName": "Album", "artistName": "Artist"}]}
            )
        return httpx.Response(
            200,
            json={
                "release-groups": [
                    {"id": MBID, "title": "Album", "artist-credit": [{"name": "Artist"}]},
                    {
                        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        "title": "Album",
                        "artist-credit": [{"name": "Other Artist"}],
                    },
                ],
                "count": 2,
            },
        )

    with client(handler) as c:
        rows = c.get("/v1/search?q=Album&kind=album", headers=AUTH).json()["results"]
        assert rows[0]["search_priority"] == 1.1
        assert rows[1]["search_priority"] is None
        assert rows[0]["external_ids"] == {"musicbrainz": MBID}


def test_apple_album_fallback_survives_musicbrainz_outage():
    def handler(request):
        if request.url.host == "musicbrainz.org":
            return httpx.Response(503)
        record = {
            "wrapperType": "collection",
            "collectionId": 123,
            "collectionName": "Album",
            "artistName": "Artist",
            "collectionViewUrl": "https://music.apple.com/us/album/123",
            "artworkUrl100": "https://example.com/100x100bb.jpg",
        }
        return httpx.Response(200, json={"results": [record]})

    with client(handler) as c:
        result = c.get("/v1/search?q=Album&kind=album", headers=AUTH)
        assert result.status_code == 200
        data = result.json()
        assert data["partial"]
        assert data["results"][0]["source"]["provider"] == "apple"
        assert data["results"][0]["search_priority"] == 1.1
        detail = c.get("/v1/items/apple/album/123", headers=AUTH)
        assert detail.status_code == 200
        assert detail.json()["external_ids"] == {"apple": "123"}
        assert (
            c.get("/v1/search?q=Album&kind=album&provider=apple&page=2", headers=AUTH).json()["results"] == []
        )


def test_musicbrainz_album_identity_uses_published_apple_link():
    from folio_metadata.adapters.musicbrainz import linked_apple_ids

    assert linked_apple_ids(
        {"relations": [{"url": {"resource": "https://music.apple.com/us/album/title/123"}}]}
    ) == {"123"}
    for url in [
        "https://music.apple.com.evil/album/123",
        "http://music.apple.com/album/123",
        "https://music.apple.com/album/123?i=456",
    ]:
        assert not linked_apple_ids({"relations": [{"url": {"resource": url}}]})

    def handler(request):
        if request.url.host == "itunes.apple.com":
            return httpx.Response(
                200,
                json={"results": [{"collectionName": "Album", "artistName": "Artist", "collectionId": 123}]},
            )
        if "query" in request.url.params:
            return httpx.Response(
                200,
                json={
                    "release-groups": [{"id": MBID, "title": "Album", "artist-credit": [{"name": "Artist"}]}],
                    "count": 1,
                },
            )
        if "/release-group/" in request.url.path:
            return httpx.Response(200, json={"releases": [{"id": MBID, "status": "Official"}]})
        return httpx.Response(
            200, json={"relations": [{"url": {"resource": "https://music.apple.com/us/album/123"}}]}
        )

    with client(handler) as c:
        row = c.get("/v1/search?q=Album&kind=album&provider=musicbrainz", headers=AUTH).json()["results"][0]
        assert row["external_ids"] == {"musicbrainz": MBID, "apple": "123"}


def test_tmdb_artwork_prefers_english_png_logo_and_keeps_backdrop():
    from folio_metadata.adapters.catalog import normalize_tmdb

    media = normalize_tmdb(
        {
            "id": 1,
            "title": "Film",
            "backdrop_path": "/wide.jpg",
            "images": {
                "logos": [
                    {"file_path": "/foreign.png", "iso_639_1": "ja", "vote_average": 10},
                    {"file_path": "/english.png", "iso_639_1": "en", "width": 500},
                    {"file_path": "/neutral.png", "iso_639_1": None, "width": 1000},
                    {"file_path": "/vector.svg", "iso_639_1": "en", "vote_average": 10},
                ]
            },
        },
        "movie",
        "2026-10-24T00:00:00Z",
    )
    assert media.logo_url == "https://image.tmdb.org/t/p/w500/english.png"
    assert media.backdrop_url == "https://image.tmdb.org/t/p/w1280/wide.jpg"
    missing = normalize_tmdb({"id": 1, "title": "Film"}, "movie", "2026-10-24T00:00:00Z")
    assert missing.logo_url is None and missing.backdrop_url is None


def test_vndb_backdrop_requires_safe_content_votes():
    from folio_metadata.adapters.catalog import normalize_vn

    data = {
        "id": "v1",
        "title": "VN",
        "screenshots": [
            {"url": "https://s.vndb.org/unsafe.jpg", "sexual": 2, "violence": 0},
            {"url": "https://s.vndb.org/unrated.jpg"},
            {"url": "https://s.vndb.org/safe.jpg", "sexual": 0, "violence": 0},
        ],
    }
    assert normalize_vn(data, "2026-10-24T00:00:00Z").backdrop_url == "https://s.vndb.org/safe.jpg"
    data["screenshots"].pop()
    assert normalize_vn(data, "2026-10-24T00:00:00Z").backdrop_url is None


def test_igdb_optional_logo_outage_keeps_game_and_background():
    def handler(request):
        if request.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.path.endswith("/logos"):
            return httpx.Response(503)
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "name": "Game",
                    "slug": "game",
                    "artworks": [{"url": "//images.igdb.com/igdb/image/upload/t_thumb/art.jpg"}],
                }
            ],
        )

    with client(handler, igdb_client_id="test-id", igdb_client_secret="test-secret") as c:
        response = c.get("/v1/items/igdb/game/1", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["logo_url"] is None
        assert response.json()["backdrop_url"].endswith("/t_720p/art.jpg")


def test_igdb_logo_uses_png_to_preserve_transparency():
    def handler(request):
        if request.url.host == "id.twitch.tv":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.path.endswith("/logos"):
            assert "alpha_channel = true" in request.content.decode()
            return httpx.Response(
                200,
                json=[{"url": "//images.igdb.com/igdb/image/upload/t_thumb/logo.jpg", "alpha_channel": True}],
            )
        return httpx.Response(200, json=[{"id": 1, "name": "Game", "slug": "game"}])

    with client(handler, igdb_client_id="test-id", igdb_client_secret="test-secret") as c:
        response = c.get("/v1/items/igdb/game/1", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["logo_url"] == "https://images.igdb.com/igdb/image/upload/t_720p/logo.png"
