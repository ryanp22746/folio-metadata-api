from ..models import Media
from .common import source

ENTITIES = {"album": "release-group", "track": "recording"}


class MusicBrainz:
    kinds = ("album", "track")

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        entity = ENTITIES[kind]
        doc = await self.http.request(
            "musicbrainz",
            f"/{entity}/",
            params={"query": query, "dismax": "true", "fmt": "json", "limit": 20, "offset": (page - 1) * 20},
        )
        return [normalize(x, kind, doc.fetched_at) for x in doc.data[entity + "s"]], page * 20 < doc.data[
            "count"
        ]

    async def detail(self, kind, identifier):
        entity = ENTITIES[kind]
        doc = await self.http.request(
            "musicbrainz", f"/{entity}/{identifier}", params={"fmt": "json", "inc": "artist-credits+genres"}
        )
        return normalize(doc.data, kind, doc.fetched_at) if doc else None


def normalize(data, kind, fetched_at):
    identifier = data["id"]
    entity = ENTITIES[kind]
    origin = source("musicbrainz", identifier, f"https://musicbrainz.org/{entity}/{identifier}", fetched_at)
    return Media(
        id=f"musicbrainz:{kind}:{identifier}",
        kind=kind,
        title=data["title"],
        release_date=data.get("first-release-date") or None,
        creators=[
            x.get("name") or x["artist"]["name"]
            for x in data.get("artist-credit") or []
            if isinstance(x, dict)
        ],
        genres=[x["name"] for x in data.get("genres") or []],
        format=data.get("primary-type"),
        external_ids={"musicbrainz": identifier},
        source=origin,
    )
