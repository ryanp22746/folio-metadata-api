"""Keyless, paced public anime metadata from Jikan (MyAnimeList-derived)."""

import asyncio
import time

import httpx

from ..models import Media
from ..transport import ProviderError
from .common import rating, safe_url, source


def adult(data):
    return str(data.get("rating") or "").startswith("Rx") or any(
        row.get("name") == "Hentai" for row in data.get("genres", [])
    )


class Jikan:
    kinds = ("anime",)

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        doc = await self.http.request(
            "jikan", "/anime", params={"q": query, "page": page, "limit": 20, "sfw": "true"}
        )
        seen, rows = set(), []
        for row in doc.data["data"]:
            if row["mal_id"] in seen or adult(row):
                continue
            seen.add(row["mal_id"])
            rows.append(normalize(row, doc.fetched_at))
        return rows, bool(doc.data.get("pagination", {}).get("has_next_page"))

    async def detail(self, kind, identifier):
        started = time.monotonic()
        doc = await self.http.request("jikan", f"/anime/{identifier}/full")
        if not doc or not doc.data.get("data") or adult(doc.data["data"]):
            return None
        media = normalize(doc.data["data"], doc.fetched_at)

        remaining = min(6, self.http.settings.provider_timeout - (time.monotonic() - started) - 0.2)
        if remaining <= 0:
            return media

        async def optional(path):
            try:
                extra = await asyncio.wait_for(self.http.request("jikan", path), remaining)
                return extra.data.get("data", []) if extra else []
            except (ProviderError, httpx.HTTPError, KeyError, TypeError, ValueError, asyncio.TimeoutError):
                return []

        staff, cast = await asyncio.gather(
            optional(f"/anime/{identifier}/staff"), optional(f"/anime/{identifier}/characters")
        )
        credits = [credit.model_dump() for credit in media.credits]
        for row in staff[:100]:
            person = row.get("person") or {}
            for role in (row.get("positions") or ["Staff"])[:6]:
                if person.get("name"):
                    credits.append({"name": person["name"], "role": role, "url": safe_url(person.get("url"))})
        for row in cast[:60]:
            for actor in row.get("voice_actors", [])[:8]:
                person = actor.get("person") or {}
                if person.get("name"):
                    credits.append(
                        {
                            "name": person["name"],
                            "role": "Cast",
                            "character": (row.get("character") or {}).get("name"),
                            "note": actor.get("language"),
                            "url": safe_url(person.get("url")),
                        }
                    )
        return Media(**(media.model_dump() | {"credits": credits}))


def normalize(data, fetched_at):
    identifier = str(data["mal_id"])
    origin = source("jikan", identifier, f"https://myanimelist.net/anime/{identifier}", fetched_at)
    image = (data.get("images") or {}).get("jpg") or {}
    facts = {}
    for label, field in [
        ("Episodes", "episodes"),
        ("Episode duration", "duration"),
        ("Status", "status"),
        ("Source material", "source"),
        ("Age rating", "rating"),
        ("Season", "season"),
    ]:
        if data.get(field) is not None:
            facts[label] = str(data[field])
    if data.get("year"):
        facts["Season year"] = str(data["year"])
    aired = data.get("aired") or {}
    if aired.get("string"):
        facts["Aired"] = aired["string"]
    credits = []
    for field, role in [("studios", "Studio"), ("producers", "Producer"), ("licensors", "Licensor")]:
        for row in data.get(field, [])[:20]:
            if row.get("name"):
                credits.append({"name": row["name"], "role": role, "url": safe_url(row.get("url"))})
    links = []
    for row in data.get("streaming", [])[:12]:
        url = safe_url(row.get("url"))
        if url and row.get("name"):
            links.append({"label": row["name"] + " · Provider-linked page", "url": url})
    return Media(
        related_media=[
            {
                "provider": "jikan",
                "kind": "anime",
                "id": str(entry["mal_id"]),
                "title": entry["name"],
                "relation": row.get("relation", "Related"),
            }
            for row in data.get("relations", [])
            for entry in row.get("entry", [])
            if entry.get("type") == "anime" and entry.get("mal_id") and entry.get("name")
        ],
        id=f"jikan:anime:{identifier}",
        kind="anime",
        title=data.get("title_english") or data["title"],
        original_title=data.get("title_japanese"),
        alternative_titles=list(
            dict.fromkeys(
                [data["title"]]
                + data.get("title_synonyms", [])
                + [row["title"] for row in data.get("titles", []) if row.get("title")]
            )
        ),
        description=data.get("synopsis"),
        release_date=str(aired["from"])[:10] if aired.get("from") else None,
        image_url=safe_url(image.get("large_image_url") or image.get("image_url")),
        genres=list(
            dict.fromkeys(
                row["name"]
                for field in ["genres", "themes", "demographics"]
                for row in data.get(field, [])
                if row.get("name")
            )
        ),
        facts=facts,
        format=data.get("type"),
        creators=[row["name"] for row in data.get("studios", []) if row.get("name")],
        credits=credits,
        media_links=links,
        trailer_url=safe_url((data.get("trailer") or {}).get("url")),
        external_ids={"myanimelist": identifier},
        rating_count=data.get("scored_by"),
        ratings=rating("MyAnimeList users (via Jikan)", data.get("score"), 10, origin),
        source=origin,
    )
