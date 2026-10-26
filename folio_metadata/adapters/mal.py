"""Official MyAnimeList public catalog, authenticated by a server-side Client ID."""

from ..models import Media
from .common import rating, safe_url, source

FIELDS = (
    "alternative_titles,start_date,end_date,synopsis,mean,num_scoring_users,genres,"
    "media_type,status,num_episodes,studios,average_episode_duration,rating,start_season,source"
)


class MyAnimeList:
    kinds = ("anime",)

    def __init__(self, transport):
        self.http = transport

    async def search(self, query, kind, page):
        doc = await self.http.request(
            "mal",
            "/anime",
            params={"q": query, "limit": 20, "offset": (page - 1) * 20, "fields": FIELDS, "nsfw": "false"},
        )
        return [normalize(row["node"], doc.fetched_at) for row in doc.data["data"]], bool(
            doc.data.get("paging", {}).get("next")
        )

    async def detail(self, kind, identifier):
        doc = await self.http.request(
            "mal",
            f"/anime/{identifier}",
            params={"fields": FIELDS + ",pictures,related_anime", "nsfw": "false"},
        )
        return normalize(doc.data, doc.fetched_at) if doc else None


def normalize(data, fetched_at):
    identifier = str(data["id"])
    origin = source("mal", identifier, f"https://myanimelist.net/anime/{identifier}", fetched_at)
    titles = data.get("alternative_titles") or {}
    picture = data.get("main_picture") or {}
    studios = [row["name"] for row in data.get("studios", []) if row.get("name")]
    facts = {}
    for label, field in [
        ("Episodes", "num_episodes"),
        ("Status", "status"),
        ("Source material", "source"),
        ("Age rating", "rating"),
    ]:
        if data.get(field) is not None:
            facts[label] = str(data[field]).replace("_", " ")
    if data.get("average_episode_duration"):
        facts["Episode duration"] = f"{round(data['average_episode_duration'] / 60)} minutes"
    season = data.get("start_season") or {}
    if season.get("season") and season.get("year"):
        facts["Season"] = f"{season['season']} {season['year']}"
    return Media(
        id=f"mal:anime:{identifier}",
        kind="anime",
        title=titles.get("en") or data["title"],
        original_title=titles.get("ja"),
        alternative_titles=[value for value in [data["title"], *titles.get("synonyms", [])] if value],
        release_date=data.get("start_date"),
        description=data.get("synopsis"),
        image_url=safe_url(picture.get("large") or picture.get("medium")),
        portrait_urls=[
            url
            for row in data.get("pictures", [])
            if (url := safe_url(row.get("large") or row.get("medium")))
        ],
        genres=[row["name"] for row in data.get("genres", []) if row.get("name")],
        creators=studios,
        credits=[
            {
                "name": row["name"],
                "role": "Studio",
                "url": f"https://myanimelist.net/anime/producer/{row['id']}"
                if isinstance(row.get("id"), int) and row["id"] > 0
                else None,
            }
            for row in data.get("studios", [])
            if row.get("name")
        ],
        related_media=[
            {
                "provider": "mal",
                "kind": "anime",
                "id": str(row["node"]["id"]),
                "title": row["node"]["title"],
                "relation": row.get("relation_type", "related"),
            }
            for row in data.get("related_anime", [])
            if isinstance(row.get("node", {}).get("id"), int) and row["node"].get("title")
        ],
        facts=facts,
        format=data.get("media_type"),
        external_ids={"myanimelist": identifier},
        rating_count=data.get("num_scoring_users"),
        ratings=rating("MyAnimeList users", data.get("mean"), 10, origin),
        source=origin,
    )
