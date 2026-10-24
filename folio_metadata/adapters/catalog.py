from ..models import Media
from .common import rating, source


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
            params={"append_to_response": "external_ids,credits", "language": "en-US"},
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
            "vndb", "/vn", payload={"filters": ["id", "=", identifier], "fields": VN_FIELDS, "results": 1}
        )
        return normalize_vn(doc.data["results"][0], doc.fetched_at) if doc and doc.data["results"] else None


VN_FIELDS = "title,alttitle,description,released,image.url,image.sexual,image.violence,rating,votecount,developers.name,length_minutes"


def normalize_vn(data, fetched_at):
    identifier = data["id"]
    picture = data.get("image") or {}
    return Media(
        id=f"vndb:visual_novel:{identifier}",
        kind="visual_novel",
        rating_count=data.get("votecount"),
        ratings=rating(
            "VNDB Bayesian",
            data.get("rating"),
            100,
            source("vndb", identifier, f"https://vndb.org/{identifier}", fetched_at),
        ),
        creators=[x["name"] for x in data.get("developers", [])],
        facts={"Typical length": f"{data['length_minutes']} minutes"} if data.get("length_minutes") else {},
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
    origin = source("tmdb", identifier, f"https://www.themoviedb.org/{kind}/{identifier}", fetched_at)
    return Media(
        facts={
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
