import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..models import Media
from ..transport import ProviderError
from .common import rating, safe_url, source

FIELDS = "id,name,slug,summary,first_release_date,cover.url,genres.name,platforms.name,rating,rating_count,aggregated_rating,websites.url"


class IGDB:
    kinds = ("game",)

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        body = f"search {json.dumps(query, ensure_ascii=False)}; fields {FIELDS}; limit 20; offset {(page - 1) * 20};"
        doc = await self.http.request("igdb", "/games", content=body)
        return [normalize(x, doc.fetched_at) for x in doc.data], len(doc.data) == 20

    async def detail(self, kind, identifier):
        doc = await self.http.request(
            "igdb",
            "/games",
            content=f"fields {FIELDS},artworks.url,screenshots.url; where id = {int(identifier)}; limit 1;",
        )
        if not doc or not doc.data:
            return None
        media = normalize(doc.data[0], doc.fetched_at)
        # Optional artwork must never make the primary game unavailable.
        try:
            logos = await self.http.request(
                "igdb",
                "/logos",
                content=f"fields url,alpha_channel; where game = {int(identifier)} & alpha_channel = true; limit 1;",
            )
            if logos and logos.data:
                media.logo_url = safe_url(
                    re.sub(
                        r"\.(?:jpg|jpeg)$", ".png", logos.data[0].get("url", "").replace("t_thumb", "t_720p")
                    )
                )
        except ProviderError:
            pass
        return media


def normalize(data, fetched_at):
    identifier = str(data["id"])
    origin = source("igdb", identifier, f"https://www.igdb.com/games/{data['slug']}", fetched_at)
    ids = {"igdb": identifier}
    steam_ids = set()
    for website in data.get("websites") or []:
        url = urlsplit(website.get("url", ""))
        match = re.fullmatch(r"/app/([1-9][0-9]*)(?:/.*)?", url.path)
        if url.scheme == "https" and url.hostname == "store.steampowered.com" and match:
            steam_ids.add(match[1])
    if len(steam_ids) == 1:
        ids["steam"] = steam_ids.pop()
    released = data.get("first_release_date")
    return Media(
        id=f"igdb:game:{identifier}",
        kind="game",
        rating_count=data.get("rating_count"),
        title=data["name"],
        description=data.get("summary"),
        release_date=datetime.fromtimestamp(released, timezone.utc).date().isoformat() if released else None,
        image_url=safe_url(((data.get("cover") or {}).get("url") or "").replace("t_thumb", "t_cover_big")),
        backdrop_url=next(
            (
                safe_url(x.get("url", "").replace("t_thumb", "t_720p"))
                for x in (data.get("artworks") or data.get("screenshots") or [])
                if safe_url(x.get("url", ""))
            ),
            None,
        ),
        genres=[x["name"] for x in data.get("genres") or []],
        platforms=[x["name"] for x in data.get("platforms") or []],
        external_ids=ids,
        source=origin,
        ratings=rating("IGDB users", data.get("rating"), 100, origin)
        + rating("IGDB critics", data.get("aggregated_rating"), 100, origin),
    )
