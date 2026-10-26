import httpx
from fastapi.testclient import TestClient

from folio_metadata.app import create_app
from folio_metadata.config import Settings

KEY = "jikan-test-key-with-at-least-32-characters"
AUTH = {"Authorization": "Bearer " + KEY}
ANIME = {
    "mal_id": 42310,
    "title": "Cyberpunk: Edgerunners",
    "title_english": None,
    "title_japanese": "サイバーパンク エッジランナーズ",
    "images": {"jpg": {"large_image_url": "https://cdn.myanimelist.net/images/anime/test.jpg"}},
    "genres": [{"name": "Action"}],
    "themes": [{"name": "Adult Cast"}],
    "score": 8.61,
    "scored_by": 10000,
    "episodes": 10,
    "aired": {"from": "2022-09-13T00:00:00+00:00", "string": "Sep 13, 2022"},
    "studios": [{"name": "Trigger", "url": "https://myanimelist.net/anime/producer/803"}],
    "streaming": [{"name": "Netflix", "url": "https://www.netflix.com/title/81054853"}],
}


def client(handler):
    return TestClient(create_app(settings=Settings(api_key=KEY), transport=httpx.MockTransport(handler)))


def test_jikan_search_is_keyless_safe_paginated_and_attributed():
    def handler(request):
        assert request.url.host == "api.jikan.moe"
        assert request.url.path == "/v4/anime"
        assert request.url.params["sfw"] == "true"
        assert request.url.params["page"] == "2"
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "data": [ANIME, ANIME, {**ANIME, "mal_id": 2, "rating": "Rx - Hentai"}],
                "pagination": {"has_next_page": True},
            },
        )

    with client(handler) as c:
        response = c.get("/v1/search?q=cyberpunk&kind=anime&provider=jikan&page=2", headers=AUTH)
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        media = data["results"][0]
        assert media["id"] == "jikan:anime:42310"
        assert media["external_ids"] == {"myanimelist": "42310"}
        assert media["ratings"][0]["value"] == "8.6/10"
        assert media["source"]["provider"] == "jikan"
        assert data["more"] is True
        assert c.get("/v1/items/jikan/anime/1").status_code == 401
        assert c.get("/v1/items/jikan/anime/not-an-id", headers=AUTH).status_code == 422


def test_jikan_details_keep_staff_cast_and_source_links():
    def handler(request):
        path = request.url.path
        if path.endswith("/full"):
            return httpx.Response(200, json={"data": ANIME})
        if path.endswith("/staff"):
            return httpx.Response(
                200, json={"data": [{"person": {"name": "Writer"}, "positions": ["Script"]}]}
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "character": {"name": "David"},
                        "voice_actors": [{"person": {"name": "Actor"}, "language": "Japanese"}],
                    }
                ]
            },
        )

    with client(handler) as c:
        data = c.get("/v1/items/jikan/anime/42310", headers=AUTH).json()
        assert any(row["name"] == "Writer" and row["role"] == "Script" for row in data["credits"])
        assert any(row["character"] == "David" for row in data["credits"])
        assert data["facts"]["Episodes"] == "10"
        assert data["release_date"] == "2022-09-13"
        assert data["media_links"][0]["url"].startswith("https://www.netflix.com/")


def test_optional_jikan_credits_outage_keeps_core_details():
    def handler(request):
        return (
            httpx.Response(200, json={"data": ANIME})
            if request.url.path.endswith("/full")
            else httpx.Response(500)
        )

    with client(handler) as c:
        response = c.get("/v1/items/jikan/anime/42310", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["title"] == "Cyberpunk: Edgerunners"
