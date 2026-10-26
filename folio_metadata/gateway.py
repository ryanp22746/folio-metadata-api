"""Provider registry and bounded orchestration; no title-based identity inference."""

import asyncio
import re

from .adapters.anilist import AniList
from .adapters.apple import Apple
from .adapters.catalog import TMDB, VNDB
from .adapters.enrichment import OMDb, Steam
from .adapters.igdb import IGDB
from .adapters.jikan import Jikan
from .adapters.mal import MyAnimeList
from .adapters.mangaupdates import MangaUpdates
from .adapters.musicbrainz import MusicBrainz
from .adapters.openlibrary import OpenLibrary
from .adapters.spotify import Spotify
from .models import ProviderInfo
from .transport import Disabled, NotConfigured, Transport

DOCS = {
    "spotify": "https://developer.spotify.com/documentation/web-api",
    "mal": "https://myanimelist.net/apiconfig/references/api/v2",
    "jikan": "https://docs.api.jikan.moe/",
    "openlibrary": "https://openlibrary.org/dev/docs/api/search",
    "apple": "https://performance-partners.apple.com/search-api",
    "tmdb": "https://developer.themoviedb.org/docs/getting-started",
    "vndb": "https://api.vndb.org/kana",
    "anilist": "https://docs.anilist.co/guide/terms-of-use",
    "mangaupdates": "https://api.mangaupdates.com/",
    "igdb": "https://api-docs.igdb.com/",
    "musicbrainz": "https://musicbrainz.org/doc/MusicBrainz_API",
    "omdb": "https://www.omdbapi.com/",
    "steam": "https://partner.steamgames.com/doc/webapi/IUserReviewsService",
}
REQUIRED = {
    "spotify": ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"],
    "mal": ["MAL_CLIENT_ID"],
    "tmdb": ["TMDB_READ_TOKEN"],
    "igdb": ["IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET"],
    "omdb": ["OMDB_API_KEY"],
    "anilist": ["ANILIST_ENABLED (only after resolving usage permission)"],
}


class Gateway:
    def __init__(self, client, settings):
        self.http = Transport(client, settings)
        self.adapters = {
            "spotify": Spotify(self.http),
            "mal": MyAnimeList(self.http),
            "jikan": Jikan(self.http),
            "openlibrary": OpenLibrary(self.http),
            "vndb": VNDB(self.http),
            "tmdb": TMDB(self.http),
            "anilist": AniList(self.http),
            "mangaupdates": MangaUpdates(self.http),
            "igdb": IGDB(self.http),
            "musicbrainz": MusicBrainz(self.http),
            "apple": Apple(self.http),
            "omdb": OMDb(self.http),
            "steam": Steam(self.http),
        }

    def catalog(self):
        entries = []
        for name, adapter in self.adapters.items():
            status = "ready"
            try:
                self.http.require(name)
            except Disabled:
                status = "disabled"
            except NotConfigured:
                status = "not_configured"
            entries.append(
                ProviderInfo(
                    provider=name,
                    kinds=list(adapter.kinds),
                    status=status,
                    capabilities=["enrich"] if hasattr(adapter, "enrich") else ["search", "detail"],
                    required_configuration=REQUIRED.get(name, []),
                    documentation=DOCS[name],
                )
            )
        return entries

    def targets(self, kind=None, provider=None):
        return [
            (name, k)
            for name, adapter in self.adapters.items()
            if hasattr(adapter, "search")
            and (provider is None or provider == name)
            and not (
                name == "jikan"
                and provider is None
                and (kind is None or self.http.settings.mal_client_id.get_secret_value())
            )
            for k in adapter.kinds
            if kind is None or k == kind
        ]

    async def search(self, provider, query, kind, page):
        self.http.require(provider)
        return await asyncio.wait_for(
            self.adapters[provider].search(query, kind, page), self.http.settings.provider_timeout
        )

    async def detail(self, provider, kind, identifier):
        if provider in {"tmdb", "igdb"} and "-" in identifier:
            from .collections import special_detail

            return await asyncio.wait_for(
                special_detail(self.http, provider, kind, identifier), self.http.settings.provider_timeout
            )
        self.http.require(provider)
        return await asyncio.wait_for(
            self.adapters[provider].detail(kind, identifier), self.http.settings.provider_timeout
        )

    async def enrich(self, provider, identifier):
        self.http.require(provider)
        return await asyncio.wait_for(
            self.adapters[provider].enrich(identifier), self.http.settings.provider_timeout
        )

    def valid(self, provider, kind, identifier, enrichment=False):
        if not enrichment and provider in {"tmdb", "igdb"} and "-" in identifier:
            from .collections import valid

            return valid(provider, kind, identifier)
        adapter = self.adapters[provider]
        kinds = adapter.kinds if enrichment else getattr(adapter, "detail_kinds", adapter.kinds)
        if kind not in kinds or not hasattr(adapter, "enrich" if enrichment else "detail"):
            return False
        patterns = {
            "spotify": r"[a-zA-Z0-9]{22}",
            "openlibrary": r"OL[1-9][0-9]{0,12}W",
            "vndb": r"v[1-9][0-9]{0,9}",
            "omdb": r"tt[0-9]{7,12}",
            "musicbrainz": r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}",
        }
        if not re.fullmatch(patterns.get(provider, r"[1-9][0-9]{0,15}"), identifier):
            return False
        if provider == "steam" and int(identifier) > 4294967295:
            return False
        return not (provider == "anilist" and int(identifier) > 2147483647)
