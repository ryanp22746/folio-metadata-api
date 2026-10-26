import re

from ..models import Media
from .common import rating, safe_url, source
from .tmdb_details import detail_fields


class TMDB:
    kinds = ("movie", "tv")

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        doc = await self.http.request(
            "tmdb",
            f"/search/{kind}",
            params={"query": query, "page": page, "include_adult": "false", "language": "en-US"},
        )
        return [normalize_tmdb(x, kind, doc.fetched_at) for x in doc.data["results"]], page < doc.data.get(
            "total_pages", 1
        )

    async def detail(self, kind, identifier):
        doc = await self.http.request(
            "tmdb",
            f"/{kind}/{identifier}",
            params={
                "append_to_response": "external_ids,credits,images,alternative_titles,videos,watch/providers"
                + (",release_dates" if kind == "movie" else ""),
                "language": "en-US",
                "include_image_language": "en,null",
            },
        )
        return normalize_tmdb(doc.data, kind, doc.fetched_at) if doc else None


class VNDB:
    kinds = ("visual_novel",)

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        doc = await self.http.request(
            "vndb",
            "/vn",
            payload={
                "filters": ["search", "=", query],
                "fields": VN_FIELDS,
                "results": 20,
                "page": page,
                "sort": "searchrank",
            },
        )
        return [normalize_vn(x, doc.fetched_at) for x in doc.data["results"]], doc.data.get("more", False)

    async def detail(self, kind, identifier):
        doc = await self.http.request(
            "vndb",
            "/vn",
            payload={
                "filters": ["id", "=", identifier],
                "fields": VN_FIELDS + VN_DETAIL_FIELDS,
                "results": 1,
            },
        )
        return normalize_vn(doc.data["results"][0], doc.fetched_at) if doc and doc.data["results"] else None


VN_FIELDS = "title,alttitle,description,released,image.url,image.sexual,image.violence,titles.title,titles.official,rating,votecount,developers.name,length_minutes"
VN_DETAIL_FIELDS = (
    ",tags.name,tags.category,tags.rating,tags.spoiler,tags.lie,"
    "screenshots.url,screenshots.sexual,screenshots.violence,developers.id,"
    "staff.id,staff.name,staff.original,staff.role,staff.note,staff.eid,"
    "editions.eid,editions.name,editions.lang,"
    "va.staff.id,va.staff.name,va.staff.original,va.character.name"
)
VN_ROLES = {
    "scenario": "Writer / scenario",
    "director": "Director",
    "chardesign": "Character designer",
    "art": "Artist",
    "music": "Composer",
    "songs": "Vocals",
    "translator": "Translator",
    "editor": "Editor",
    "qa": "Quality assurance",
    "staff": "Other staff",
}


def vn_credits(data):
    """Preserve named staff, aliases and edition scope without inferring authorship."""
    editions = {row["eid"]: row for row in data.get("editions", []) if "eid" in row}
    credits, seen = [], set()

    def add(name, role, identifier, note=None, character=None):
        if not name:
            return
        key = (name, role, identifier, note, character)
        if key in seen:
            return
        seen.add(key)
        credits.append(
            {
                "name": name,
                "role": role,
                "note": note,
                "character": character,
                "url": f"https://vndb.org/{identifier}"
                if re.fullmatch(r"[sp][1-9][0-9]*", str(identifier))
                else None,
            }
        )

    for row in sorted(
        data.get("staff", []),
        key=lambda r: list(VN_ROLES).index(r["role"]) if r.get("role") in VN_ROLES else len(VN_ROLES),
    ):
        notes = [row.get("note")]
        if row.get("original") and row["original"] != row.get("name"):
            notes.append(row["original"])
        if row.get("eid") is not None:
            edition = editions.get(row["eid"], {})
            label = edition.get("name") or edition.get("lang") or "Edition-specific credit"
            notes.append(f"Edition: {label}")
        add(
            row.get("name"),
            VN_ROLES.get(row.get("role"), "Other staff"),
            row.get("id"),
            "; ".join(x for x in notes if x) or None,
        )
    for row in data.get("developers", []):
        add(row.get("name"), "Developer", row.get("id"))
    for row in data.get("va", []):
        staff = row.get("staff") or {}
        add(
            staff.get("name"),
            "Cast",
            staff.get("id"),
            staff.get("original"),
            (row.get("character") or {}).get("name"),
        )
    return credits[:250]


VN_GENRES = {
    "action",
    "adventure",
    "comedy",
    "drama",
    "fantasy",
    "horror",
    "mystery",
    "romance",
    "science fiction",
    "slice of life",
    "thriller",
    "suspense",
    "historical",
    "tragedy",
    "psychological horror",
    "psychological drama",
    "time travel",
    "supernatural",
    "post-apocalyptic",
}


def normalize_vn(data, fetched_at):
    identifier = data["id"]
    picture = data.get("image") or {}
    tags = list(
        dict.fromkeys(
            row["name"]
            for row in sorted(data.get("tags", []), key=lambda row: -(row.get("rating") or 0))
            if row.get("name")
            and row.get("category") == "cont"
            and row.get("spoiler") == 0
            and not row.get("lie")
        )
    )
    return Media(
        id=f"vndb:visual_novel:{identifier}",
        kind="visual_novel",
        genres=[tag for tag in tags if tag.casefold() in VN_GENRES],
        content_tags=[tag for tag in tags if tag.casefold() not in VN_GENRES][:40],
        rating_count=data.get("votecount"),
        ratings=rating(
            "VNDB Bayesian",
            data.get("rating"),
            100,
            source("vndb", identifier, f"https://vndb.org/{identifier}", fetched_at),
        ),
        creators=[x["name"] for x in data.get("developers", [])],
        credits=vn_credits(data),
        facts={"Typical length": f"{data['length_minutes']} minutes"} if data.get("length_minutes") else {},
        title=data["title"],
        original_title=data.get("alttitle"),
        alternative_titles=[
            x["title"] for x in data.get("titles", []) if x.get("official") and x.get("title")
        ][:20],
        description=data.get("description"),
        description_format="vndb_markup",
        release_date=data.get("released"),
        backdrop_url=next(
            (
                safe_url(x.get("url"))
                for x in data.get("screenshots", [])
                if x.get("sexual") == 0 and x.get("violence") == 0 and safe_url(x.get("url"))
            ),
            None,
        ),
        image_url=picture.get("url"),
        backdrop_urls=list(
            dict.fromkeys(
                safe_url(x.get("url"))
                for x in data.get("screenshots", [])
                if x.get("sexual") == 0 and x.get("violence") == 0 and safe_url(x.get("url"))
            )
        )[:30],
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
    logos = (data.get("images") or {}).get("logos") or []
    logos = [
        x
        for x in logos
        if x.get("iso_639_1") in ("en", None) and str(x.get("file_path", "")).endswith(".png")
    ]
    logos.sort(
        key=lambda x: (x.get("iso_639_1") == "en", x.get("vote_average", 0), x.get("width", 0)), reverse=True
    )
    logo = logos[0].get("file_path") if logos else None
    origin = source("tmdb", identifier, f"https://www.themoviedb.org/{kind}/{identifier}", fetched_at)
    return Media(
        original_language=data.get("original_language"),
        origin_countries=list(
            dict.fromkeys(
                data.get("origin_country", [])
                + [row["iso_3166_1"] for row in data.get("production_countries", []) if row.get("iso_3166_1")]
            )
        ),
        **detail_fields(data),
        facts={
            **{
                label: ", ".join(
                    x.get("english_name") or x.get("name", "")
                    for x in data[key]
                    if x.get("name") or x.get("english_name")
                )
                for key, label in [
                    ("production_companies", "Studios"),
                    ("production_countries", "Countries"),
                    ("spoken_languages", "Languages"),
                ]
                if data.get(key)
            },
            **{
                label: str(data[key]) + suffix
                for key, label, suffix in [
                    ("runtime", "Runtime", " minutes"),
                    ("number_of_seasons", "Seasons", ""),
                    ("number_of_episodes", "Episodes", ""),
                    ("status", "Release status", ""),
                    ("original_language", "Original language", ""),
                ]
                if data.get(key)
            },
        },
        creators=list(
            dict.fromkeys(
                [x["name"] for x in data.get("created_by", [])]
                + [
                    x["name"]
                    for x in (data.get("credits") or {}).get("crew", [])
                    if x.get("job") == "Director"
                ]
            )
        ),
        popularity=data.get("popularity"),
        rating_count=data.get("vote_count"),
        ratings=rating(
            "TMDB users", data.get("vote_average") if data.get("vote_count") else None, 10, origin
        ),
        logo_url=f"https://image.tmdb.org/t/p/w500{logo}" if logo else None,
        portrait_urls=[
            f"https://image.tmdb.org/t/p/w500{x['file_path']}"
            for x in (data.get("images") or {}).get("posters", [])
            if isinstance(x.get("file_path"), str) and x["file_path"].startswith("/")
        ][:40],
        backdrop_urls=[
            f"https://image.tmdb.org/t/p/w1280{x['file_path']}"
            for x in (data.get("images") or {}).get("backdrops", [])
            if isinstance(x.get("file_path"), str) and x["file_path"].startswith("/")
        ][:40],
        backdrop_url=f"https://image.tmdb.org/t/p/w1280{data['backdrop_path']}"
        if data.get("backdrop_path")
        else None,
        id=f"tmdb:{kind}:{identifier}",
        kind=kind,
        title=data["title"] if kind == "movie" else data["name"],
        original_title=data.get("original_title" if kind == "movie" else "original_name"),
        description=data.get("overview"),
        release_date=data.get("release_date" if kind == "movie" else "first_air_date") or None,
        image_url=f"https://image.tmdb.org/t/p/w500{data['poster_path']}"
        if data.get("poster_path")
        else None,
        genres=[g["name"] for g in data.get("genres", [])]
        or (["Animation"] if 16 in data.get("genre_ids", []) else []),
        external_ids=ids,
        source=source("tmdb", identifier, f"https://www.themoviedb.org/{kind}/{identifier}", fetched_at),
    )
