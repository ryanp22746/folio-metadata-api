"""Bounded character-to-title discovery using explicit catalog relationships."""

import asyncio
import re
import unicodedata

from .adapters.jikan import adult, normalize
from .transport import ProviderError


def words(value):
    return set(re.findall(r"\w+", unicodedata.normalize("NFKD", value).casefold()))


async def characters(http, query):
    http.require("jikan")
    doc = await http.request("jikan", "/characters", params={"q": query, "limit": 5})
    candidates = sorted(
        [
            row
            for row in doc.data.get("data", [])
            if any(
                words(query) <= words(name) for name in [row.get("name", ""), *(row.get("nicknames") or [])]
            )
        ],
        key=lambda row: -(row.get("favorites") or 0),
    )[:1]
    matches = []
    for character in candidates:
        linked = await http.request("jikan", f"/characters/{int(character['mal_id'])}/anime")
        rows = sorted(linked.data.get("data", []), key=lambda row: row.get("role") != "Main")[:3]
        results = []
        for row in rows:
            try:
                doc = await asyncio.wait_for(
                    http.request("jikan", f"/anime/{int(row['anime']['mal_id'])}"), 4
                )
                anime = doc.data.get("data") if doc else None
                if anime and not adult(anime):
                    results.append(normalize(anime, doc.fetched_at))
            except (ProviderError, TimeoutError):
                continue
        if results:
            matches.append(
                {
                    "name": character["name"],
                    "url": f"https://myanimelist.net/character/{int(character['mal_id'])}",
                    "results": results,
                }
            )
    return {"matches": matches}
