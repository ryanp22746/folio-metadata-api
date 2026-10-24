from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["movie", "tv", "visual_novel", "anime", "manga", "game", "album", "track"]
Provider = Literal["tmdb", "vndb", "anilist", "mangaupdates", "igdb", "musicbrainz", "omdb", "steam"]


class Source(BaseModel):
    provider: Provider
    id: str
    url: str
    fetched_at: str


class Rating(BaseModel):
    label: str
    value: str
    # Preserve original scales, populations and attribution; never average different scores.
    source: Source


class ReviewSummary(BaseModel):
    positive: int = Field(ge=0)
    negative: int = Field(ge=0)
    total: int = Field(ge=0)
    positive_percent: float | None = None
    label: str | None = None
    population: str = "all languages; all purchase types; off-topic activity excluded"


class Enrichment(BaseModel):
    source: Source
    ratings: list[Rating] = Field(default_factory=list)
    reviews: ReviewSummary | None = None


class ProviderStatus(BaseModel):
    provider: Provider
    status: Literal["ok", "unavailable", "not_configured", "disabled", "not_found"]
    kind: Kind | None = None


class ProviderInfo(BaseModel):
    provider: Provider
    kinds: list[Kind]
    capabilities: list[Literal["search", "detail", "enrich"]]
    status: Literal["ready", "not_configured", "disabled"]
    required_configuration: list[str] = Field(default_factory=list)
    documentation: str


class Media(BaseModel):
    id: str
    kind: Kind
    title: str
    original_title: str | None = None
    description: str | None = None
    description_format: Literal["text", "vndb_markup", "html"] = "text"
    release_date: str | None = None
    image_url: str | None = None
    image_sexual: float | None = None
    image_violence: float | None = None
    genres: list[str] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    source: Source
    format: str | None = None
    creators: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    ratings: list[Rating] = Field(default_factory=list)
    enrichments: list[Enrichment] = Field(default_factory=list)
    enrichment_status: list[ProviderStatus] = Field(default_factory=list)


class SearchResponse(BaseModel):
    results: list[Media]
    providers: list[ProviderStatus]
    partial: bool
    page: int
    more: bool
