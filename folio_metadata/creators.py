"""Source-qualified creator discovery. Name matches are suggestions, never identity merges."""

import asyncio
import json
import re

import httpx

from .adapters.apple import normalize as apple_album
from .adapters.catalog import VN_FIELDS, normalize_tmdb, normalize_vn
from .adapters.common import safe_url, source, year
from .adapters.igdb import FIELDS as GAME_FIELDS
from .adapters.igdb import normalize as game
from .adapters.jikan import adult
from .adapters.jikan import normalize as anime
from .adapters.musicbrainz import normalize as music
from .adapters.openlibrary import normalize as book
from .adapters.spotify import normalize as spotify_media
from .adapters.spotify import valid_id as spotify_id
from .models import CreatorRef, CreatorWorks, Media, ProviderStatus
from .transport import Disabled, NotConfigured, ProviderError

PROVIDERS = ("vndb", "tmdb", "mangaupdates", "musicbrainz", "openlibrary", "igdb", "apple", "spotify")


def valid(provider, identifier):
    pattern = {
        "mal_studio": r"[1-9][0-9]{0,12}",
        "spotify": r"[a-zA-Z0-9]{22}",
        "apple": r"[1-9][0-9]{0,15}",
        "igdb": r"[1-9][0-9]{0,12}",
        "tmdb_company": r"[1-9][0-9]{0,12}",
        "vndb": r"[sp][1-9][0-9]{0,9}",
        "tmdb": r"[1-9][0-9]{0,12}",
        "openlibrary": r"OL[1-9][0-9]{0,12}A",
        "mangaupdates": r"[1-9][0-9]{0,15}",
        "musicbrainz": r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}",
    }.get(provider)
    return bool(pattern and re.fullmatch(pattern, identifier))


def creator(provider, row):
    identifier = str(row["id"])
    if row.get("_company"):
        provider = "tmdb_company"
    urls = {
        "spotify": f"https://open.spotify.com/artist/{identifier}",
        "apple": f"https://music.apple.com/us/artist/{identifier}",
        "igdb": f"https://www.igdb.com/companies/{identifier}",
        "tmdb_company": f"https://www.themoviedb.org/company/{identifier}",
        "openlibrary": f"https://openlibrary.org/authors/{identifier}",
        "vndb": f"https://vndb.org/{identifier}",
        "tmdb": f"https://www.themoviedb.org/person/{identifier}",
        "mangaupdates": row.get("url") or f"https://www.mangaupdates.com/author.html?id={identifier}",
        "musicbrainz": f"https://musicbrainz.org/artist/{identifier}",
    }
    description = (
        row.get("biography") or row.get("description") or row.get("bio") or row.get("disambiguation")
    )
    if isinstance(description, dict):
        description = description.get("value")
    if not isinstance(description, str):
        description = None
    image = None
    if provider == "tmdb" and row.get("profile_path"):
        image = "https://image.tmdb.org/t/p/h632" + row["profile_path"]
    elif provider == "tmdb_company" and row.get("logo_path"):
        image = "https://image.tmdb.org/t/p/w500" + row["logo_path"]
    elif provider == "spotify":
        image = next((safe_url(i.get("url")) for i in row.get("images", []) if safe_url(i.get("url"))), None)
    elif provider == "igdb" and (row.get("logo") or {}).get("image_id"):
        image = f"https://images.igdb.com/igdb/image/upload/t_logo_med/{row['logo']['image_id']}.png"
    elif provider == "openlibrary" and row.get("photos") and row["photos"][0] > 0:
        image = f"https://covers.openlibrary.org/a/id/{row['photos'][0]}-L.jpg"
    facts = {}
    for field, label in [
        ("known_for_department", "Known for"),
        ("birthday", "Born"),
        ("deathday", "Died"),
        ("place_of_birth", "Birthplace"),
        ("birth_date", "Born"),
        ("death_date", "Died"),
        ("type", "Type"),
        ("country", "Country"),
    ]:
        if row.get(field) and isinstance(row[field], str):
            facts[label] = row[field]
    if row.get("genres"):
        facts["Genres"] = " · ".join(str(g) for g in row["genres"][:12])
    if (row.get("area") or {}).get("name"):
        facts["Origin"] = row["area"]["name"]
    for field, label in [("begin", "Active since"), ("end", "Active until")]:
        if (row.get("life-span") or {}).get(field):
            facts[label] = row["life-span"][field]
    return CreatorRef(
        provider=provider,
        id=identifier,
        name=row.get("name") or row.get("title") or identifier,
        url=urls[provider],
        description=description,
        image_url=image,
        facts=facts,
        entity_links=list(
            dict.fromkeys(
                url
                for url in [
                    urls[provider],
                    safe_url(row.get("homepage")),
                    *[safe_url(r.get("url")) for r in row.get("websites", []) if isinstance(r, dict)],
                    *[
                        safe_url((r.get("url") or {}).get("resource"))
                        for r in row.get("relations", [])
                        if isinstance(r.get("url"), dict)
                    ],
                ]
                if url
            )
        ),
    )


async def works(http, provider, identifier, page):
    if provider == "mal_studio":
        http.require("jikan")
        # Profile coverage must not prevent the studio's actual works from loading.
        person = {}
        try:
            profile = await http.request("jikan", f"/producers/{identifier}/full")
            person = profile.data.get("data", {}) if profile else {}
        except (ProviderError, httpx.HTTPError):
            pass
        doc = await http.request(
            "jikan",
            "/anime",
            params={
                "producers": identifier,
                "page": page,
                "limit": 25,
                "order_by": "members",
                "sort": "desc",
                "sfw": "true",
            },
        )
        rows = {
            row["mal_id"]: row
            for row in doc.data.get("data", [])
            if not adult(row)
            and any(
                str(c.get("mal_id")) == identifier
                for field in ("studios", "producers", "licensors")
                for c in row.get(field, [])
            )
        }
        if not person:
            person = next(
                (
                    c
                    for row in rows.values()
                    for field in ("studios", "producers", "licensors")
                    for c in row.get(field, [])
                    if str(c.get("mal_id")) == identifier
                ),
                {},
            )
        return CreatorWorks(
            creator=CreatorRef(
                provider=provider,
                id=identifier,
                name=next(
                    (r["title"] for r in person.get("titles", []) if r.get("type") == "Default"),
                    person.get("name") or identifier,
                ),
                url=f"https://myanimelist.net/anime/producer/{identifier}",
                description=person.get("about"),
                image_url=safe_url((person.get("images", {}).get("jpg") or {}).get("image_url")),
            ),
            results=[anime(row, doc.fetched_at) for row in rows.values()],
            page=page,
            more=bool(doc.data.get("pagination", {}).get("has_next_page")),
        )
    http.require("tmdb" if provider == "tmdb_company" else provider)
    if provider == "spotify":
        person = await http.request("spotify", f"/artists/{identifier}")
        if not person:
            return None
        doc = await http.request(
            "spotify",
            f"/artists/{identifier}/albums",
            params={
                "market": "US",
                "include_groups": "album,single,appears_on,compilation",
                "limit": 10,
                "offset": (page - 1) * 10,
            },
        )
        track_page = {}
        track_stamp = doc.fetched_at
        try:
            tracks = await http.request(
                "spotify",
                "/search",
                params={
                    "q": 'artist:"' + person.data["name"].replace('"', "") + '"',
                    "type": "track",
                    "market": "US",
                    "limit": 10,
                    "offset": (page - 1) * 10,
                },
            )
            track_page = tracks.data.get("tracks") or {}
            track_stamp = tracks.fetched_at
        except ProviderError:
            pass  # Artist releases remain useful if track search is unavailable.
        results = [
            spotify_media(r, "album", doc.fetched_at)
            for r in doc.data.get("items", [])
            if r and spotify_id(r.get("id")) and any(a.get("id") == identifier for a in r.get("artists", []))
        ]
        results.extend(
            spotify_media(r, "track", track_stamp)
            for r in track_page.get("items", [])
            if r and spotify_id(r.get("id")) and any(a.get("id") == identifier for a in r.get("artists", []))
        )
        return CreatorWorks(
            creator=creator(provider, person.data),
            results=results,
            page=page,
            more=bool(doc.data.get("next") or track_page.get("next")),
        )
    if provider == "apple":
        doc = await http.request(
            "apple", "/lookup", params={"id": identifier, "entity": "album", "limit": 200, "country": "US"}
        )
        people = [
            row
            for row in doc.data.get("results", [])
            if row.get("wrapperType") == "artist" and str(row.get("artistId")) == identifier
        ]
        if not people:
            return None
        rows = [
            row
            for row in doc.data.get("results", [])
            if row.get("wrapperType") == "collection" and str(row.get("artistId")) == identifier
        ]
        return CreatorWorks(
            creator=creator(provider, {"id": identifier, "name": people[0]["artistName"]}),
            results=[apple_album(row, doc.fetched_at) for row in rows[(page - 1) * 20 : page * 20]],
            page=page,
            more=len(rows) > page * 20,
        )
    if provider == "igdb":
        company = await http.request(
            "igdb",
            "/companies",
            content=f"fields name,description,logo.image_id,websites.url; where id = {int(identifier)}; limit 1;",
        )
        if not company.data:
            return None
        doc = await http.request(
            "igdb",
            "/games",
            content=f"fields {GAME_FIELDS}; where involved_companies.company = {int(identifier)}; sort total_rating_count desc; limit 20; offset {(page - 1) * 20};",
        )
        return CreatorWorks(
            creator=creator(provider, company.data[0]),
            results=[game(row, doc.fetched_at) for row in doc.data],
            page=page,
            more=len(doc.data) == 20,
        )
    if provider == "tmdb_company":
        company = await http.request("tmdb", f"/company/{identifier}")
        if not company:
            return None
        docs = await asyncio.gather(
            *(
                http.request(
                    "tmdb",
                    f"/discover/{kind}",
                    params={
                        "with_companies": identifier,
                        "page": page,
                        "include_adult": "false",
                        "sort_by": "popularity.desc",
                    },
                )
                for kind in ["movie", "tv"]
            )
        )
        return CreatorWorks(
            creator=creator(provider, company.data),
            results=[
                normalize_tmdb(row, kind, doc.fetched_at)
                for kind, doc in zip(["movie", "tv"], docs)
                for row in doc.data.get("results", [])
            ],
            page=page,
            more=any(page < doc.data.get("total_pages", 1) for doc in docs),
        )
    if provider == "vndb":
        producer = identifier.startswith("p")
        filters = (
            ["id", "=", identifier] if producer else ["and", ["id", "=", identifier], ["ismain", "=", 1]]
        )
        person = await http.request(
            provider,
            "/producer" if producer else "/staff",
            payload={"filters": filters, "fields": "name,description", "results": 1},
        )
        if not person or not person.data.get("results"):
            return None
        doc = await http.request(
            provider,
            "/vn",
            payload={
                "filters": ["developer" if producer else "staff", "=", ["id", "=", identifier]],
                "fields": VN_FIELDS,
                "results": 20,
                "page": page,
                "sort": "rating",
                "reverse": True,
            },
        )
        results = [normalize_vn(row, doc.fetched_at) for row in doc.data["results"]]
        more = doc.data.get("more", False)
        ref = creator(provider, person.data["results"][0])
    elif provider == "tmdb":
        person = await http.request(provider, f"/person/{identifier}", params={"language": "en-US"})
        if not person:
            return None
        doc = await http.request(
            provider, f"/person/{identifier}/combined_credits", params={"language": "en-US"}
        )
        rows = {}
        for row in doc.data.get("cast", []) + doc.data.get("crew", []):
            kind = row.get("media_type")
            if kind in ("movie", "tv") and not row.get("adult"):
                rows.setdefault((kind, row["id"]), row)
        ordered = sorted(rows.values(), key=lambda r: -(r.get("popularity") or 0))
        results = [
            normalize_tmdb(row, row["media_type"], doc.fetched_at)
            for row in ordered[(page - 1) * 20 : page * 20]
        ]
        more = len(ordered) > page * 20
        ref = creator(provider, person.data)
    elif provider == "mangaupdates":
        person = await http.request(provider, f"/authors/{identifier}")
        if not person:
            return None
        doc = await http.request(provider, f"/authors/{identifier}/series", payload={})
        rows = doc.data.get("series_list", [])
        results = []
        for row in rows[(page - 1) * 20 : page * 20]:
            sid = str(row["series_id"])
            kind = "book" if row["title"].endswith("(Novel)") else "manga"
            results.append(
                Media(
                    id=f"mangaupdates:{kind}:{sid}",
                    kind=kind,
                    title=row["title"],
                    release_date=year(row.get("year")),
                    genres=row.get("genres") or [],
                    external_ids={"mangaupdates": sid},
                    source=source(provider, sid, row["url"], doc.fetched_at),
                )
            )
        more = len(rows) > page * 20
        ref = creator(provider, person.data)
    elif provider == "openlibrary":
        person = await http.request(provider, f"/authors/{identifier}.json")
        if not person:
            return None
        doc = await http.request(
            provider, f"/authors/{identifier}/works.json", params={"limit": 20, "offset": (page - 1) * 20}
        )
        entries = doc.data.get("entries", [])
        results = [
            book(
                {
                    "key": row["key"],
                    "title": row["title"],
                    "author_name": [person.data["name"]],
                    "subject": row.get("subjects") or [],
                    "cover_i": next((c for c in row.get("covers", []) if isinstance(c, int) and c > 0), None),
                },
                doc.fetched_at,
            )
            for row in entries
            if re.fullmatch(r"/works/OL[1-9][0-9]*W", row.get("key", ""))
        ]
        more = (
            doc.data.get("size", (page - 1) * 20 + len(entries) + (1 if len(entries) == 20 else 0))
            > page * 20
        )
        ref = creator(provider, {**person.data, "id": identifier})
    else:
        person = await http.request(
            provider, f"/artist/{identifier}", params={"fmt": "json", "inc": "url-rels"}
        )
        if not person:
            return None
        results, more = [], False
        for entity, kind in [("release-group", "album"), ("recording", "track")]:
            doc = await http.request(
                provider,
                f"/{entity}",
                params={
                    "artist": identifier,
                    "fmt": "json",
                    "limit": 20,
                    "offset": (page - 1) * 20,
                    "inc": "artist-credits",
                },
            )
            results.extend(music(row, kind, doc.fetched_at) for row in doc.data.get(entity + "s", []))
            more = more or doc.data.get(entity + "-count", 0) > page * 20
        ref = creator(provider, person.data)
    return CreatorWorks(creator=ref, results=results, page=page, more=more)


async def find(http, query):
    async def run(provider):
        try:
            http.require(provider)

            async def lookup():
                if provider == "spotify":
                    doc = await http.request(
                        "spotify", "/search", params={"q": query, "type": "artist", "limit": 5}
                    )
                    return doc.data.get("artists", {}).get("items", [])
                if provider == "apple":
                    doc = await http.request(
                        "apple",
                        "/search",
                        params={"term": query, "entity": "musicArtist", "limit": 5, "country": "US"},
                    )
                    return [
                        {"id": r["artistId"], "name": r["artistName"]}
                        for r in doc.data.get("results", [])
                        if r.get("artistId") and r.get("artistName")
                    ]
                if provider == "igdb":
                    doc = await http.request(
                        "igdb",
                        "/companies",
                        content=f"fields name; where name ~ *{json.dumps(query)}*; limit 5;",
                    )
                    return doc.data
                if provider == "vndb":
                    doc = await http.request(
                        provider,
                        "/staff",
                        payload={
                            "filters": ["and", ["search", "=", query], ["ismain", "=", 1]],
                            "fields": "name",
                            "results": 5,
                        },
                    )
                    return doc.data.get("results", [])
                if provider == "mangaupdates":
                    doc = await http.request(provider, "/authors/search", payload={"search": query})
                    return [r["record"] for r in doc.data.get("results", [])[:5]]
                if provider == "musicbrainz":
                    doc = await http.request(
                        provider,
                        "/artist/",
                        params={"query": json.dumps(query, ensure_ascii=False), "fmt": "json", "limit": 5},
                    )
                    return doc.data.get("artists", [])
                if provider == "openlibrary":
                    doc = await http.request(
                        provider, "/search/authors.json", params={"q": query, "limit": 5}
                    )
                    return [{**row, "id": row["key"]} for row in doc.data.get("docs", [])[:5] if "key" in row]
                doc = await http.request(
                    provider, "/search/person", params={"query": query, "include_adult": "false"}
                )
                rows = list(doc.data.get("results", []))
                companies = await http.request("tmdb", "/search/company", params={"query": query})
                rows += [{**r, "_company": True} for r in companies.data.get("results", [])[:5]]
                if not rows and len(query.split()) == 2:
                    doc = await http.request(
                        provider,
                        "/search/person",
                        params={"query": " ".join(reversed(query.split())), "include_adult": "false"},
                    )
                    rows = doc.data.get("results", [])
                return sorted(
                    rows,
                    key=lambda row: (
                        row.get("name", "").casefold() != query.casefold(),
                        not row.get("_company", False),
                    ),
                )[:5]

            rows = await asyncio.wait_for(lookup(), 8)
            return [
                creator(provider, r) for r in rows if valid(provider, str(r.get("id", "")))
            ], ProviderStatus(provider=provider, status="ok")
        except Disabled:
            return [], ProviderStatus(provider=provider, status="disabled")
        except NotConfigured:
            return [], ProviderStatus(provider=provider, status="not_configured")
        except (
            ProviderError,
            TimeoutError,
            KeyError,
            TypeError,
            ValueError,
            AttributeError,
            httpx.HTTPError,
        ):
            return [], ProviderStatus(provider=provider, status="unavailable")

    batches = await asyncio.gather(*(run(p) for p in PROVIDERS))
    return {"matches": [m for batch, _ in batches for m in batch], "providers": [s for _, s in batches]}
