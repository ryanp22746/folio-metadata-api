from ..models import Media
from ..transport import ProviderError
from .common import fuzzy_date, rating, safe_url, source

FIELDS = """
id idMal type format title { romaji english native }
description(asHtml: true) startDate { year month day }
coverImage { large } genres averageScore
"""
SEARCH = """query($query: String!, $type: MediaType!, $page: Int!) {
  Page(page: $page, perPage: 20) {
    pageInfo { hasNextPage }
    media(search: $query, type: $type, sort: SEARCH_MATCH) { FIELDS }
  }
}""".replace("FIELDS", FIELDS)
DETAIL = "query($id: Int!, $type: MediaType!) { Media(id: $id, type: $type) { FIELDS } }".replace(
    "FIELDS", FIELDS
)


class AniList:
    kinds = ("anime", "manga")

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        doc = await self.http.request(
            "anilist",
            "/",
            payload={"query": SEARCH, "variables": {"query": query, "type": kind.upper(), "page": page}},
        )
        if doc.data.get("errors"):
            raise ProviderError()
        data = doc.data["data"]["Page"]
        return [normalize(x, doc.fetched_at) for x in data["media"]], data["pageInfo"]["hasNextPage"]

    async def detail(self, kind, identifier):
        doc = await self.http.request(
            "anilist",
            "/",
            payload={"query": DETAIL, "variables": {"id": int(identifier), "type": kind.upper()}},
        )
        if not doc:
            return None
        errors = doc.data.get("errors")
        if errors:
            if all(e.get("status") == 404 for e in errors):
                return None
            raise ProviderError()
        data = doc.data["data"]["Media"]
        return normalize(data, doc.fetched_at) if data else None


def normalize(data, fetched_at):
    identifier, kind = str(data["id"]), data["type"].lower()
    titles = data["title"]
    origin = source("anilist", identifier, f"https://anilist.co/{kind}/{identifier}", fetched_at)
    ids = {"anilist": identifier}
    if data.get("idMal"):
        ids["myanimelist"] = str(data["idMal"])
    return Media(
        id=f"anilist:{kind}:{identifier}",
        kind=kind,
        title=titles.get("english") or titles.get("romaji") or titles["native"],
        original_title=titles.get("native"),
        description=data.get("description"),
        description_format="html",
        release_date=fuzzy_date(data.get("startDate") or {}),
        image_url=safe_url((data.get("coverImage") or {}).get("large")),
        genres=data.get("genres") or [],
        format=data.get("format"),
        external_ids=ids,
        ratings=rating("AniList average", data.get("averageScore"), 100, origin),
        source=origin,
    )
