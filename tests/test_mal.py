import httpx
from fastapi.testclient import TestClient

from folio_metadata.app import create_app
from folio_metadata.config import Settings

KEY = "mal-test-key-with-at-least-32-characters"
AUTH = {"Authorization": "Bearer " + KEY}
ANIME = {
    "id": 42310,
    "title": "Cyberpunk: Edgerunners",
    "mean": 8.6,
    "num_scoring_users": 10000,
    "num_episodes": 10,
    "studios": [{"id": 803, "name": "Trigger"}],
    "alternative_titles": {
        "en": "Cyberpunk: Edgerunners",
        "ja": "Original title",
        "synonyms": ["Edgerunners"],
    },
}


def test_tmdb_retains_origin_evidence_for_anime_filtering():
    from folio_metadata.adapters.catalog import normalize_tmdb

    for language, countries in [("en", ["US"]), ("ja", ["JP"])]:
        media = normalize_tmdb(
            {
                "id": 1,
                "name": "Animated series",
                "genre_ids": [16],
                "original_language": language,
                "origin_country": countries,
            },
            "tv",
            "2026-10-25T00:00:00Z",
        )
        assert media.original_language == language
        assert media.origin_countries == countries
        assert media.kind == "tv"


def test_mal_requires_client_id_and_never_exposes_it():
    with TestClient(create_app(settings=Settings(api_key=KEY))) as c:
        assert ("jikan", "anime") not in c.app.state.gateway.targets(None, None)
        assert ("jikan", "anime") in c.app.state.gateway.targets("anime", None)
        r = c.get("/v1/search?q=cyberpunk&kind=anime&provider=mal", headers=AUTH)
        assert r.status_code == 503
        assert r.json()["detail"]["providers"][0]["status"] == "not_configured"


def test_official_mal_search_and_detail_use_fixed_host_and_server_header():
    def handler(request):
        assert request.url.host == "api.myanimelist.net"
        assert request.headers["X-MAL-CLIENT-ID"] == "client-id-only-on-server"
        assert "authorization" not in request.headers
        if request.url.path == "/v2/anime":
            assert request.url.params["offset"] == "20"
            assert request.url.params["nsfw"] == "false"
            return httpx.Response(
                200,
                json={
                    "data": [{"node": ANIME}],
                    "paging": {"next": "https://api.myanimelist.net/v2/anime?offset=40"},
                },
            )
        assert "related_anime" in request.url.params["fields"]
        return httpx.Response(
            200,
            json={
                **ANIME,
                "pictures": [{"large": "https://cdn.myanimelist.net/image.jpg"}],
                "related_anime": [
                    {"node": {"id": 61990, "title": "Cyberpunk: Edgerunners 2"}, "relation_type": "sequel"}
                ],
            },
        )

    with TestClient(
        create_app(
            settings=Settings(api_key=KEY, mal_client_id="client-id-only-on-server"),
            transport=httpx.MockTransport(handler),
        )
    ) as c:
        assert ("jikan", "anime") not in c.app.state.gateway.targets("anime", None)
        response = c.get("/v1/search?q=cyberpunk&kind=anime&provider=mal&page=2", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["more"]
        assert "client-id-only-on-server" not in response.text
        media = response.json()["results"][0]
        assert media["external_ids"] == {"myanimelist": "42310"}
        assert media["ratings"][0]["value"] == "8.6/10"
        assert media["source"]["provider"] == "mal"
        assert media["credits"][0]["url"] == "https://myanimelist.net/anime/producer/803"
        detail = c.get("/v1/items/mal/anime/42310", headers=AUTH)
        assert detail.status_code == 200
        assert detail.json()["portrait_urls"] == ["https://cdn.myanimelist.net/image.jpg"]
        assert detail.json()["related_media"] == [
            {
                "provider": "mal",
                "kind": "anime",
                "id": "61990",
                "title": "Cyberpunk: Edgerunners 2",
                "relation": "sequel",
            }
        ]
        assert c.get("/v1/items/mal/anime/invalid", headers=AUTH).status_code == 422
