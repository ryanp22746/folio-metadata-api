from typing import Literal

from pydantic import BaseModel, Field

Kind = Literal["movie", "tv", "visual_novel"]
Provider = Literal["tmdb", "vndb"]


class Source(BaseModel):
    provider: Provider
    id: str
    url: str
    fetched_at: str


class Media(BaseModel):
    id: str
    kind: Kind
    title: str
    original_title: str | None = None
    description: str | None = None
    description_format: Literal["text", "vndb_markup"] = "text"
    release_date: str | None = None
    image_url: str | None = None
    image_sexual: float | None = None
    image_violence: float | None = None
    genres: list[str] = Field(default_factory=list)
    external_ids: dict[str, str] = Field(default_factory=dict)
    source: Source


class ProviderStatus(BaseModel):
    provider: Provider
    status: Literal["ok", "unavailable", "not_configured"]


class SearchResponse(BaseModel):
    results: list[Media]
    providers: list[ProviderStatus]
    partial: bool
    page: int
    more: bool
