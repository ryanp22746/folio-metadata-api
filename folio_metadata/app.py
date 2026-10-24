import logging
import os
import re
import secrets
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from .models import Kind, Media, Provider, ProviderStatus, SearchResponse
from .providers import Gateway, NotConfigured, ProviderError

log = logging.getLogger("folio")
security = HTTPBearer(auto_error=False)


def create_app(api_key=None, tmdb_token=None, transport=None):
    key = api_key if api_key is not None else os.getenv("METADATA_API_KEY", "")
    token = tmdb_token if tmdb_token is not None else os.getenv("TMDB_READ_TOKEN", "")

    @asynccontextmanager
    async def lifespan(app):
        if len(key) < 32:
            raise RuntimeError("METADATA_API_KEY must contain at least 32 characters")
        async with httpx.AsyncClient(
            timeout=8,
            follow_redirects=False,
            transport=transport,
            limits=httpx.Limits(max_connections=10),
            headers={"User-Agent": "FolioMetadata/0.1"},
        ) as client:
            app.state.gateway = Gateway(client, token)
            yield

    app = FastAPI(title="Folio Metadata API", version="0.1.0", lifespan=lifespan)
    requests = deque()

    @app.middleware("http")
    async def observe(request: Request, call_next):
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        log.info(
            "request_id=%s method=%s status=%s duration_ms=%.0f",
            request_id,
            request.method,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    async def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
        if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), key.encode()):
            raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})
        now = time.monotonic()
        while requests and requests[0] <= now - 60:
            requests.popleft()
        if len(requests) >= 60:
            raise HTTPException(429, "Request limit exceeded", headers={"Retry-After": "60"})
        requests.append(now)

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/v1/search", response_model=SearchResponse, dependencies=[Depends(authorize)])
    async def search(
        request: Request,
        q: str = Query(min_length=1, max_length=200),
        kind: Kind | None = None,
        page: int = Query(default=1, ge=1, le=100),
    ):
        if not q.strip():
            raise HTTPException(422, "Query must not be blank")
        targets = [("vndb", "visual_novel"), ("tmdb", "movie"), ("tmdb", "tv")]
        targets = [(p, k) for p, k in targets if kind is None or k == kind]

        async def run(provider, selected_kind):
            try:
                # Movie and TV share a rate budget; combine them sequentially below.
                result, more = await request.app.state.gateway.search(
                    provider, q.strip(), selected_kind, page
                )
                return result, more, "ok"
            except NotConfigured:
                return [], False, "not_configured"
            except (ProviderError, KeyError, TypeError, ValueError, AttributeError, ValidationError):
                return [], False, "unavailable"

        results, statuses, more = [], {}, False
        for provider, selected_kind in targets:
            items, has_more, status = await run(provider, selected_kind)
            results.extend(items)
            more = more or has_more
            if statuses.get(provider) != "unavailable":
                statuses[provider] = status
        provider_states = [ProviderStatus(provider=p, status=s) for p, s in statuses.items()]
        if not results and all(s != "ok" for s in statuses.values()):
            raise HTTPException(
                503,
                {
                    "message": "No requested provider available",
                    "providers": [s.model_dump() for s in provider_states],
                },
            )
        return SearchResponse(
            results=results,
            providers=provider_states,
            partial=any(s != "ok" for s in statuses.values()),
            page=page,
            more=more,
        )

    @app.get(
        "/v1/items/{provider}/{kind}/{identifier}", response_model=Media, dependencies=[Depends(authorize)]
    )
    async def detail(request: Request, provider: Provider, kind: Kind, identifier: str):
        valid = (
            provider == "vndb" and kind == "visual_novel" and re.fullmatch(r"v[1-9][0-9]{0,9}", identifier)
        ) or (provider == "tmdb" and kind in ("movie", "tv") and re.fullmatch(r"[1-9][0-9]{0,9}", identifier))
        if not valid:
            raise HTTPException(422, "Invalid provider, kind or identifier combination")
        try:
            result = await request.app.state.gateway.detail(provider, kind, identifier)
        except (ProviderError, KeyError, TypeError, ValueError, AttributeError, ValidationError):
            raise HTTPException(503, "Provider unavailable") from None
        if result is None:
            raise HTTPException(404, "Item not found")
        return result

    return app


app = create_app()
