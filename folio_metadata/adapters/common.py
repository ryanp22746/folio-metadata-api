import re
from urllib.parse import urlsplit

from ..models import Rating, Source


def source(provider, identifier, url, fetched_at):
    return Source(provider=provider, id=str(identifier), url=url, fetched_at=fetched_at)


def rating(label, value, scale, origin):
    return [] if value is None else [Rating(label=label, value=f"{value}/{scale}", source=origin)]


def safe_url(value):
    if not isinstance(value, str):
        return None
    if value.startswith("//"):
        value = "https:" + value
    parsed = urlsplit(value)
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username else None


def year(value):
    return str(value) if value and re.fullmatch(r"[12][0-9]{3}", str(value)) else None


def fuzzy_date(data):
    result = year(data.get("year"))
    if result and data.get("month"):
        result += f"-{data['month']:02d}"
        if data.get("day"):
            result += f"-{data['day']:02d}"
    return result
