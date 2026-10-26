import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from ..models import Media
from ..transport import ProviderError
from .common import rating, safe_url, source

FIELDS = "id,name,slug,summary,first_release_date,cover.url,genres.name,platforms.name,rating,rating_count,aggregated_rating,websites.url,alternative_names.name"


class IGDB:
    kinds = ("game",)

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        body = f"search {json.dumps(query, ensure_ascii=False)}; fields {FIELDS}; limit 20; offset {(page - 1) * 20};"
        requests = [self.http.request("igdb", "/games", content=body)]
        # IGDB's native ranking can crowd a well-known title out of a broad query.
        # Supplement the first page with popular title matches, retaining all
        # native results (including aliases and fuzzy matches).
        if page == 1:
            requests.append(
                self.http.request(
                    "igdb",
                    "/games",
                    content=f"fields {FIELDS}; where name ~ *{json.dumps(query, ensure_ascii=False)}*; sort total_rating_count desc; limit 20;",
                )
            )
        responses = await asyncio.gather(*requests, return_exceptions=True)
        docs = [doc for doc in responses if not isinstance(doc, Exception)]
        if not docs:
            raise responses[0]
        rows = {str(row["id"]): normalize(row, doc.fetched_at) for doc in docs for row in doc.data}
        return list(rows.values()), any(len(doc.data) == 20 for doc in docs)

    async def detail(self, kind, identifier):
        doc = await self.http.request(
            "igdb",
            "/games",
            content=f"fields {FIELDS},artworks.url,screenshots.url,involved_companies.company.id,involved_companies.company.name,involved_companies.developer,involved_companies.publisher,game_modes.name,themes.name,player_perspectives.name; where id = {int(identifier)}; limit 1;",
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
    vn_ids = set()
    for website in data.get("websites") or []:
        url = urlsplit(website.get("url", ""))
        match = re.fullmatch(r"/app/([1-9][0-9]*)(?:/.*)?", url.path)
        if url.scheme == "https" and url.hostname == "store.steampowered.com" and match:
            steam_ids.add(match[1])
        vn_match = re.fullmatch(r"/(v[1-9][0-9]*)/?", url.path)
        if url.scheme == "https" and url.hostname == "vndb.org" and vn_match:
            vn_ids.add(vn_match[1])
    if len(steam_ids) == 1:
        ids["steam"] = steam_ids.pop()
    if len(vn_ids) == 1:
        ids["vndb"] = vn_ids.pop()
    released = data.get("first_release_date")
    return Media(
        id=f"igdb:game:{identifier}",
        kind="game",
        rating_count=data.get("rating_count"),
        title=data["name"],
        alternative_titles=[x["name"] for x in data.get("alternative_names", []) if x.get("name")][:20],
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
        backdrop_urls=list(
            dict.fromkeys(
                safe_url(x.get("url", "").replace("t_thumb", "t_720p"))
                for x in (data.get("artworks") or []) + (data.get("screenshots") or [])
                if safe_url(x.get("url", ""))
            )
        )[:40],
        platforms=[x["name"] for x in data.get("platforms") or []],
        credits=[
            {
                "name": c["company"]["name"],
                "role": role,
                "url": f"https://www.igdb.com/companies/{c['company']['id']}"
                if c["company"].get("id")
                else None,
            }
            for c in data.get("involved_companies", [])
            if (c.get("company") or {}).get("name")
            for flag, role in [("developer", "Developer"), ("publisher", "Publisher")]
            if c.get(flag)
        ],
        facts={
            label: ", ".join(x["name"] for x in data[key] if x.get("name"))
            for key, label in [
                ("game_modes", "Game modes"),
                ("themes", "Themes"),
                ("player_perspectives", "Perspective"),
            ]
            if data.get(key)
        },
        media_links=[
            {"label": label + " · Store page", "url": website["url"]}
            for website in data.get("websites", [])
            if safe_url(website.get("url"))
            for host, label in [
                ("www.gog.com", "GOG"),
                ("store.epicgames.com", "Epic Games"),
                ("store.playstation.com", "PlayStation"),
                ("www.xbox.com", "Xbox"),
                ("www.nintendo.com", "Nintendo"),
            ]
            if urlsplit(website["url"]).hostname == host
        ],
        external_ids=ids,
        source=origin,
        ratings=rating("IGDB users", data.get("rating"), 100, origin)
        + rating("IGDB critics", data.get("aggregated_rating"), 100, origin),
    )
