"""Detail-only credits, releases and attributed JustWatch availability via TMDB."""

import re

from .common import safe_url


def detail_fields(data):
    credits = []
    people = data.get("credits") or {}
    priority = [
        "Director",
        "Screenplay",
        "Writer",
        "Story",
        "Novel",
        "Original Story",
        "Original Film Writer",
        "Comic Book",
        "Characters",
        "Producer",
        "Executive Producer",
        "Director of Photography",
        "Original Music Composer",
        "Editor",
        "Production Design",
        "Art Direction",
        "Costume Design",
        "Set Decoration",
    ]
    for person in data.get("created_by", []):
        if person.get("name"):
            identifier = person.get("id")
            credits.append(
                {
                    "name": person["name"],
                    "role": "Series creator",
                    "url": f"https://www.themoviedb.org/person/{identifier}"
                    if isinstance(identifier, int) and identifier > 0
                    else None,
                }
            )
    for group in ("cast", "crew"):
        rows = people.get(group, [])
        if group == "crew":
            rows = sorted(
                rows,
                key=lambda x: priority.index(x.get("job")) if x.get("job") in priority else len(priority),
            )
        for person in rows[:150]:
            if not person.get("name"):
                continue
            identifier = person.get("id")
            credits.append(
                {
                    "name": person["name"],
                    "role": "Cast" if group == "cast" else person.get("job") or "Crew",
                    "character": person.get("character") if group == "cast" else None,
                    "url": f"https://www.themoviedb.org/person/{identifier}"
                    if isinstance(identifier, int) and identifier > 0
                    else None,
                }
            )
    for company in data.get("production_companies", []):
        if company.get("name"):
            identifier = company.get("id")
            credits.append(
                {
                    "name": company["name"],
                    "role": "Studio",
                    "url": f"https://www.themoviedb.org/company/{identifier}"
                    if isinstance(identifier, int) and identifier > 0
                    else None,
                }
            )
    release_types = {
        1: "Premiere",
        2: "Theatrical (limited)",
        3: "Theatrical",
        4: "Digital",
        5: "Physical",
        6: "TV",
    }
    releases = []
    for country in (data.get("release_dates") or {}).get("results", []):
        for release in country.get("release_dates", []):
            date = str(release.get("release_date", ""))[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                releases.append(
                    {
                        "date": date,
                        "region": country.get("iso_3166_1", ""),
                        "type": release_types.get(release.get("type"), "Release"),
                        "certification": release.get("certification") or "",
                        "note": release.get("note") or "",
                    }
                )
    watch = data.get("watch/providers")
    regions = {}
    for country, result in ((watch or {}).get("results") or {}).items():
        if not re.fullmatch(r"[A-Z]{2}", country):
            continue
        offers, seen = [], set()
        for key, label in [
            ("flatrate", "Subscription"),
            ("free", "Free"),
            ("ads", "Ads"),
            ("rent", "Rent"),
            ("buy", "Buy"),
        ]:
            for provider in result.get(key, [])[:50]:
                name = provider.get("provider_name")
                if not name or (name, label) in seen:
                    continue
                seen.add((name, label))
                logo = provider.get("logo_path") or ""
                offers.append(
                    {
                        "name": name,
                        "type": label,
                        "logo_url": f"https://image.tmdb.org/t/p/w92{logo}"
                        if re.fullmatch(r"/[\w.-]+", logo)
                        else None,
                    }
                )
        regions[country] = {"url": safe_url(result.get("link")), "offers": offers}
    trailer = next(
        (
            v
            for v in (data.get("videos") or {}).get("results", [])
            if v.get("site") == "YouTube"
            and v.get("type") == "Trailer"
            and v.get("official")
            and re.fullmatch(r"[\w-]{11}", v.get("key", ""))
        ),
        None,
    )
    return {
        "credits": credits,
        "releases": sorted(releases, key=lambda r: (r["date"], r["region"], r["type"]))[:500],
        "watch_regions": regions,
        "watch_status": "unknown"
        if watch is None
        else "ok"
        if isinstance(watch.get("results"), dict)
        else "unavailable",
        "trailer_url": f"https://www.youtube.com/watch?v={trailer['key']}" if trailer else None,
        "alternative_titles": list(
            dict.fromkeys(
                x["title"]
                for x in (data.get("alternative_titles") or {}).get(
                    "titles", (data.get("alternative_titles") or {}).get("results", [])
                )
                if x.get("title")
            )
        )[:80],
    }
