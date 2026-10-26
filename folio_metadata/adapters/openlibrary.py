"""Bounded human-facing book lookup using Open Library work identities."""

import asyncio
import re
import time
from collections import OrderedDict

import httpx

from ..models import Media
from ..transport import ProviderError
from .common import rating, source

FIELDS = "key,title,author_name,first_publish_year,cover_i,subject,ratings_average,ratings_count"


GENRE_ALIASES = {
    "Science fiction": [
        "science fiction",
        "science-fiction",
        "ciencia-ficción",
        "ciencia ficcion",
        "sciencefiction",
        "sci-fi",
    ],
    "Fantasy": ["fantasy", "fantasy fiction"],
    "Horror": ["horror", "horror fiction", "horror tales"],
    "Mystery": ["mystery", "mystery fiction", "detective and mystery stories"],
    "Thriller": ["thriller", "thrillers", "suspense fiction"],
    "Romance": ["romance", "romance fiction", "love stories"],
    "Historical fiction": ["historical fiction"],
    "Adventure": ["adventure", "adventure fiction", "adventure stories"],
    "Literary fiction": ["literary fiction"],
    "Nonfiction": ["nonfiction", "non-fiction"],
    "Biography": ["biography", "autobiography", "biographies"],
    "Memoir": ["memoir", "memoirs"],
    "History": ["history"],
    "Poetry": ["poetry", "poems"],
    "Comics": ["comics", "graphic novels", "comic books, strips, etc."],
    "Young adult": ["young adult fiction", "young adult literature"],
    "Children’s literature": ["children's fiction", "children's literature", "juvenile fiction"],
}


def book_genres(subjects):
    """Translate known catalog subjects; never treat award/index codes as genres."""
    found = []
    for raw in subjects or []:
        if not isinstance(raw, str) or re.search(r"[:=_]|https?:|award|prize|bestseller", raw, re.IGNORECASE):
            continue
        value = raw.casefold().strip()
        parts = [x.strip() for x in re.split(r"[,;]", value)]
        for genre, terms in GENRE_ALIASES.items():
            if genre not in found and (value in terms or any(x in terms for x in parts)):
                found.append(genre)
    return found


class OpenLibrary:
    kinds = ("book",)

    def __init__(self, transport):
        self.http = transport
        self.works = OrderedDict()

    async def search(self, query, kind, page):
        doc = await self.http.request(
            "openlibrary", "/search.json", params={"q": query, "fields": FIELDS, "limit": 20, "page": page}
        )
        rows = doc.data["docs"]
        results = [
            normalize(x, doc.fetched_at)
            for x in rows
            if re.fullmatch(r"(?:/works/)?OL[1-9][0-9]*W", x.get("key", ""))
        ]
        for media in results:
            self.works[media.source.id] = (time.monotonic() + self.http.settings.cache_ttl, media)
            self.works.move_to_end(media.source.id)
        while len(self.works) > 64:
            self.works.popitem(last=False)
        return results, page * 20 < doc.data.get("numFound", 0)

    async def detail(self, kind, identifier):
        cached = self.works.get(identifier)
        if cached and cached[0] > time.monotonic():
            media = cached[1].model_copy(deep=True)
        else:
            index = await self.http.request(
                "openlibrary",
                "/search.json",
                params={"q": f"key:/works/{identifier}", "fields": FIELDS, "limit": 1},
            )
            row = (
                next((x for x in index.data["docs"] if x.get("key") == f"/works/{identifier}"), None)
                if index
                else None
            )
            if row is None:
                return None
            media = normalize(row, index.fetched_at)
        # Search supplies the earliest year; work.first_publish_date can be a later edition.
        try:
            doc = await asyncio.wait_for(self.http.request("openlibrary", f"/works/{identifier}.json"), 2)
            if doc and doc.data.get("key") == f"/works/{identifier}":
                description = doc.data.get("description")
                media.description = description.get("value") if isinstance(description, dict) else description
                media.portrait_urls = [
                    f"https://covers.openlibrary.org/b/id/{cover}-L.jpg?default=false"
                    for cover in doc.data.get("covers", [])
                    if isinstance(cover, int) and cover > 0
                ][:30]
        except (ProviderError, httpx.HTTPError, asyncio.TimeoutError):
            pass
        return media


def normalize(data, fetched_at):
    identifier = data["key"].removeprefix("/works/")
    origin = source("openlibrary", identifier, f"https://openlibrary.org/works/{identifier}", fetched_at)
    cover = data.get("cover_i")
    return Media(
        id=f"openlibrary:book:{identifier}",
        kind="book",
        title=data["title"],
        creators=data.get("author_name") or [],
        release_date=str(data["first_publish_year"]) if data.get("first_publish_year") else None,
        genres=book_genres(data.get("subject")),
        image_url=f"https://covers.openlibrary.org/b/id/{cover}-L.jpg?default=false"
        if isinstance(cover, int) and cover > 0
        else None,
        rating_count=data.get("ratings_count"),
        ratings=rating(
            "Open Library users",
            data.get("ratings_average") if data.get("ratings_count") else None,
            5,
            origin,
        ),
        external_ids={"openlibrary": identifier},
        source=origin,
    )
