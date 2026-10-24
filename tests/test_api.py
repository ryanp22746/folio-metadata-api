import httpx
import pytest
from fastapi.testclient import TestClient

from folio_metadata.app import create_app

KEY = "test-secret-that-is-at-least-32-characters"
HEADERS = {"Authorization": f"Bearer {KEY}"}
VN = {"id": "v17", "title": "Ever17", "released": "2002", "image": None}


def client(handler, token=""):
    return TestClient(create_app(KEY, token, httpx.MockTransport(handler)))


def test_auth_health_and_validation():
    with client(lambda r: httpx.Response(200, json={"results": []})) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/v1/search?q=test").status_code == 401
        assert c.get("/v1/search?q=  ", headers=HEADERS).status_code == 422
        assert c.get("/v1/search?q=test&page=0", headers=HEADERS).status_code == 422
        assert c.get("/v1/items/vndb/movie/17", headers=HEADERS).status_code == 422


def test_fail_closed():
    with pytest.raises(RuntimeError), TestClient(create_app("short")):
        pass


def test_normalization_partial_and_cache():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"results": [VN], "more": True})

    with client(handler) as c:
        response = c.get("/v1/search?q=Ever17", headers=HEADERS)
        data = response.json()
        assert response.status_code == 200
        assert data["partial"] is True
        assert data["results"][0]["id"] == "vndb:visual_novel:v17"
        assert data["results"][0]["release_date"] == "2002"
        assert data["results"][0]["image_url"] is None
        assert data["more"] is True
        assert c.get("/v1/search?q=Ever17", headers=HEADERS).status_code == 200
        assert len(calls) == 1
        assert response.headers["X-Request-ID"]


@pytest.mark.parametrize("status", [401, 429, 500])
def test_upstream_failures(status):
    with client(lambda r: httpx.Response(status, text="private upstream details")) as c:
        response = c.get("/v1/search?q=test&kind=visual_novel", headers=HEADERS)
        assert response.status_code == 503
        assert "private upstream details" not in response.text


def test_malformed_and_timeout():
    for handler in (
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"results": [{}]}),
    ):
        with client(handler) as c:
            assert c.get("/v1/search?q=test", headers=HEADERS).status_code == 503

    def timeout(request):
        raise httpx.ReadTimeout("timeout", request=request)

    with client(timeout) as c:
        assert c.get("/v1/search?q=test", headers=HEADERS).status_code == 503


def test_tmdb_detail_external_id():
    def handler(request):
        assert request.headers["Authorization"] == "Bearer provider-secret"
        return httpx.Response(
            200,
            json={
                "id": 11,
                "title": "Star Wars",
                "external_ids": {"imdb_id": "tt0076759"},
                "genres": [{"name": "Adventure"}],
            },
        )

    with client(handler, "provider-secret") as c:
        data = c.get("/v1/items/tmdb/movie/11", headers=HEADERS).json()
        assert data["external_ids"]["imdb"] == "tt0076759"
        assert data["genres"] == ["Adventure"]


def test_not_found():
    with client(lambda r: httpx.Response(404), "token") as c:
        assert c.get("/v1/items/tmdb/movie/11", headers=HEADERS).status_code == 404


def test_rate_limit_and_provider_cooldown():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    with client(handler) as c:
        for i in range(60):
            assert c.get(f"/v1/search?q=test{i}&kind=visual_novel", headers=HEADERS).status_code == 503
        assert len(calls) == 1
        response = c.get("/v1/search?q=test", headers=HEADERS)
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"
