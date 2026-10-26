from folio_metadata.adapters.catalog import normalize_tmdb, normalize_vn
from folio_metadata.adapters.igdb import normalize as game


def test_provider_artwork_galleries_preserve_defaults_and_safe_vn_images():
    movie = normalize_tmdb(
        {
            "id": 1,
            "title": "Film",
            "poster_path": "/default.jpg",
            "images": {
                "posters": [{"file_path": "/other.jpg"}, {"file_path": "bad"}],
                "backdrops": [{"file_path": "/wide.jpg"}],
            },
        },
        "movie",
        "2026-10-24T00:00:00Z",
    )
    assert movie.image_url.endswith("/default.jpg")
    assert movie.portrait_urls == ["https://image.tmdb.org/t/p/w500/other.jpg"]
    assert movie.backdrop_urls == ["https://image.tmdb.org/t/p/w1280/wide.jpg"]
    vn = normalize_vn(
        {
            "id": "v1",
            "title": "Novel",
            "screenshots": [
                {"url": "https://images.example/safe.jpg", "sexual": 0, "violence": 0},
                {"url": "https://images.example/unrated.jpg"},
                {"url": "https://images.example/adult.jpg", "sexual": 1, "violence": 0},
            ],
        },
        "2026-10-24T00:00:00Z",
    )
    assert vn.backdrop_urls == ["https://images.example/safe.jpg"]
    media = game(
        {
            "id": 1,
            "name": "Game",
            "slug": "game",
            "artworks": [{"url": "//images.example/t_thumb/art.jpg"}],
            "screenshots": [{"url": "https://images.example/t_thumb/shot.jpg"}],
        },
        "2026-10-24T00:00:00Z",
    )
    assert media.backdrop_urls == [
        "https://images.example/t_720p/art.jpg",
        "https://images.example/t_720p/shot.jpg",
    ]


def test_cross_catalog_links_and_animation_evidence_are_preserved():
    media = game(
        {"id": 1, "name": "Novel", "slug": "novel", "websites": [{"url": "https://vndb.org/v2002"}]},
        "2026-10-25T00:00:00Z",
    )
    assert media.external_ids["vndb"] == "v2002"
    unrelated = game(
        {"id": 1, "name": "Novel", "slug": "novel", "websites": [{"url": "https://vndb.org.evil/v2002"}]},
        "2026-10-25T00:00:00Z",
    )
    assert "vndb" not in unrelated.external_ids
    anime = normalize_tmdb({"id": 1, "name": "Series", "genre_ids": [16]}, "tv", "2026-10-25T00:00:00Z")
    assert "Animation" in anime.genres
