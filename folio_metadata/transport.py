"""Fixed upstream origins, bounded cache, deadlines, pacing and OAuth lifecycle."""

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .config import Settings

ORIGINS = {
    "apple": "https://itunes.apple.com",
    "tmdb": "https://api.themoviedb.org/3",
    "vndb": "https://api.vndb.org/kana",
    "anilist": "https://graphql.anilist.co",
    "mangaupdates": "https://api.mangaupdates.com/v1",
    "igdb": "https://api.igdb.com/v4",
    "musicbrainz": "https://musicbrainz.org/ws/2",
    "omdb": "https://www.omdbapi.com",
    "steam": "https://api.steampowered.com",
}
INTERVALS = {
    "apple": 3.0,
    "tmdb": 0.1,
    "vndb": 2.1,
    "anilist": 2.1,
    "mangaupdates": 1.1,
    "igdb": 0.3,
    "musicbrainz": 1.1,
    "omdb": 1.1,
    "steam": 1.1,
}
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_CACHE_BYTES = 32 * 1024 * 1024


class ProviderError(Exception):
    """Intentionally contains no upstream bodies, URLs or credentials."""


class NotConfigured(ProviderError):
    pass


class Disabled(ProviderError):
    pass


@dataclass(frozen=True)
class Document:
    data: dict | list
    fetched_at: str


class Transport:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client, self.settings = client, settings
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.locks = {name: asyncio.Lock() for name in ORIGINS}
        self.next_call = dict.fromkeys(ORIGINS, 0.0)
        self.oauth_lock = asyncio.Lock()
        self.access_token = ""
        self.token_expiry = 0.0

    def require(self, provider):
        s = self.settings
        if provider == "anilist" and not s.anilist_enabled:
            raise Disabled()
        needed = {
            "tmdb": [s.tmdb_token],
            "igdb": [s.igdb_client_id, s.igdb_client_secret],
            "omdb": [s.omdb_api_key],
        }.get(provider, [])
        if any(not value.get_secret_value() for value in needed):
            raise NotConfigured()

    async def _read(self, method, url, **kwargs):
        async with self.client.stream(method, url, **kwargs) as response:
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ProviderError()
                chunks.append(chunk)
            return response.status_code, response.headers, b"".join(chunks)

    async def _token(self):
        async with self.oauth_lock:
            if self.access_token and self.token_expiry > time.monotonic():
                return self.access_token
            status, _, body = await self._read(
                "POST",
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": self.settings.igdb_client_id.get_secret_value(),
                    "client_secret": self.settings.igdb_client_secret.get_secret_value(),
                    "grant_type": "client_credentials",
                },
            )
            if status != 200:
                raise ProviderError()
            data = json.loads(body)
            self.access_token = data["access_token"]
            self.token_expiry = time.monotonic() + max(0, int(data["expires_in"]) - 60)
            return self.access_token

    def _backoff(self, provider, headers):
        value = headers.get("Retry-After", "60")
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = parsedate_to_datetime(value).timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                delay = 60
        # Never retry earlier than the provider requests.
        self.next_call[provider] = time.monotonic() + max(60, delay)

    async def request(self, provider, path, *, payload=None, params=None, content=None):
        self.require(provider)
        # Only adapters select paths. Neither client-supplied URLs nor redirects are accepted.
        if not path.startswith("/") or path.startswith("//"):
            raise ProviderError()
        key = (provider, path, json.dumps([payload, params, content], sort_keys=True))
        try:
            return await asyncio.wait_for(
                self._request(provider, path, key, payload, params, content),
                timeout=self.settings.provider_timeout,
            )
        except (httpx.HTTPError, TimeoutError, asyncio.TimeoutError, ValueError, KeyError, TypeError) as exc:
            raise ProviderError() from exc

    async def _request(self, provider, path, key, payload, params, content):
        async with self.locks[provider]:
            now = time.monotonic()
            cached = self.cache.get(key)
            if cached and cached[0] > now:
                self.cache.move_to_end(key)
                return cached[1]
            if cached:
                self.cache_bytes -= self.cache.pop(key)[2]
            delay = self.next_call[provider] - now
            if delay > 3:
                raise ProviderError()
            if delay > 0:
                await asyncio.sleep(delay)
            params = dict(params or {})
            headers = {}
            if provider == "tmdb":
                headers["Authorization"] = f"Bearer {self.settings.tmdb_token.get_secret_value()}"
            elif provider == "igdb":
                headers = {
                    "Client-ID": self.settings.igdb_client_id.get_secret_value(),
                    "Authorization": f"Bearer {await self._token()}",
                    "Content-Type": "text/plain",
                }
            elif provider == "omdb":
                params["apikey"] = self.settings.omdb_api_key.get_secret_value()
            elif provider == "musicbrainz":
                headers["User-Agent"] = f"FolioMetadata/0.2 ({self.settings.musicbrainz_contact})"
            for attempt in range(2):
                self.next_call[provider] = time.monotonic() + INTERVALS[provider]
                status, response_headers, body = await self._read(
                    "POST" if payload is not None or content is not None else "GET",
                    ORIGINS[provider] + path,
                    json=payload,
                    params=params,
                    content=content,
                    headers=headers,
                )
                if status == 401 and provider == "igdb" and attempt == 0:
                    self.access_token = ""
                    headers["Authorization"] = f"Bearer {await self._token()}"
                    await asyncio.sleep(INTERVALS[provider])
                    continue
                break
            if status == 404:
                return None
            if status in (429, 503):
                self._backoff(provider, response_headers)
            if status < 200 or status >= 300:
                raise ProviderError()
            data = json.loads(body)
            if not isinstance(data, (dict, list)):
                raise ProviderError()
            # HTTP 200 does not necessarily mean a successful provider response.
            if isinstance(data, dict) and (data.get("errors") or data.get("Response") == "False"):
                return Document(data, datetime.now(timezone.utc).isoformat())
            doc = Document(data, datetime.now(timezone.utc).isoformat())
            self.cache[key] = (time.monotonic() + self.settings.cache_ttl, doc, len(body))
            self.cache_bytes += len(body)
            while len(self.cache) > self.settings.cache_entries or self.cache_bytes > MAX_CACHE_BYTES:
                self.cache_bytes -= self.cache.popitem(last=False)[1][2]
            return doc
