import asyncio
import re
import unicodedata
from urllib.parse import urlsplit

from ..models import Media, MediaLink
from ..transport import ProviderError
from .common import rating, source

ENTITIES = {"album": "release-group", "track": "recording"}


def key(value):
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKD", value).casefold())


def linked_apple_ids(data):
    ids = set()
    for relation in data.get("relations", []):
        url = urlsplit((relation.get("url") or {}).get("resource", ""))
        match = re.fullmatch(r"/(?:[a-z]{2}/)?album/(?:[^/]+/)?([1-9][0-9]*)/?", url.path)
        if (
            url.scheme == "https"
            and url.hostname == "music.apple.com"
            and not url.username
            and not url.query
            and match
        ):
            ids.add(match[1])
    return ids


def linked_spotify_urls(data):
    """Only source-linked Spotify album IDs; never guess from a title match."""
    urls = set()
    for relation in data.get("relations", []):
        parsed = urlsplit((relation.get("url") or {}).get("resource", ""))
        match = re.fullmatch(r"/(?:intl-[a-z]{2}/)?album/([A-Za-z0-9]{22})/?", parsed.path)
        if parsed.scheme == "https" and parsed.netloc == "open.spotify.com" and match:
            urls.add(f"https://open.spotify.com/album/{match[1]}")
    return sorted(urls)


def add_spotify_links(media, data):
    known = {link.url for link in media.media_links}
    for url in linked_spotify_urls(data):
        if len(media.media_links) >= 4:
            break
        if url not in known:
            edition = str(data.get("disambiguation") or "linked edition")[:100]
            media.media_links.append(MediaLink(label=f"Spotify \u00b7 Listen ({edition})", url=url))


class MusicBrainz:
    kinds = ("album", "track")

    def __init__(self, transport):
        self.http = transport

    async def catalog_hints(self, query):
        try:
            doc = await asyncio.wait_for(
                self.http.request(
                    "apple",
                    "/search",
                    params={"term": query, "entity": "album", "limit": 20, "country": "US"},
                ),
                4,
            )
            return doc.data.get("results", []) if doc else []
        except (ProviderError, TimeoutError, asyncio.TimeoutError):
            return []

    async def search(self, query, kind, page):
        entity = ENTITIES[kind]
        doc, hints = await asyncio.gather(
            self.http.request(
                "musicbrainz",
                f"/{entity}/",
                params={
                    "query": query,
                    "dismax": "true",
                    "fmt": "json",
                    "limit": 20,
                    "offset": (page - 1) * 20,
                },
            ),
            self.catalog_hints(query) if kind == "album" and page == 1 else asyncio.sleep(0, result=[]),
        )
        records = [normalize(x, kind, doc.fetched_at) for x in doc.data[entity + "s"]]
        # Advisory relevance only. Never infer shared IDs, merge records, or copy artwork from title matches.
        for record in records:
            for index, hint in enumerate(hints):
                if key(hint.get("collectionName", "")) == key(record.title) and key(
                    hint.get("artistName", "")
                ) in [key(x) for x in record.creators]:
                    record.search_priority = 1.1 / (1 + index * 0.2)
                    break
        # Resolve one leading candidate within a strict budget; discovery survives lookup failures.
        if kind == "album":
            candidates = sorted(
                (r for r in records if r.search_priority), key=lambda r: -(r.search_priority or 0)
            )
            if candidates:
                record = candidates[0]
                hint = next(
                    (
                        h
                        for h in hints
                        if key(h.get("collectionName", "")) == key(record.title)
                        and key(h.get("artistName", "")) in [key(x) for x in record.creators]
                    ),
                    None,
                )
                if hint:
                    try:
                        ids = await asyncio.wait_for(self.album_links(record.source.id), 4)
                        candidate_id = str(hint["collectionId"])
                        if candidate_id in ids:
                            record.external_ids["apple"] = candidate_id
                        elif len(ids) == 1:
                            record.external_ids["apple"] = next(iter(ids))
                    except (ProviderError, TimeoutError, asyncio.TimeoutError, KeyError):
                        pass
        return records, page * 20 < doc.data["count"]

    async def album_links(self, identifier, data=None, media=None):
        if data is None:
            doc = await self.http.request(
                "musicbrainz",
                f"/release-group/{identifier}",
                params={"fmt": "json", "inc": "url-rels+releases"},
            )
            data = doc.data if doc else {}
        ids = linked_apple_ids(data)
        if media is not None:
            add_spotify_links(media, data)
        if media is not None:
            if media.media_links or not data.get("releases"):
                return ids
            # One bounded browse, not one request per edition. Exact group identity only.
            doc = await self.http.request(
                "musicbrainz",
                "/release",
                params={
                    "release-group": identifier,
                    "status": "official",
                    "limit": 20,
                    "fmt": "json",
                    "inc": "url-rels+release-groups",
                },
            )
            edition_ids = set()
            for edition in (doc.data.get("releases", []) if doc else [])[:20]:
                if (
                    edition.get("status") != "Official"
                    or (edition.get("release-group") or {}).get("id") != identifier
                ):
                    continue
                add_spotify_links(media, edition)
                edition_ids.update(linked_apple_ids(edition))
            if len(media.media_links) > 1:
                for index, link in enumerate(media.media_links, 1):
                    if link.label.endswith("(linked edition)"):
                        link.label = f"Spotify · Listen (linked edition {index})"
            return ids or edition_ids
        if ids:
            return ids
        # One official edition only, never arbitrary URLs or unbounded release fan-out.
        release = next(
            (
                r
                for r in data.get("releases", [])
                if r.get("status") == "Official"
                and re.fullmatch(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", r.get("id", ""))
            ),
            None,
        )
        if release:
            doc = await self.http.request(
                "musicbrainz", f"/release/{release['id']}", params={"fmt": "json", "inc": "url-rels"}
            )
            if doc:
                ids.update(linked_apple_ids(doc.data))
                if media is not None:
                    add_spotify_links(media, doc.data)
        return ids

    async def detail(self, kind, identifier):
        entity = ENTITIES[kind]
        includes = "artist-credits+genres+ratings" + (
            "+releases" if kind == "track" else "+releases+url-rels"
        )
        doc = await self.http.request(
            "musicbrainz", f"/{entity}/{identifier}", params={"fmt": "json", "inc": includes}
        )
        result = normalize(doc.data, kind, doc.fetched_at) if doc else None
        if result and kind == "album":
            try:
                ids = await asyncio.wait_for(self.album_links(identifier, doc.data, result), 3)
                # Only a unique mapping is safe for general detail responses.
                if len(ids) == 1:
                    result.external_ids["apple"] = ids.pop()
            except (ProviderError, TimeoutError, asyncio.TimeoutError):
                pass
        return result


def normalize(data, kind, fetched_at):
    identifier = data["id"]
    entity = ENTITIES[kind]
    origin = source("musicbrainz", identifier, f"https://musicbrainz.org/{entity}/{identifier}", fetched_at)
    votes = data.get("rating") or {}
    # CAA resolves exact MusicBrainz IDs. Missing covers return 404 and use the client placeholder.
    art_type, art_id = "release-group", identifier
    if kind == "track":
        art_type = "release"
        art_id = next((x["id"] for x in data.get("releases", []) if x.get("id")), None)
    return Media(
        id=f"musicbrainz:{kind}:{identifier}",
        kind=kind,
        title=data["title"],
        image_url=f"https://coverartarchive.org/{art_type}/{art_id}/front-500" if art_id else None,
        release_date=data.get("first-release-date") or None,
        description=data.get("disambiguation") or None,
        creators=[
            x.get("name") or x["artist"]["name"]
            for x in data.get("artist-credit") or []
            if isinstance(x, dict)
        ],
        credits=[
            {
                "name": credit.get("name") or (credit.get("artist") or {}).get("name"),
                "role": "Artist",
                "url": f"https://musicbrainz.org/artist/{credit['artist']['id']}"
                if re.fullmatch(
                    r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}",
                    (credit.get("artist") or {}).get("id", ""),
                )
                else None,
            }
            for credit in data.get("artist-credit") or []
            if isinstance(credit, dict) and (credit.get("name") or (credit.get("artist") or {}).get("name"))
        ],
        genres=[x["name"] for x in data.get("genres") or data.get("tags") or []],
        ratings=rating("MusicBrainz users", votes.get("value"), 5, origin),
        rating_count=votes.get("votes-count"),
        facts={"Music format": data["primary-type"]} if data.get("primary-type") else {},
        format=data.get("primary-type"),
        external_ids={
            "musicbrainz": identifier,
            **({"isrc": data["isrcs"][0].upper()} if len(data.get("isrcs", [])) == 1 else {}),
        },
        source=origin,
    )
