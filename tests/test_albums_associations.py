import httpx
from fastapi.testclient import TestClient

from folio_metadata.app import create_app
from folio_metadata.config import Settings
from folio_metadata.transport import INTERVALS

KEY = "album-tests-key-at-least-32-characters"
AUTH = {"Authorization": "Bearer " + KEY}
ALBUM, ARTIST, TRACK = "a" * 22, "b" * 22, "c" * 22
GROUP = "11111111-1111-1111-1111-111111111111"
RELEASE = "22222222-2222-2222-2222-222222222222"
RECORDING = "33333333-3333-3333-3333-333333333333"


def client(handler, **settings):
    return TestClient(
        create_app(settings=Settings(api_key=KEY, **settings), transport=httpx.MockTransport(handler))
    )


def test_spotify_album_tracks_preserve_position_identity_and_pagination(monkeypatch):
    monkeypatch.setitem(INTERVALS, "spotify", 0)

    def handler(request):
        if request.url.host == "accounts.spotify.com":
            return httpx.Response(200, json={"access_token": "private-token", "expires_in": 3600})
        if request.url.path.endswith("/tracks"):
            assert request.url.params["offset"] == "50"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": TRACK,
                            "name": "Song",
                            "artists": [{"id": ARTIST, "name": "Artist"}],
                            "disc_number": 2,
                            "track_number": 4,
                            "duration_ms": 183000,
                        }
                    ],
                    "next": "https://api.spotify.com/v1/more",
                },
            )
        return httpx.Response(
            200,
            json={
                "id": ALBUM,
                "name": "Album",
                "artists": [{"id": ARTIST, "name": "Artist"}],
                "release_date": "2020",
                "images": [{"url": "https://i.scdn.co/image/cover"}],
            },
        )

    with client(handler, spotify_client_id="private-id", spotify_client_secret="private-secret") as c:
        assert c.get(f"/v1/albums/spotify/{ALBUM}/tracks").status_code == 401
        assert c.get("/v1/albums/spotify/invalid/tracks", headers=AUTH).status_code == 422
        response = c.get(f"/v1/albums/spotify/{ALBUM}/tracks?page=2", headers=AUTH)
        assert response.status_code == 200, response.text
        data = response.json()
        row = data["results"][0]
        assert row["id"] == f"spotify:track:{TRACK}" and data["more"]
        assert row["facts"]["Disc"] == "2" and row["facts"]["Duration"] == "3:03"
        assert row["facts"]["Album"] == "Album" and row["image_url"]
        assert "private-token" not in response.text


def test_apple_tracks_exclude_unrelated_collection_and_open_as_individual_song(monkeypatch):
    monkeypatch.setitem(INTERVALS, "apple", 0)

    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {"wrapperType": "collection", "collectionId": 12, "collectionName": "Album"},
                    {
                        "kind": "song",
                        "trackId": 34,
                        "trackName": "Song",
                        "collectionId": 12,
                        "collectionName": "Album",
                        "artistName": "Artist",
                        "artistId": 56,
                        "trackNumber": 2,
                        "discNumber": 1,
                        "trackTimeMillis": 210000,
                    },
                    {"kind": "song", "trackId": 99, "trackName": "Unrelated", "collectionId": 13},
                ]
            },
        )

    with client(handler) as c:
        response = c.get("/v1/albums/apple/12/tracks", headers=AUTH)
        assert response.status_code == 200, response.text
        data = response.json()
        assert [r["id"] for r in data["results"]] == ["apple:track:34"]
        assert data["results"][0]["facts"]["Duration"] == "3:30"
        detail = c.get("/v1/items/apple/track/34?enrich=false", headers=AUTH)
        assert detail.status_code == 200 and detail.json()["kind"] == "track"


def test_brainz_listing_uses_official_edition_and_recording_ids(monkeypatch):
    monkeypatch.setitem(INTERVALS, "musicbrainz", 0)

    def handler(request):
        if "/release-group/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "title": "Album",
                    "releases": [
                        {"id": "bootleg", "status": "Bootleg"},
                        {"id": RELEASE, "status": "Official", "date": "2020"},
                    ],
                },
            )
        assert request.url.path.endswith(RELEASE)
        return httpx.Response(
            200,
            json={
                "id": RELEASE,
                "title": "Edition",
                "date": "2020",
                "country": "US",
                "media": [
                    {
                        "position": 2,
                        "tracks": [
                            {
                                "position": 1,
                                "title": "Song",
                                "length": 180000,
                                "recording": {"id": RECORDING, "title": "Song", "isrcs": ["TEST12345678"]},
                            }
                        ],
                    }
                ],
            },
        )

    with client(handler) as c:
        response = c.get(f"/v1/albums/musicbrainz/{GROUP}/tracks", headers=AUTH)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["edition"] == "Edition · 2020 · US"
        assert data["results"][0]["id"] == f"musicbrainz:track:{RECORDING}"
        assert data["results"][0]["external_ids"]["isrc"] == "TEST12345678"
        assert data["results"][0]["facts"]["Disc"] == "2"


def test_character_results_require_name_and_verified_appearances(monkeypatch):
    monkeypatch.setitem(INTERVALS, "jikan", 0)

    def handler(request):
        if request.url.path.endswith("/characters"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"mal_id": 1, "name": "Matoi, Ryuuko", "favorites": 100},
                        {"mal_id": 2, "name": "Unrelated", "favorites": 1000000},
                    ]
                },
            )
        if "/characters/1/anime" in request.url.path:
            return httpx.Response(200, json={"data": [{"role": "Main", "anime": {"mal_id": 10}}]})
        assert request.url.path.endswith("/anime/10")
        return httpx.Response(
            200,
            json={"data": {"mal_id": 10, "title": "Kill la Kill", "images": {}, "genres": [], "rating": "R"}},
        )

    with client(handler) as c:
        response = c.get("/v1/characters/find?q=Ryuuko%20Matoi", headers=AUTH)
        assert response.status_code == 200, response.text
        matches = response.json()["matches"]
        assert len(matches) == 1 and matches[0]["name"] == "Matoi, Ryuuko"
        assert matches[0]["results"][0]["title"] == "Kill la Kill"


def test_creator_profiles_use_supplied_biography_and_portrait(monkeypatch):
    monkeypatch.setitem(INTERVALS, "tmdb", 0)

    def handler(request):
        if request.url.path.endswith("/combined_credits"):
            return httpx.Response(200, json={"cast": [], "crew": []})
        return httpx.Response(
            200,
            json={
                "id": 12,
                "name": "Director",
                "biography": "A supplied biography.",
                "birthday": "1980-01-01",
                "profile_path": "/portrait.jpg",
                "homepage": "https://example.org/director",
            },
        )

    with client(handler, tmdb_token="test-token") as c:
        response = c.get("/v1/creators/tmdb/12/works", headers=AUTH)
        assert response.status_code == 200, response.text
        creator = response.json()["creator"]
        assert creator["description"] == "A supplied biography."
        assert creator["image_url"].endswith("/portrait.jpg")
        assert creator["facts"]["Born"] == "1980-01-01"
        assert "https://example.org/director" in creator["entity_links"]
        assert "https://www.themoviedb.org/person/12" in creator["entity_links"]
