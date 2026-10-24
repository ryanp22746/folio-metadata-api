from ..models import Media
from .common import rating, safe_url, source, year

COMIC_TYPES = [
    "Manga",
    "Manhwa",
    "Manhua",
    "Doujinshi",
    "OEL",
    "Filipino",
    "Indonesian",
    "Thai",
    "Vietnamese",
    "Malaysian",
    "Nordic",
    "French",
    "Spanish",
    "German",
    "Russian",
]


class MangaUpdates:
    kinds = ("manga",)

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        doc = await self.http.request(
            "mangaupdates",
            "/series/search",
            payload={
                "search": query,
                "stype": "title",
                "type": COMIC_TYPES,
                "page": page,
                "perpage": 20,
                "orderby": "score",
            },
        )
        return [normalize(x["record"], doc.fetched_at) for x in doc.data["results"]], page * 20 < doc.data[
            "total_hits"
        ]

    async def detail(self, kind, identifier):
        doc = await self.http.request("mangaupdates", f"/series/{identifier}")
        if not doc or doc.data.get("type") not in COMIC_TYPES:
            return None
        return normalize(doc.data, doc.fetched_at)


def normalize(data, fetched_at):
    identifier = str(data["series_id"])
    url = safe_url(data.get("url")) or f"https://www.mangaupdates.com/series.html?id={identifier}"
    origin = source("mangaupdates", identifier, url, fetched_at)
    return Media(
        id=f"mangaupdates:manga:{identifier}",
        kind="manga",
        rating_count=data.get("rating_votes"),
        title=data["title"],
        description=data.get("description"),
        description_format="html",
        format=data.get("type"),
        release_date=year(data.get("year")),
        image_url=safe_url(((data.get("image") or {}).get("url") or {}).get("original")),
        genres=[x["genre"] for x in data.get("genres") or []],
        creators=list(dict.fromkeys(x["name"] for x in data.get("authors") or [] if x.get("name"))),
        ratings=rating("MangaUpdates Bayesian", data.get("bayesian_rating"), 10, origin),
        external_ids={"mangaupdates": identifier},
        source=origin,
    )
