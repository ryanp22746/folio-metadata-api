"""Explicit catalog membership, separate identities for parents and their parts."""

import re

from .adapters.common import source
from .models import Media


def valid(provider, kind, identifier):
    if provider == "tmdb" and kind == "tv":
        return bool(
            re.fullmatch(r"[1-9][0-9]{0,15}(?:-season-[0-9]{1,4}(?:-episode-[1-9][0-9]{0,4})?)?", identifier)
        )
    return bool(re.fullmatch(r"(?:collection-)?[1-9][0-9]{0,15}", identifier)) and (
        (provider, kind) in {("tmdb", "movie"), ("igdb", "game")}
    )


def tmdb_part(series, row, season, fetched_at, episode=None):
    identifier = f"{series['id']}-season-{season}"
    suffix, url = f"Season {season}" if season else "Specials", f"/tv/{series['id']}/season/{season}"
    facts = {"Series": series["name"], "Season number": str(season)}
    if episode is not None:
        identifier += f"-episode-{episode}"
        suffix += f" · Episode {episode}: {row['name']}"
        url += f"/episode/{episode}"
        facts["Episode number"] = str(episode)
    elif row.get("episode_count") is not None or "episodes" in row:
        facts["Episodes"] = str(row.get("episode_count", len(row.get("episodes", []))))
    if row.get("runtime"):
        facts["Runtime"] = f"{row['runtime']} minutes"
    portrait = row.get("poster_path") or series.get("poster_path")
    backdrop = row.get("still_path") or series.get("backdrop_path")
    return Media(
        id=f"tmdb:tv:{identifier}",
        kind="tv",
        title=f"{series['name']} · {suffix}",
        source=source("tmdb", identifier, "https://www.themoviedb.org" + url, fetched_at),
        external_ids={"tmdb": identifier},
        format="Episode" if episode is not None else "Season",
        facts=facts,
        description=row.get("overview"),
        release_date=row.get("air_date") or None,
        image_url=f"https://image.tmdb.org/t/p/w500{portrait}" if portrait else None,
        backdrop_url=f"https://image.tmdb.org/t/p/w1280{backdrop}" if backdrop else None,
        genres=[g["name"] for g in series.get("genres", [])],
        original_language=series.get("original_language"),
        origin_countries=series.get("origin_country", []),
    )


async def special_detail(http, provider, kind, identifier):
    if identifier.startswith("collection-"):
        number = int(identifier.split("-")[1])
        if provider == "tmdb":
            doc = await http.request(provider, f"/collection/{number}")
            if not doc:
                return None
            row = doc.data
            portrait = row.get("poster_path")
            backdrop = row.get("backdrop_path")
            return Media(
                id=f"tmdb:movie:{identifier}",
                kind="movie",
                title=row["name"],
                format="Collection",
                description=row.get("overview"),
                image_url=f"https://image.tmdb.org/t/p/w500{portrait}" if portrait else None,
                backdrop_url=f"https://image.tmdb.org/t/p/w1280{backdrop}" if backdrop else None,
                source=source(
                    provider, identifier, f"https://www.themoviedb.org/collection/{number}", doc.fetched_at
                ),
                external_ids={"tmdb": identifier},
            )
        doc = await http.request(
            provider, "/collections", content=f"fields name,slug; where id = {number}; limit 1;"
        )
        if not doc or not doc.data:
            return None
        row = doc.data[0]
        return Media(
            id=f"igdb:game:{identifier}",
            kind="game",
            title=row["name"],
            format="Collection",
            source=source(
                provider, identifier, f"https://www.igdb.com/collections/{row['slug']}", doc.fetched_at
            ),
            external_ids={"igdb": identifier},
        )
    series_id, remainder = identifier.split("-season-")
    parts = remainder.split("-episode-")
    season = int(parts[0])
    series = await http.request("tmdb", f"/tv/{series_id}")
    path = f"/tv/{series_id}/season/{season}"
    episode = int(parts[1]) if len(parts) > 1 else None
    doc = await http.request("tmdb", path + (f"/episode/{episode}" if episode is not None else ""))
    return tmdb_part(series.data, doc.data, season, doc.fetched_at, episode) if series and doc else None


async def listing(http, provider, kind, identifier, page=1):
    from .adapters.catalog import normalize_tmdb
    from .adapters.igdb import FIELDS, normalize

    http.require(provider)
    groups, parent, more = [], None, False
    if provider == "tmdb" and kind == "tv":
        series_id = identifier.split("-")[0]
        doc = await http.request(provider, f"/tv/{series_id}")
        if not doc:
            return None
        series = doc.data
        if "-season-" in identifier:
            parent = normalize_tmdb(series, "tv", doc.fetched_at)
            season = int(identifier.split("-season-")[1].split("-")[0])
            season_doc = await http.request(provider, f"/tv/{series_id}/season/{season}")
            rows = season_doc.data.get("episodes", []) if season_doc else []
            if "-episode-" in identifier and season_doc:
                parent = tmdb_part(series, season_doc.data, season, season_doc.fetched_at)
            groups.append(
                {
                    "title": "Episodes",
                    "results": [
                        tmdb_part(series, r, season, doc.fetched_at, r["episode_number"]) for r in rows
                    ],
                }
            )
        else:
            groups.append(
                {
                    "title": "Seasons",
                    "results": [
                        tmdb_part(series, r, r["season_number"], doc.fetched_at)
                        for r in sorted(
                            series.get("seasons", []),
                            key=lambda r: (r["season_number"] == 0, r["season_number"]),
                        )
                    ],
                }
            )
    elif provider == "tmdb":
        collection_id = (
            identifier.removeprefix("collection-") if identifier.startswith("collection-") else None
        )
        if collection_id is None:
            doc = await http.request(provider, f"/movie/{identifier}")
            collection_id = (doc.data.get("belongs_to_collection") or {}).get("id") if doc else None
        if collection_id:
            doc = await http.request(provider, f"/collection/{collection_id}")
            if doc:
                if not identifier.startswith("collection-"):
                    parent = await special_detail(http, provider, kind, f"collection-{collection_id}")
                groups.append(
                    {
                        "title": doc.data["name"],
                        "results": [
                            normalize_tmdb(r, "movie", doc.fetched_at)
                            for r in sorted(
                                doc.data.get("parts", []), key=lambda r: r.get("release_date") or "9999"
                            )
                            if not r.get("adult")
                        ],
                    }
                )
    else:
        if identifier.startswith("collection-"):
            number = int(identifier.split("-")[1])
            doc = await http.request(
                provider,
                "/games",
                content=f"fields {FIELDS}; where collections = ({number}); sort first_release_date asc; limit 50; offset {(page - 1) * 50};",
            )
            groups.append(
                {"title": "Games in this series", "results": [normalize(r, doc.fetched_at) for r in doc.data]}
            )
            more = len(doc.data) == 50
        else:
            fields = ",".join(
                f"{field}.{FIELDS.replace(',', ',' + field + '.')}"
                for field in ["dlcs", "expansions", "standalone_expansions", "parent_game", "bundles"]
            )
            doc = await http.request(
                provider,
                "/games",
                content=f"fields collections.name,collections.slug,{fields}; where id = {int(identifier)}; limit 1;",
            )
            if not doc or not doc.data:
                return None
            data = doc.data[0]
            collections = [
                Media(
                    id=f"igdb:game:collection-{r['id']}",
                    kind="game",
                    title=r["name"],
                    format="Collection",
                    external_ids={"igdb": f"collection-{r['id']}"},
                    source=source(
                        provider,
                        f"collection-{r['id']}",
                        f"https://www.igdb.com/collections/{r['slug']}",
                        doc.fetched_at,
                    ),
                )
                for r in data.get("collections", [])
            ]
            if collections:
                groups.append({"title": "Game series", "results": collections})
            if data.get("parent_game"):
                parent = normalize(data["parent_game"], doc.fetched_at)
            for field, title in [
                ("dlcs", "Downloadable content"),
                ("expansions", "Expansions"),
                ("standalone_expansions", "Standalone expansions"),
                ("bundles", "Bundles"),
            ]:
                if data.get(field):
                    groups.append(
                        {"title": title, "results": [normalize(r, doc.fetched_at) for r in data[field]]}
                    )
    for group in groups:
        group["results"] = list({m.id: m for m in group["results"]}.values())
    return {"parent": parent, "groups": groups, "page": page, "more": more}
