import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from folio_metadata.adapters.spotify import normalize
from folio_metadata.app import create_app
from folio_metadata.config import Settings
from folio_metadata.transport import INTERVALS, ProviderError, Transport

ALBUM = "a" * 22
ARTIST = "b" * 22
TRACK = "c" * 22
KEY = "spotify-test-service-key-at-least-32"
STAMP = "2026-10-25T00:00:00Z"


def album():
    return {
        "id": ALBUM,
        "name": "Release",
        "artists": [{"id": ARTIST, "name": "Artist"}],
        "album_type": "album",
        "release_date": "2024",
        "release_date_precision": "year",
        "total_tracks": 10,
        "images": [
            {"width": 64, "url": "https://i.scdn.co/image/small"},
            {"width": 640, "url": "https://i.scdn.co/image/large"},
        ],
    }


def test_normalization_preserves_precision_identity_and_missing_fields():
    m = normalize(album(), "album", STAMP)
    assert m.release_date == "2024"
    assert m.image_url.endswith("large")
    assert m.portrait_urls == [m.image_url]
    assert m.credits[0].url == f"https://open.spotify.com/artist/{ARTIST}"
    assert m.media_links[0].url == f"https://open.spotify.com/album/{ALBUM}"
    assert not m.ratings and m.popularity is None and m.logo_url is None
    assert m.facts["Release date precision"] == "Year"
    track = normalize(
        {
            "id": TRACK,
            "name": "Track",
            "album": album(),
            "artists": album()["artists"],
            "duration_ms": 183500,
            "external_ids": {"isrc": "usabc1234567"},
            "explicit": True,
        },
        "track",
        STAMP,
    )
    assert track.facts["Duration"] == "3:03"
    assert track.external_ids["isrc"] == "USABC1234567"
    assert track.image_url == m.image_url


def test_spotify_routes_artists_and_credential_redaction(monkeypatch):
    monkeypatch.setitem(INTERVALS, "spotify", 0)
    tokens = []

    def handler(request):
        if request.url.host == "accounts.spotify.com":
            tokens.append(request)
            assert request.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "private-token", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer private-token"
        if request.url.path == f"/v1/artists/{ARTIST}":
            return httpx.Response(200, json={"id": ARTIST, "name": "Artist"})
        if request.url.path == f"/v1/artists/{ARTIST}/albums":
            assert int(request.url.params["limit"]) <= 10
            return httpx.Response(200, json={"items": [album()], "next": None})
        if request.url.path == f"/v1/albums/{ALBUM}":
            return httpx.Response(200, json=album())
        assert request.url.path == "/v1/search"
        kind = request.url.params["type"]
        if kind == "artist":
            return httpx.Response(200, json={"artists": {"items": [{"id": ARTIST, "name": "Artist"}]}})
        if kind == "track":
            return httpx.Response(
                200,
                json={
                    "tracks": {
                        "items": [
                            {
                                "id": TRACK,
                                "name": "Track",
                                "artists": [{"id": "d" * 22, "name": "Artist"}],
                                "album": album(),
                            }
                        ],
                        "next": None,
                    }
                },
            )
        assert int(request.url.params["limit"]) <= 10
        return httpx.Response(200, json={"albums": {"items": [album()], "next": None}})

    settings = Settings(api_key=KEY, spotify_client_id="private-id", spotify_client_secret="private-secret")
    with TestClient(create_app(settings=settings, transport=httpx.MockTransport(handler))) as c:
        auth = {"Authorization": "Bearer " + KEY}
        for path in [
            f"/v1/items/spotify/album/{ALBUM}",
            "/v1/search?q=Artist&provider=spotify&kind=album",
            f"/v1/creators/spotify/{ARTIST}/works",
        ]:
            response = c.get(path, headers=auth)
            assert response.status_code == 200, response.text
            if path.startswith("/v1/search"):
                assert response.json()["results"][0]["search_priority"] == 1.1
            assert all(
                secret not in response.text for secret in ("private-id", "private-secret", "private-token")
            )
        works = c.get(f"/v1/creators/spotify/{ARTIST}/works", headers=auth).json()
        assert len(works["results"]) == 1, "same-name tracks from a different artist ID must be excluded"
        assert c.get("/v1/items/spotify/album/not-an-id", headers=auth).status_code == 422
        assert len(tokens) == 1


def test_token_refresh_once_and_rate_limit_backoff(monkeypatch):
    monkeypatch.setitem(INTERVALS, "spotify", 0)

    async def run():
        tokens, calls = [], []

        def handler(request):
            if request.url.host == "accounts.spotify.com":
                tokens.append(1)
                return httpx.Response(200, json={"access_token": f"token-{len(tokens)}", "expires_in": 3600})
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(401, json={})
            return httpx.Response(429, headers={"Retry-After": "300"}, json={})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            t = Transport(client, Settings(spotify_client_id="id", spotify_client_secret="secret"))
            with pytest.raises(ProviderError):
                await t.request("spotify", "/search")
            with pytest.raises(ProviderError):
                await t.request("spotify", "/search")
            assert len(tokens) == 2 and len(calls) == 2

    asyncio.run(run())
