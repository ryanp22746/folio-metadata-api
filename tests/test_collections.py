import httpx
from fastapi.testclient import TestClient

from folio_metadata.app import create_app
from folio_metadata.config import Settings
from folio_metadata.transport import INTERVALS

KEY = "collections-test-key-over-32-characters"
AUTH = {"Authorization": "Bearer " + KEY}


def test_anime_relations_remain_distinct_catalog_entries():
    from folio_metadata.adapters.anilist import normalize as anilist
    from folio_metadata.adapters.jikan import normalize as jikan

    stamp = "2026-10-25T12:00:00Z"
    media = anilist(
        {
            "id": 1,
            "type": "ANIME",
            "title": {"english": "First"},
            "relations": {
                "edges": [
                    {
                        "relationType": "SEQUEL",
                        "node": {"id": 2, "type": "ANIME", "title": {"english": "Second"}},
                    }
                ]
            },
        },
        stamp,
    )
    assert media.related_media[0].id == "2" and media.related_media[0].relation == "sequel"
    media = jikan(
        {
            "mal_id": 1,
            "title": "First",
            "relations": [
                {"relation": "Sequel", "entry": [{"mal_id": 2, "name": "Second", "type": "anime"}]}
            ],
        },
        stamp,
    )
    assert media.related_media[0].id == "2" and media.related_media[0].provider == "jikan"


def test_tv_hierarchy_and_independent_identity(monkeypatch):
    monkeypatch.setitem(INTERVALS, "tmdb", 0)
    series = {
        "id": 7,
        "name": "Series",
        "genres": [{"name": "Drama"}],
        "seasons": [
            {"season_number": 2, "name": "Season 2", "episode_count": 1},
            {"season_number": 0, "name": "Specials"},
            {"season_number": 1, "name": "Season 1"},
        ],
    }
    season = {"name": "Season 2", "episodes": [{"episode_number": 1, "name": "Opening", "runtime": 42}]}

    def handler(r):
        if r.url.path.endswith("/episode/1"):
            return httpx.Response(200, json=season["episodes"][0])
        return httpx.Response(200, json=season if "/season/" in r.url.path else series)

    with TestClient(
        create_app(settings=Settings(api_key=KEY, tmdb_token="test"), transport=httpx.MockTransport(handler))
    ) as c:
        assert c.get("/v1/collections/tmdb/tv/7").status_code == 401
        assert c.get("/v1/items/tmdb/movie/7-season-2", headers=AUTH).status_code == 422
        response = c.get("/v1/collections/tmdb/tv/7", headers=AUTH)
        assert response.status_code == 200, response.text
        rows = response.json()["groups"][0]["results"]
        assert [r["source"]["id"] for r in rows] == ["7-season-1", "7-season-2", "7-season-0"]
        assert rows[1]["external_ids"] == {"tmdb": "7-season-2"}
        assert rows[1]["facts"]["Episodes"] == "1"
        data = c.get("/v1/collections/tmdb/tv/7-season-2", headers=AUTH).json()
        assert data["parent"]["id"] == "tmdb:tv:7"
        episode = data["groups"][0]["results"][0]
        assert episode["source"]["id"] == "7-season-2-episode-1"
        detail = c.get("/v1/items/tmdb/tv/7-season-2-episode-1?enrich=true", headers=AUTH)
        assert detail.status_code == 200, detail.text
        assert detail.json()["title"] == "Series · Season 2 · Episode 1: Opening"
        assert (
            c.get("/v1/collections/tmdb/tv/7-season-2-episode-1", headers=AUTH).json()["parent"]["source"][
                "id"
            ]
            == "7-season-2"
        )


def test_movie_collection_membership(monkeypatch):
    monkeypatch.setitem(INTERVALS, "tmdb", 0)

    def handler(r):
        if "/collection/" in r.url.path:
            return httpx.Response(
                200,
                json={
                    "id": 9,
                    "name": "Saga",
                    "parts": [
                        {"id": 2, "title": "Second", "release_date": "2022"},
                        {"id": 1, "title": "First", "release_date": "2020"},
                        {"id": 1, "title": "First", "release_date": "2020"},
                    ],
                },
            )
        return httpx.Response(200, json={"id": 1, "title": "First", "belongs_to_collection": {"id": 9}})

    with TestClient(
        create_app(settings=Settings(api_key=KEY, tmdb_token="test"), transport=httpx.MockTransport(handler))
    ) as c:
        data = c.get("/v1/collections/tmdb/movie/1", headers=AUTH).json()
        assert data["parent"]["source"]["id"] == "collection-9"
        assert [r["title"] for r in data["groups"][0]["results"]] == ["First", "Second"]
        result = c.get("/v1/items/tmdb/movie/collection-9", headers=AUTH)
        assert result.status_code == 200 and result.json()["format"] == "Collection"


def test_game_series_and_expansion(monkeypatch):
    monkeypatch.setitem(INTERVALS, "igdb", 0)

    def handler(r):
        if "oauth2/token" in r.url.path:
            return httpx.Response(200, json={"access_token": "test", "expires_in": 3600})
        body = r.content.decode()
        if r.url.path.endswith("/collections"):
            return httpx.Response(200, json=[{"id": 9, "name": "Series", "slug": "series"}])
        if "where collections" in body:
            assert "offset 50" in body
            return httpx.Response(200, json=[{"id": 1, "name": "Game", "slug": "game"}])
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "collections": [{"id": 9, "name": "Series", "slug": "series"}],
                    "expansions": [{"id": 2, "name": "Expansion", "slug": "expansion"}],
                }
            ],
        )

    with TestClient(
        create_app(
            settings=Settings(api_key=KEY, igdb_client_id="test", igdb_client_secret="test"),
            transport=httpx.MockTransport(handler),
        )
    ) as c:
        result = c.get("/v1/collections/igdb/game/1", headers=AUTH)
        assert result.status_code == 200, result.text
        assert result.json()["groups"][0]["results"][0]["source"]["id"] == "collection-9"
        assert result.json()["groups"][1]["results"][0]["id"] == "igdb:game:2"
        result = c.get("/v1/collections/igdb/game/collection-9?page=2", headers=AUTH)
        assert result.status_code == 200, result.text
        assert result.json()["groups"][0]["results"][0]["title"] == "Game"
