from types import SimpleNamespace

from folio_metadata.identity import duplicate_groups


def test_only_shared_ids_of_same_kind_are_duplicate_evidence():
    records = [
        SimpleNamespace(id="a", kind="movie", external_ids={"imdb": "tt1234567"}),
        SimpleNamespace(id="b", kind="movie", external_ids={"imdb": "tt1234567"}),
        SimpleNamespace(id="c", kind="tv", external_ids={"imdb": "tt1234567"}),
        SimpleNamespace(id="d", kind="movie", external_ids={"tmdb": "123"}),
    ]
    assert duplicate_groups(records) == [
        {"kind": "movie", "namespace": "imdb", "external_id": "tt1234567", "record_ids": ["a", "b"]}
    ]
