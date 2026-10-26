from folio_metadata.adapters.catalog import VN_DETAIL_FIELDS, VN_FIELDS, VNDB, vn_credits
from folio_metadata.adapters.mangaupdates import normalize as manga
from folio_metadata.adapters.musicbrainz import normalize as music
from folio_metadata.adapters.tmdb_details import detail_fields


def test_vn_credits_preserve_roles_identity_and_edition_scope():
    data = {
        "staff": [
            {
                "id": "s216",
                "name": "Maruto Fumiaki",
                "original": "Original name",
                "role": "scenario",
                "eid": None,
            },
            {
                "id": "s216",
                "name": "Maruto Fumiaki",
                "role": "scenario",
                "eid": 1,
                "note": "Additional script",
            },
            {"id": "s2", "name": "Composer", "role": "music"},
            {"id": "bad/url", "name": "Other", "role": "future_role"},
        ],
        "editions": [{"eid": 1, "name": "Console edition", "lang": "ja"}],
        "developers": [{"id": "p1", "name": "Studio"}],
        "va": [{"staff": {"id": "s3", "name": "Actor"}, "character": {"name": "Hero"}}],
    }
    credits = vn_credits(data)
    assert credits[0]["role"] == "Writer / scenario"
    assert credits[0]["url"] == "https://vndb.org/s216"
    assert "Original name" in credits[0]["note"]
    assert "Additional script" in credits[1]["note"]
    assert "Console edition" in credits[1]["note"]
    assert any(c["role"] == "Composer" for c in credits)
    assert next(c for c in credits if c["name"] == "Other")["url"] is None
    assert next(c for c in credits if c["name"] == "Actor")["character"] == "Hero"
    assert vn_credits({}) == []
    assert "staff.role" not in VN_FIELDS and "staff.role" in VN_DETAIL_FIELDS
    assert VNDB.kinds == ("visual_novel",)


def test_other_media_keep_identifiable_people_and_explicit_roles():
    comic = manga(
        {
            "series_id": 1,
            "title": "Comic",
            "authors": [
                {"name": "Writer", "type": "Author", "url": "https://www.mangaupdates.com/author/one"},
                {"name": "Illustrator", "type": "Artist", "url": "javascript:bad"},
            ],
        },
        "2026-10-25T00:00:00Z",
    )
    assert [c.role for c in comic.credits] == ["Author", "Artist"]
    assert comic.credits[1].url is None
    identifier = "00000000-0000-0000-0000-000000000001"
    album = music(
        {
            "id": identifier,
            "title": "Album",
            "artist-credit": [
                {"name": "Artist", "artist": {"id": identifier, "name": "Artist"}},
            ],
        },
        "album",
        "2026-10-25T00:00:00Z",
    )
    assert album.credits[0].url == f"https://musicbrainz.org/artist/{identifier}"
    tv = detail_fields({"created_by": [{"id": 1, "name": "Series creator"}]})
    assert tv["credits"][0]["role"] == "Series creator"


def test_studio_credits_link_to_company_not_person():
    fields = detail_fields({"production_companies": [{"id": 50908, "name": "TRIGGER"}]})
    assert fields["credits"][0]["role"] == "Studio"
    assert fields["credits"][0]["url"] == "https://www.themoviedb.org/company/50908"


def test_vn_content_tags_are_ranked_and_exclude_spoilers_and_technical_tags():
    from folio_metadata.adapters.catalog import normalize_vn

    media = normalize_vn(
        {
            "id": "v2002",
            "title": "Steins;Gate",
            "tags": [
                {"name": "Science Fiction", "category": "cont", "rating": 3, "spoiler": 0, "lie": False},
                {"name": "Time Travel", "category": "cont", "rating": 2.9, "spoiler": 0},
                {"name": "Adult Protagonist", "category": "cont", "rating": 2.8, "spoiler": 0},
                {"name": "Plot reveal", "category": "cont", "rating": 3, "spoiler": 2},
                {"name": "Engine", "category": "tech", "rating": 3, "spoiler": 0},
                {"name": "Disputed", "category": "cont", "rating": 3, "spoiler": 0, "lie": True},
            ],
        },
        "2026-10-25T00:00:00Z",
    )
    assert media.genres == ["Science Fiction", "Time Travel"]
    assert media.content_tags == ["Adult Protagonist"]
