"""Environment-only configuration; secrets never appear in API responses."""

import os

from pydantic import BaseModel, Field, SecretStr


class Settings(BaseModel):
    api_key: SecretStr = SecretStr("")
    mal_client_id: SecretStr = SecretStr("")
    spotify_client_id: SecretStr = SecretStr("")
    spotify_client_secret: SecretStr = SecretStr("")
    tmdb_token: SecretStr = SecretStr("")
    igdb_client_id: SecretStr = SecretStr("")
    igdb_client_secret: SecretStr = SecretStr("")
    omdb_api_key: SecretStr = SecretStr("")
    anilist_enabled: bool = False
    musicbrainz_contact: str = "https://github.com/ryanp22746/folio-metadata-api"
    cache_ttl: int = Field(default=900, ge=0, le=86400)
    cache_entries: int = Field(default=256, ge=1, le=2048)
    provider_timeout: float = Field(default=12, gt=0, le=60)

    @classmethod
    def from_env(cls):
        return cls(
            api_key=os.getenv("METADATA_API_KEY", ""),
            mal_client_id=os.getenv("MAL_CLIENT_ID", ""),
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", ""),
            spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", ""),
            tmdb_token=os.getenv("TMDB_READ_TOKEN", ""),
            igdb_client_id=os.getenv("IGDB_CLIENT_ID", ""),
            igdb_client_secret=os.getenv("IGDB_CLIENT_SECRET", ""),
            omdb_api_key=os.getenv("OMDB_API_KEY", ""),
            anilist_enabled=os.getenv("ANILIST_ENABLED", "false"),
            musicbrainz_contact=os.getenv(
                "MUSICBRAINZ_CONTACT", cls.model_fields["musicbrainz_contact"].default
            ),
            cache_ttl=os.getenv("CACHE_TTL_SECONDS", "900"),
            cache_entries=os.getenv("CACHE_MAX_ENTRIES", "256"),
            provider_timeout=os.getenv("PROVIDER_TIMEOUT_SECONDS", "12"),
        )
