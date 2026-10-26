from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["movie", "tv", "visual_novel", "anime", "manga", "game", "album", "track", "book"]
Provider = Literal[
    "spotify",
    "tmdb",
    "vndb",
    "anilist",
    "mangaupdates",
    "igdb",
    "musicbrainz",
    "apple",
    "omdb",
    "steam",
    "openlibrary",
    "jikan",
    "mal",
]


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


class Credit(BaseModel):
    name: str
    role: str
    character: str | None = None
    url: str | None = None
    note: str | None = None


class Release(BaseModel):
    date: str
    region: str = ""
    type: str = "Release"
    certification: str = ""
    note: str = ""


class WatchOffer(BaseModel):
    name: str
    type: Literal["Subscription", "Free", "Ads", "Rent", "Buy"]
    logo_url: str | None = None


class WatchRegion(BaseModel):
    url: str | None = None
    offers: list[WatchOffer] = Field(default_factory=list)


class MediaLink(BaseModel):
    label: str
    url: str


class RelatedMedia(BaseModel):
    provider: Provider
    kind: Kind
    id: str
    title: str
    relation: str


class Media(BaseModel):
    id: str
    kind: Kind
    title: str
    search_priority: float | None = None
    original_language: str | None = None
    origin_countries: list[str] = Field(default_factory=list)
    related_media: list[RelatedMedia] = Field(default_factory=list)
    facts: dict[str, str] = Field(default_factory=dict)
    popularity: float | None = None
    rating_count: int | None = None
    original_title: str | None = None
    alternative_titles: list[str] = Field(default_factory=list)
    credits: list[Credit] = Field(default_factory=list)
    releases: list[Release] = Field(default_factory=list)
    watch_regions: dict[str, WatchRegion] = Field(default_factory=dict)
    watch_status: Literal["unknown", "ok", "unavailable"] = "unknown"
    trailer_url: str | None = None
    media_links: list[MediaLink] = Field(default_factory=list)
    description: str | None = None
    description_format: Literal["text", "vndb_markup", "html"] = "text"
    release_date: str | None = None
    image_url: str | None = None
    logo_url: str | None = None
    backdrop_url: str | None = None
    portrait_urls: list[str] = Field(default_factory=list)
    backdrop_urls: list[str] = Field(default_factory=list)
    image_sexual: float | None = None
    image_violence: float | None = None
    genres: list[str] = Field(default_factory=list)
    content_tags: list[str] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    source: Source
    format: str | None = None
    creators: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    ratings: list[Rating] = Field(default_factory=list)
    enrichments: list[Enrichment] = Field(default_factory=list)
    enrichment_status: list[ProviderStatus] = Field(default_factory=list)


class SearchResponse(BaseModel):
    duplicate_groups: list[dict] = Field(default_factory=list)
    results: list[Media]
    providers: list[ProviderStatus]
    partial: bool
    page: int
    more: bool


class CreatorRef(BaseModel):
    provider: Literal[
        "mal_studio",
        "vndb",
        "tmdb",
        "mangaupdates",
        "musicbrainz",
        "openlibrary",
        "igdb",
        "tmdb_company",
        "apple",
        "spotify",
    ]
    id: str
    name: str
    url: str
    description: str | None = None
    image_url: str | None = None
    facts: dict[str, str] = Field(default_factory=dict)
    entity_links: list[str] = Field(default_factory=list)


class CreatorWorks(BaseModel):
    creator: CreatorRef
    results: list[Media]
    page: int
    more: bool


class AlbumTracks(BaseModel):
    title: str
    edition: str | None = None
    url: str
    results: list[Media]
    page: int
    more: bool
