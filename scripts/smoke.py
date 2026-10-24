"""Opt-in live checks. Never runs during pytest or queries AniList unless explicitly enabled.

Run from repository root: python -m scripts.smoke
Pass --provider tmdb/igdb/omdb/anilist for credentialed/permitted checks.
"""

import argparse
import asyncio
import logging

import httpx

from folio_metadata.config import Settings
from folio_metadata.gateway import Gateway
from folio_metadata.transport import ProviderError


async def main(providers):
    config = Settings.from_env()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    failed = False
    async with httpx.AsyncClient(
        timeout=8, follow_redirects=False, headers={"User-Agent": "FolioMetadata/0.2"}
    ) as client:
        gateway = Gateway(client, config)
        examples = {
            "vndb": ("Ever17", "visual_novel"),
            "mangaupdates": ("Berserk", "manga"),
            "musicbrainz": ("Abbey Road", "album"),
            "tmdb": ("Star Wars", "movie"),
            "igdb": ("Portal", "game"),
            "anilist": ("Cowboy Bebop", "anime"),
        }
        for name in providers:
            try:
                if name in ("omdb", "steam"):
                    result = await gateway.enrich(name, "tt0076759" if name == "omdb" else "620")
                    if result is None:
                        raise ValueError("Expected known record")
                else:
                    query, kind = examples[name]
                    results, _ = await gateway.search(name, query, kind, 1)
                    if not results:
                        raise ValueError("Expected search results")
                    result = await gateway.detail(name, kind, results[0].source.id)
                    if result is None:
                        raise ValueError("Expected detail result")
                print(f"{name}: PASS (search/detail or enrichment)")
            except (
                ProviderError,
                httpx.HTTPError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                TimeoutError,
                asyncio.TimeoutError,
            ) as exc:
                # Never print exception messages: upstream URLs may contain credentials.
                print(f"{name}: FAIL ({type(exc).__name__})")
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider",
        action="append",
        choices=["vndb", "mangaupdates", "musicbrainz", "steam", "tmdb", "igdb", "omdb", "anilist"],
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.provider or ["vndb", "mangaupdates", "musicbrainz", "steam"])))
