"""Spotify catalog metadata. No playback, account history, or inferred review scores."""

import re

from ..models import Media
from ..transport import ProviderError
from .common import safe_url, source

ID = r"[a-zA-Z0-9]{22}"


def valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(ID, value))


def images(data):
    return list(
        dict.fromkeys(
            safe_url(i.get("url"))
            for i in sorted(data.get("images") or [], key=lambda i: i.get("width") or 0, reverse=True)
            if safe_url(i.get("url"))
        )
    )


def normalize(data, kind, fetched_at):
    identifier = data["id"]
    if not valid_id(identifier):
        raise ValueError("Invalid catalog identifier")
    album = data if kind == "album" else data.get("album") or {}
    portraits = images(album)
    artists = [a for a in data.get("artists", []) if a.get("name")]
    facts = {}
    if album.get("album_type"):
        facts["Release type"] = album["album_type"].capitalize()
    if album.get("total_tracks") is not None:
        facts["Tracks"] = str(album["total_tracks"])
    if album.get("label"):
        facts["Label"] = album["label"]
    if kind == "track":
        facts["Album"] = album.get("name") or ""
        if data.get("duration_ms") is not None:
            seconds = int(data["duration_ms"]) // 1000
            facts["Duration"] = f"{seconds // 60}:{seconds % 60:02}"
        if "explicit" in data:
            facts["Explicit content"] = "Yes" if data["explicit"] else "No"
        if data.get("track_number"):
            facts["Track number"] = str(data["track_number"])
        if data.get("disc_number"):
            facts["Disc"] = str(data["disc_number"])
    if album.get("release_date_precision"):
        facts["Release date precision"] = album["release_date_precision"].capitalize()
    copyright_lines = [c["text"] for c in album.get("copyrights", []) if c.get("text")]
    if copyright_lines:
        facts["Copyright"] = " · ".join(copyright_lines)
    href = f"https://open.spotify.com/{kind}/{identifier}"
    return Media(
        id=f"spotify:{kind}:{identifier}",
        kind=kind,
        title=data["name"],
        format=(album.get("album_type") or "Album").capitalize() if kind == "album" else "Track",
        source=source("spotify", identifier, href, fetched_at),
        creators=[a["name"] for a in artists],
        credits=[
            {
                "name": a["name"],
                "role": "Artist",
                "url": f"https://open.spotify.com/artist/{a['id']}" if valid_id(a.get("id")) else None,
            }
            for a in artists
        ],
        release_date=album.get("release_date"),
        image_url=portraits[0] if portraits else None,
        # Spotify's images are resolution variants of the same cover.
        portrait_urls=portraits[:1],
        genres=data.get("genres") or [],
        facts=facts,
        external_ids={
            "spotify": identifier,
            **{
                k: str(v).upper()
                for k, v in (data.get("external_ids") or {}).items()
                if k in ("isrc", "upc", "ean") and v
            },
        },
        media_links=[{"label": "Spotify · Listen", "url": href}],
        popularity=data.get("popularity"),
    )


class Spotify:
    kinds = ("album", "track")

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        doc = await self.http.request(
            "spotify",
            "/search",
            params={"q": query, "type": kind, "market": "US", "limit": 10, "offset": (page - 1) * 10},
        )
        block = doc.data.get(kind + "s") or {}
        rows = []
        for index, row in enumerate(block.get("items", [])):
            if row and valid_id(row.get("id")):
                media = normalize(row, kind, doc.fetched_at)
                # Spotify search order is relevance evidence, never a listener/review count.
                media.search_priority = 1.1 / (1 + ((page - 1) * 10 + index) * 0.2)
                rows.append(media)
        # A bare artist query should also find their records, not only releases named after them.
        if kind == "album" and page == 1:
            try:
                artists = await self.http.request(
                    "spotify", "/search", params={"q": query, "type": "artist", "limit": 5}
                )
                exact = [
                    a
                    for a in artists.data.get("artists", {}).get("items", [])
                    if a
                    and a.get("name", "").casefold().strip() == query.casefold().strip()
                    and valid_id(a.get("id"))
                ][:2]
                for artist in exact:
                    releases = await self.http.request(
                        "spotify",
                        f"/artists/{artist['id']}/albums",
                        params={"market": "US", "limit": 10, "include_groups": "album,single"},
                    )
                    rows.extend(
                        normalize(r, "album", releases.fetched_at)
                        for r in releases.data.get("items", [])
                        if r
                        and valid_id(r.get("id"))
                        and any(a.get("id") == artist["id"] for a in r.get("artists", []))
                    )
            except ProviderError:
                pass  # Keep the direct results usable when artist expansion is unavailable.
        # Keep direct search relevance when artist expansion repeats a release.
        unique = {}
        for media in rows:
            unique.setdefault(media.id, media)
        return list(unique.values()), bool(block.get("next"))

    async def detail(self, kind, identifier):
        doc = await self.http.request("spotify", f"/{kind}s/{identifier}", params={"market": "US"})
        return normalize(doc.data, kind, doc.fetched_at) if doc else None
