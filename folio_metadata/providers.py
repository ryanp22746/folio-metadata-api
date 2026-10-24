import asyncio
import time
from collections import OrderedDict
from datetime import datetime, timezone

import httpx

from .models import Media, Source


class ProviderError(Exception):
    pass


class NotConfigured(ProviderError):
    pass


class Gateway:
    """Bounded cache and serialized provider calls; one process per deployment."""

    def __init__(self, client: httpx.AsyncClient, tmdb_token: str = ""):
        self.client = client
        self.tmdb_token = tmdb_token
        self.cache = OrderedDict()
        self.locks = {name: asyncio.Lock() for name in ("vndb", "tmdb")}
        self.next_call = {"vndb": 0.0, "tmdb": 0.0}

    async def request(self, provider, path, payload=None, params=None):
        if provider == "tmdb" and not self.tmdb_token:
            raise NotConfigured()
        key = (provider, path, repr(payload), repr(params))
        async with self.locks[provider]:
            now = time.monotonic()
            cached = self.cache.get(key)
            if cached and cached[0] > now:
                self.cache.move_to_end(key)
                return cached[1]
            # Pace normal requests; reject long cooldowns rather than waiting through them.
            delay = self.next_call[provider] - now
            if delay > 2:
                raise ProviderError()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_call[provider] = time.monotonic() + (2.0 if provider == "vndb" else 0.1)
            base = "https://api.vndb.org/kana" if provider == "vndb" else "https://api.themoviedb.org/3"
            headers = {"Authorization": f"Bearer {self.tmdb_token}"} if provider == "tmdb" else {}
            try:
                response = await self.client.request(
                    "POST" if payload is not None else "GET",
                    base + path,
                    json=payload,
                    params=params,
                    headers=headers,
                )
                if response.status_code == 429:
                    try:
                        delay = max(60, min(3600, float(response.headers.get("Retry-After", "60"))))
                    except ValueError:
                        delay = 60
                    self.next_call[provider] = time.monotonic() + delay
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise TypeError("Invalid provider response")
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                raise ProviderError() from exc
            data["_fetched_at"] = datetime.now(timezone.utc).isoformat()
            self.cache[key] = (time.monotonic() + 900, data)
            while len(self.cache) > 512:
                self.cache.popitem(last=False)
            return data

    async def search(self, provider, query, kind, page):
        if provider == "vndb":
            data = await self.request(
                provider,
                "/vn",
                payload={
                    "filters": ["search", "=", query],
                    "fields": VN_FIELDS,
                    "results": 20,
                    "page": page,
                    "sort": "searchrank",
                },
            )
            return [normalize_vn(x, data["_fetched_at"]) for x in data["results"]], data.get("more", False)
        data = await self.request(
            provider,
            f"/search/{kind}",
            params={
                "query": query,
                "page": page,
                "include_adult": "false",
                "language": "en-US",
            },
        )
        return [normalize_tmdb(x, kind, data["_fetched_at"]) for x in data["results"]], page < data.get(
            "total_pages", 1
        )

    async def detail(self, provider, kind, identifier):
        if provider == "vndb":
            data = await self.request(
                provider,
                "/vn",
                payload={
                    "filters": ["id", "=", identifier],
                    "fields": VN_FIELDS,
                    "results": 1,
                },
            )
            return normalize_vn(data["results"][0], data["_fetched_at"]) if data["results"] else None
        data = await self.request(
            provider,
            f"/{kind}/{identifier}",
            params={
                "append_to_response": "external_ids",
                "language": "en-US",
            },
        )
        return normalize_tmdb(data, kind, data["_fetched_at"]) if data else None


VN_FIELDS = "title,alttitle,description,released,image.url,image.sexual,image.violence"


def source(provider, identifier, url, fetched_at):
    return Source(provider=provider, id=str(identifier), url=url, fetched_at=fetched_at)


def normalize_vn(data, fetched_at):
    identifier = data["id"]
    picture = data.get("image") or {}
    return Media(
        id=f"vndb:visual_novel:{identifier}",
        kind="visual_novel",
        title=data["title"],
        original_title=data.get("alttitle"),
        description=data.get("description"),
        description_format="vndb_markup",
        release_date=data.get("released"),
        image_url=picture.get("url"),
        image_sexual=picture.get("sexual"),
        image_violence=picture.get("violence"),
        external_ids={"vndb": identifier},
        source=source("vndb", identifier, f"https://vndb.org/{identifier}", fetched_at),
    )


def normalize_tmdb(data, kind, fetched_at):
    identifier = str(data["id"])
    ids = {"tmdb": identifier}
    imdb = (data.get("external_ids") or {}).get("imdb_id") or data.get("imdb_id")
    if imdb:
        ids["imdb"] = imdb
    return Media(
        id=f"tmdb:{kind}:{identifier}",
        kind=kind,
        title=data["title"] if kind == "movie" else data["name"],
        original_title=data.get("original_title" if kind == "movie" else "original_name"),
        description=data.get("overview"),
        release_date=data.get("release_date" if kind == "movie" else "first_air_date") or None,
        image_url=f"https://image.tmdb.org/t/p/w500{data['poster_path']}"
        if data.get("poster_path")
        else None,
        genres=[g["name"] for g in data.get("genres", [])],
        external_ids=ids,
        source=source("tmdb", identifier, f"https://www.themoviedb.org/{kind}/{identifier}", fetched_at),
    )
