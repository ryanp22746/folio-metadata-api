from ..models import Media
from .common import safe_url, source


class Apple:
    """Key-free US album catalog discovery; source order is relevance, not a listener count."""

    kinds = ("album", "track")

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        if page > 1:
            return [], False
        doc = await self.http.request(
            "apple",
            "/search",
            params={
                "term": query,
                "entity": "song" if kind == "track" else "album",
                "limit": 20,
                "country": "US",
            },
        )
        return [
            normalize(x, doc.fetched_at, index) for index, x in enumerate(doc.data.get("results", []))
        ], False

    async def detail(self, kind, identifier):
        doc = await self.http.request(
            "apple",
            "/lookup",
            params={"id": identifier, "entity": "song" if kind == "track" else "album", "country": "US"},
        )
        rows = doc.data.get("results", []) if doc else []
        return next(
            (
                normalize(x, doc.fetched_at)
                for x in rows
                if (
                    kind == "album"
                    and str(x.get("collectionId")) == identifier
                    and x.get("wrapperType") == "collection"
                )
                or (kind == "track" and str(x.get("trackId")) == identifier and x.get("kind") == "song")
            ),
            None,
        )


def normalize(data, fetched_at, index=None):
    track = data.get("kind") == "song"
    kind = "track" if track else "album"
    identifier = str(data["trackId"] if track else data["collectionId"])
    return Media(
        id=f"apple:{kind}:{identifier}",
        kind=kind,
        title=data["trackName"] if track else data["collectionName"],
        format="Track" if track else "Album",
        creators=[data["artistName"]],
        credits=[
            {
                "name": data["artistName"],
                "role": "Artist",
                "url": f"https://music.apple.com/us/artist/{data['artistId']}",
            }
        ]
        if str(data.get("artistId", "")).isdigit()
        else [],
        release_date=(data.get("releaseDate") or "")[:10] or None,
        image_url=safe_url((data.get("artworkUrl100") or "").replace("100x100bb", "600x600bb")),
        genres=[data["primaryGenreName"]] if data.get("primaryGenreName") else [],
        facts={
            **(
                {
                    "Album": data.get("collectionName", ""),
                    "Track number": str(data.get("trackNumber") or ""),
                    "Disc": str(data.get("discNumber") or 1),
                }
                if track
                else {}
            ),
            **(
                {
                    "Duration": f"{int(data['trackTimeMillis']) // 60000}:{int(data['trackTimeMillis']) // 1000 % 60:02}"
                }
                if track and data.get("trackTimeMillis") is not None
                else {}
            ),
            **(
                {"Explicit content": "Yes" if data["trackExplicitness"] == "explicit" else "No"}
                if track and data.get("trackExplicitness")
                else {}
            ),
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
            safe_url(data.get("trackViewUrl") if track else data.get("collectionViewUrl"))
            or f"https://music.apple.com/us/{'song' if track else 'album'}/{identifier}",
            fetched_at,
        ),
    )
