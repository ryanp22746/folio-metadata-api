import json

import httpx
from fastapi.testclient import TestClient

from folio_metadata.app import create_app
from folio_metadata.config import Settings

KEY = "creator-tests-key-at-least-32-characters"
AUTH = {"Authorization": "Bearer " + KEY}


def test_mal_studio_uses_exact_catalog_id_not_origin_related_titles():
    def handler(request):
        if request.url.path.endswith("/producers/803/full"):
            return httpx.Response(
                200,
                json={
                    "data": {"titles": [{"type": "Default", "title": "Trigger"}], "about": "Animation studio"}
                },
            )
        assert request.url.path.endswith("/anime")
        assert request.url.params["producers"] == "803"
        assert request.url.params["page"] == "2"
        row = {"mal_id": 18679, "title": "Kill la Kill", "studios": [{"mal_id": 803, "name": "Trigger"}]}
        return httpx.Response(
            200,
            json={
                "data": [row, row, {"mal_id": 999, "title": "Unrelated", "studios": [{"mal_id": 1}]}],
                "pagination": {"has_next_page": True},
            },
        )

    with client(handler) as c:
        response = c.get("/v1/creators/mal_studio/803/works?page=2", headers=AUTH)
        assert response.status_code == 200
        data = response.json()
        assert data["creator"]["name"] == "Trigger"
        assert data["more"] is True
        assert [m["title"] for m in data["results"]] == ["Kill la Kill"]


def client(handler, **settings):
    return TestClient(
        create_app(settings=Settings(api_key=KEY, **settings), transport=httpx.MockTransport(handler))
    )


def test_mal_studio_missing_profile_does_not_hide_catalog():
    def handler(request):
        if "/producers/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={"data": [{"mal_id": 1, "title": "Work", "studios": [{"mal_id": 803, "name": "Trigger"}]}]},
        )

    with client(handler) as c:
        response = c.get("/v1/creators/mal_studio/803/works", headers=AUTH)
        assert response.status_code == 200
        assert response.json()["creator"]["name"] == "Trigger"
        assert len(response.json()["results"]) == 1


def test_explicit_refresh_bypasses_upstream_cache_without_affecting_later_requests():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/combined_credits"):
            return httpx.Response(200, json={"cast": [], "crew": []})
        return httpx.Response(200, json={"id": 12, "name": "Person"})

    path = "/v1/creators/tmdb/12/works"
    with client(handler, tmdb_token="test-token") as c:
        assert c.get(path, headers=AUTH).status_code == 200
        assert len(calls) == 2
        assert c.get(path, headers=AUTH).status_code == 200
        assert len(calls) == 2
        assert c.get(path + "?refresh=true", headers=AUTH).status_code == 200
        assert len(calls) == 4
        assert c.get(path, headers=AUTH).status_code == 200
        assert len(calls) == 4


def test_vn_works_use_exact_staff_id_and_pagination():
    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith("/staff"):
            assert body["filters"] == ["and", ["id", "=", "s216"], ["ismain", "=", 1]]
            return httpx.Response(200, json={"results": [{"id": "s216", "name": "Maruto Fumiaki"}]})
        assert body["filters"] == ["staff", "=", ["id", "=", "s216"]]
        assert body["page"] == 2
        return httpx.Response(200, json={"results": [{"id": "v7771", "title": "WHITE ALBUM2"}], "more": True})

    with client(handler) as c:
        assert c.get("/v1/creators/vndb/s216/works").status_code == 401
        assert c.get("/v1/creators/vndb/s0/works", headers=AUTH).status_code == 422
        response = c.get("/v1/creators/vndb/s216/works?page=2", headers=AUTH)
        assert response.status_code == 200
        data = response.json()
        assert data["creator"]["id"] == "s216" and data["more"] is True
        assert data["results"][0]["id"] == "vndb:visual_novel:v7771"


def test_tmdb_combines_movie_tv_credits_without_duplicate_roles():
    def handler(request):
        if request.url.path.endswith("/combined_credits"):
            row = {"id": 1, "media_type": "movie", "title": "Film", "popularity": 10}
            return httpx.Response(
                200, json={"cast": [row], "crew": [row, {"id": 2, "media_type": "tv", "name": "Series"}]}
            )
        return httpx.Response(200, json={"id": 12, "name": "Person"})

    with client(handler, tmdb_token="test-token") as c:
        data = c.get("/v1/creators/tmdb/12/works", headers=AUTH).json()
        assert [m["kind"] for m in data["results"]] == ["movie", "tv"]


def test_author_series_are_source_linked_and_no_detail_fanout():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/series"):
            assert request.method == "POST"
            return httpx.Response(
                200,
                json={
                    "series_list": [
                        {
                            "series_id": 1,
                            "title": "Comic",
                            "year": 2013,
                            "url": "https://www.mangaupdates.com/series/one",
                            "genres": ["Drama"],
                        }
                    ]
                },
            )
        return httpx.Response(
            200, json={"id": 123, "name": "Author", "url": "https://www.mangaupdates.com/author/test"}
        )

    with client(handler) as c:
        data = c.get("/v1/creators/mangaupdates/123/works", headers=AUTH).json()
        assert data["results"][0]["external_ids"]["mangaupdates"] == "1"
        assert len(calls) == 2


def test_author_linked_novels_are_not_saved_as_manga():
    def handler(request):
        if request.url.path.endswith("/series"):
            return httpx.Response(
                200,
                json={
                    "series_list": [
                        {
                            "series_id": 3,
                            "title": "Story (Novel)",
                            "url": "https://www.mangaupdates.com/series/novel",
                        }
                    ]
                },
            )
        if "/authors/" in request.url.path:
            return httpx.Response(200, json={"id": 123, "name": "Writer"})
        return httpx.Response(200, json={"series_id": 3, "title": "Story (Novel)", "type": "Novel"})

    with client(handler) as c:
        works = c.get("/v1/creators/mangaupdates/123/works", headers=AUTH).json()
        assert works["results"][0]["kind"] == "book"
        assert c.get("/v1/items/mangaupdates/book/3", headers=AUTH).json()["kind"] == "book"
        assert c.get("/v1/items/mangaupdates/manga/3", headers=AUTH).status_code == 404


def test_book_author_works_preserve_work_identity_and_do_not_guess_publication_dates():
    def handler(request):
        if request.url.path.endswith("/works.json"):
            return httpx.Response(
                200,
                json={
                    "size": 21,
                    "entries": [
                        {
                            "key": "/works/OL1W",
                            "title": "Book",
                            "covers": [12],
                            "subjects": ["Science fiction"],
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"key": "/authors/OL1A", "name": "Author"})

    with client(handler) as c:
        data = c.get("/v1/creators/openlibrary/OL1A/works", headers=AUTH).json()
        assert data["creator"]["id"] == "OL1A"
        assert data["results"][0]["id"] == "openlibrary:book:OL1W"
        assert data["results"][0]["release_date"] is None
        assert data["more"] is True


def test_creator_name_matches_are_separate_and_failures_do_not_hide_other_sources():
    def handler(request):
        if request.url.host == "api.vndb.org":
            return httpx.Response(200, json={"results": [{"id": "s216", "name": "Maruto Fumiaki"}]})
        if request.url.host == "api.mangaupdates.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "record": {
                                "id": 123,
                                "name": "MARUTO Fumiaki",
                                "url": "https://www.mangaupdates.com/author/test",
                            }
                        }
                    ]
                },
            )
        raise httpx.ReadTimeout("test failure")

    with client(handler) as c:
        data = c.get("/v1/creators/find?q=Maruto%20Fumiaki", headers=AUTH).json()
        assert len(data["matches"]) == 2
        assert {m["provider"] for m in data["matches"]} == {"vndb", "mangaupdates"}
        assert next(s for s in data["providers"] if s["provider"] == "tmdb")["status"] == "not_configured"
        assert next(s for s in data["providers"] if s["provider"] == "openlibrary")["status"] == "unavailable"


def test_company_works_preserve_source_qualified_ids():
    def handler(request):
        if request.url.path.endswith("/companies"):
            return httpx.Response(200, json=[{"id": 16, "name": "Valve"}])
        if request.url.path.endswith("/games"):
            assert "involved_companies.company = 16" in request.content.decode()
            return httpx.Response(200, json=[{"id": 1, "name": "Portal 2", "slug": "portal-2"}])
        if "/company/" in request.url.path:
            return httpx.Response(200, json={"id": 3, "name": "Trigger"})
        assert request.url.params["with_companies"] == "3"
        return httpx.Response(
            200, json={"results": [{"id": 9, "name": "Anime", "title": "Anime"}], "total_pages": 1}
        )

    with client(handler, igdb_client_id="id", igdb_client_secret="secret", tmdb_token="token") as c:
        c.app.state.gateway.http.access_token = "test"
        c.app.state.gateway.http.token_expiry = float("inf")
        result = c.get("/v1/creators/igdb/16/works", headers=AUTH)
        assert result.status_code == 200
        assert result.json()["results"][0]["title"] == "Portal 2"
        result = c.get("/v1/creators/tmdb_company/3/works", headers=AUTH)
        assert result.status_code == 200
        assert {r["kind"] for r in result.json()["results"]} == {"movie", "tv"}


def test_company_discovery_does_not_mutate_cached_people():
    def handler(request):
        if request.url.path.endswith("/search/person"):
            return httpx.Response(200, json={"results": [{"id": 1, "name": "Other person"}]})
        if request.url.path.endswith("/search/company"):
            return httpx.Response(200, json={"results": [{"id": 50908, "name": "TRIGGER"}]})
        return httpx.Response(200, json={"results": [], "artists": [], "docs": []})

    with client(handler, tmdb_token="test-token") as c:
        for _ in range(3):
            data = c.get("/v1/creators/find?q=Trigger", headers=AUTH).json()
            companies = [r for r in data["matches"] if r["provider"] == "tmdb_company"]
            assert len(companies) == 1
            assert companies[0]["id"] == "50908"


def test_apple_artist_works_use_exact_identity_and_keep_artist_links():
    def handler(request):
        assert request.url.params["id"] == "271256"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"wrapperType": "artist", "artistId": 271256, "artistName": "Drake"},
                    {
                        "wrapperType": "collection",
                        "collectionId": 10,
                        "collectionName": "Album",
                        "artistId": 271256,
                        "artistName": "Drake",
                    },
                    {
                        "wrapperType": "collection",
                        "collectionId": 11,
                        "collectionName": "Other artist",
                        "artistId": 1,
                        "artistName": "Drake",
                    },
                ]
            },
        )

    with client(handler) as c:
        data = c.get("/v1/creators/apple/271256/works", headers=AUTH).json()
        assert data["creator"]["provider"] == "apple"
        assert len(data["results"]) == 1
        assert data["results"][0]["credits"][0]["url"] == "https://music.apple.com/us/artist/271256"
