from ..models import Media
from .common import safe_url, source


class Apple:
    """Key-free US album catalog discovery; source order is relevance, not a listener count."""

    kinds = ("album",)

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        if page > 1:
            return [], False
        doc = await self.http.request(
            "apple", "/search", params={"term": query, "entity": "album", "limit": 20, "country": "US"}
        )
        return [
            normalize(x, doc.fetched_at, index) for index, x in enumerate(doc.data.get("results", []))
        ], False

    async def detail(self, kind, identifier):
        doc = await self.http.request(
            "apple", "/lookup", params={"id": identifier, "entity": "album", "country": "US"}
        )
        rows = doc.data.get("results", []) if doc else []
        return next(
            (
                normalize(x, doc.fetched_at)
                for x in rows
                if str(x.get("collectionId")) == identifier and x.get("wrapperType") == "collection"
            ),
            None,
        )


def normalize(data, fetched_at, index=None):
    identifier = str(data["collectionId"])
    return Media(
        id=f"apple:album:{identifier}",
        kind="album",
        title=data["collectionName"],
        creators=[data["artistName"]],
        release_date=(data.get("releaseDate") or "")[:10] or None,
        image_url=safe_url((data.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")),
        genres=[data["primaryGenreName"]] if data.get("primaryGenreName") else [],
        facts={
            **({"Tracks": str(data["trackCount"])} if data.get("trackCount") else {}),
            **(
                {
                    "Edition": {
                        "cleaned": "Clean",
                        "explicit": "Explicit",
                        "notExplicit": "Not explicit",
                    }.get(data["collectionExplicitness"], data["collectionExplicitness"])
                }
                if data.get("collectionExplicitness")
                else {}
            ),
        },
        external_ids={"apple": identifier},
        search_priority=1.1 / (1 + index * 0.2) if index is not None else None,
        source=source(
            "apple",
            identifier,
            safe_url(data.get("collectionViewUrl")) or f"https://music.apple.com/us/album/{identifier}",
            fetched_at,
        ),
    )
