import json

from ..models import Enrichment, Rating, ReviewSummary
from ..transport import ProviderError
from .common import source


class OMDb:
    kinds = ("movie", "tv")

    def __init__(self, transport):
        self.http = transport

    async def enrich(self, identifier):
        doc = await self.http.request("omdb", "/", params={"i": identifier, "r": "json"})
        if not doc:
            return None
        data = doc.data
        if data.get("Response") == "False":
            if data.get("Error") in ("Movie not found!", "Series not found!"):
                return None
            raise ProviderError()
        if data.get("Response") != "True" or data.get("imdbID") != identifier:
            raise ProviderError()
        origin = source("omdb", identifier, f"https://www.imdb.com/title/{identifier}/", doc.fetched_at)
        ratings = [
            Rating(label=r["Source"], value=r["Value"], source=origin)
            for r in data.get("Ratings") or []
            if r.get("Value") not in (None, "N/A", "")
        ]
        return Enrichment(source=origin, ratings=ratings)


class Steam:
    kinds = ("game",)

    def __init__(self, transport):
        self.http = transport

    async def enrich(self, identifier):
        doc = await self.http.request(
            "steam",
            "/IUserReviewsService/GetAppReviews/v1/",
            params={
                "input_json": json.dumps(
                    {
                        "appid": int(identifier),
                        "languages": ["all"],
                        "review_type": 0,
                        "purchase_type": 1,
                        "filter": 1,
                        "num_per_page": 1,
                        "filter_offtopic_activity": True,
                        "display_language": "english",
                    }
                )
            },
        )
        if not doc:
            return None
        summary = doc.data["response"]["query_summary"]
        positive = int(summary.get("total_positive", 0))
        negative = int(summary.get("total_negative", 0))
        total = int(summary["total_reviews"])
        if positive + negative != total:
            raise ProviderError()
        origin = source(
            "steam", identifier, f"https://store.steampowered.com/app/{identifier}/", doc.fetched_at
        )
        reviews = ReviewSummary(
            positive=positive,
            negative=negative,
            total=total,
            positive_percent=round(positive / total * 100, 2) if total else None,
            label=summary.get("review_score_desc"),
        )
        return Enrichment(source=origin, reviews=reviews)
