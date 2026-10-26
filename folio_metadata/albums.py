"""Track listings for source-qualified albums; editions and recordings retain their IDs."""

from .adapters.apple import normalize as apple_media
from .adapters.musicbrainz import normalize as brainz_media
from .adapters.spotify import normalize as spotify_media
from .models import AlbumTracks


def duration(milliseconds):
    seconds = max(0, int(milliseconds or 0)) // 1000
    return f"{seconds // 60}:{seconds % 60:02}"


async def tracks(http, provider, identifier, page):
    http.require(provider)
    edition = None
    if provider == "spotify":
        album = await http.request(provider, f"/albums/{identifier}", params={"market": "US"})
        if not album:
            return None
        doc = await http.request(
            provider,
            f"/albums/{identifier}/tracks",
            params={"market": "US", "limit": 50, "offset": (page - 1) * 50},
        )
        rows = [
            spotify_media({**row, "album": album.data}, "track", doc.fetched_at)
            for row in doc.data.get("items", [])
            if row and row.get("id")
        ]
        title, url = album.data["name"], f"https://open.spotify.com/album/{identifier}"
        more = bool(doc.data.get("next"))
    elif provider == "apple":
        doc = await http.request(
            provider, "/lookup", params={"id": identifier, "entity": "song", "limit": 200, "country": "US"}
        )
        data = doc.data.get("results", []) if doc else []
        album = next(
            (
                r
                for r in data
                if r.get("wrapperType") == "collection" and str(r.get("collectionId")) == identifier
            ),
            None,
        )
        if not album:
            return None
        songs = [r for r in data if r.get("kind") == "song" and str(r.get("collectionId")) == identifier]
        rows = [apple_media(r, doc.fetched_at) for r in songs[(page - 1) * 50 : page * 50]]
        title = album["collectionName"]
        url = f"https://music.apple.com/us/album/{identifier}"
        more = len(songs) > page * 50
    else:
        group = await http.request(
            provider, f"/release-group/{identifier}", params={"fmt": "json", "inc": "releases"}
        )
        if not group:
            return None
        releases = sorted(
            [r for r in group.data.get("releases", []) if r.get("status") == "Official" and r.get("id")],
            key=lambda r: (r.get("date") or "9999", r["id"]),
        )
        if not releases:
            return AlbumTracks(
                title=group.data["title"],
                url=f"https://musicbrainz.org/release-group/{identifier}",
                results=[],
                page=page,
                more=False,
            )
        release = await http.request(
            provider,
            f"/release/{releases[0]['id']}",
            params={"fmt": "json", "inc": "recordings+artist-credits+isrcs"},
        )
        rows = []
        for disc in release.data.get("media", []):
            for row in disc.get("tracks", []):
                recording = row.get("recording") or {}
                if not recording.get("id"):
                    continue
                media = brainz_media(
                    {
                        **recording,
                        "title": row.get("title") or recording["title"],
                        "artist-credit": row.get("artist-credit")
                        or recording.get("artist-credit")
                        or release.data.get("artist-credit", []),
                        "first-release-date": group.data.get("first-release-date"),
                        "releases": [{"id": release.data["id"]}],
                    },
                    "track",
                    release.fetched_at,
                )
                media.facts.update(
                    {
                        "Track number": str(row.get("position") or row.get("number") or ""),
                        "Disc": str(disc.get("position") or 1),
                        "Album": group.data["title"],
                    }
                )
                if row.get("length") or recording.get("length"):
                    media.facts["Duration"] = duration(row.get("length") or recording["length"])
                rows.append(media)
        title, url = group.data["title"], f"https://musicbrainz.org/release/{release.data['id']}"
        edition = " · ".join(
            str(x)
            for x in [release.data.get("title"), release.data.get("date"), release.data.get("country")]
            if x
        )
        more, rows = len(rows) > page * 50, rows[(page - 1) * 50 : page * 50]
    return AlbumTracks(title=title, edition=edition, url=url, results=rows, page=page, more=more)
