import asyncio
import logging
import secrets
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from .gateway import Gateway
from .identity import duplicate_groups
from .models import Enrichment, Kind, Media, Provider, ProviderInfo, ProviderStatus, SearchResponse
from .transport import Disabled, NotConfigured, ProviderError

log = logging.getLogger("uvicorn.error")
security = HTTPBearer(auto_error=False)
UPSTREAM_ERRORS = (
    ProviderError,
    KeyError,
    TypeError,
    ValueError,
    AttributeError,
    OverflowError,
    TimeoutError,
    asyncio.TimeoutError,
)


def create_app(api_key=None, tmdb_token=None, transport=None, *, settings=None):
    config = settings or Settings.from_env()
    updates = {}
    if api_key is not None:
        updates["api_key"] = api_key
    if tmdb_token is not None:
        updates["tmdb_token"] = tmdb_token
    config = Settings(**(config.model_dump() | updates))
    key = config.api_key.get_secret_value()

    @asynccontextmanager
    async def lifespan(app):
        if len(key) < 32:
            raise RuntimeError("METADATA_API_KEY must contain at least 32 characters")
        # httpx INFO request logs include OMDb's required query-string credential.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        async with httpx.AsyncClient(
            timeout=8,
            follow_redirects=False,
            transport=transport,
            limits=httpx.Limits(max_connections=16),
            headers={"User-Agent": "FolioMetadata/0.2"},
        ) as client:
            app.state.gateway = Gateway(client, config)
            yield

    app = FastAPI(title="Folio Metadata API", version="0.2.0", lifespan=lifespan)
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

    @app.get("/v1/providers", response_model=list[ProviderInfo], dependencies=[Depends(authorize)])
    async def providers(request: Request):
        return request.app.state.gateway.catalog()

    @app.get("/v1/search", response_model=SearchResponse, dependencies=[Depends(authorize)])
    async def search(
        request: Request,
        q: str = Query(min_length=1, max_length=200),
        kind: Kind | None = None,
        page: int = Query(default=1, ge=1, le=100),
        provider: Provider | None = None,
    ):
        if not q.strip() or any(ord(c) < 32 for c in q):
            raise HTTPException(422, "Query must contain text and no control characters")
        gateway = request.app.state.gateway
        targets = gateway.targets(kind, provider)
        if not targets:
            raise HTTPException(422, "Provider does not support search for this kind")

        async def run(name, selected_kind):
            status = "ok"
            items, more = [], False
            try:
                items, more = await gateway.search(name, q.strip(), selected_kind, page)
            except Disabled:
                status = "disabled"
            except NotConfigured:
                status = "not_configured"
            except UPSTREAM_ERRORS:
                status = "unavailable"
            return items, more, ProviderStatus(provider=name, kind=selected_kind, status=status)

        # Independent providers run concurrently; transport locks enforce each provider's budget.
        outcomes = await asyncio.gather(*(run(p, k) for p, k in targets))
        states = [result[2] for result in outcomes]
        if all(state.status != "ok" for state in states):
            raise HTTPException(
                503,
                {"message": "No requested provider available", "providers": [s.model_dump() for s in states]},
            )
        return SearchResponse(
            duplicate_groups=duplicate_groups([item for result in outcomes for item in result[0]]),
            results=[item for result in outcomes for item in result[0]],
            providers=states,
            partial=any(s.status != "ok" for s in states),
            page=page,
            more=any(result[1] for result in outcomes),
        )

    async def load_enrichment(gateway, provider, identifier):
        try:
            result = await gateway.enrich(provider, identifier)
            return result, ProviderStatus(provider=provider, status="ok" if result else "not_found")
        except Disabled:
            return None, ProviderStatus(provider=provider, status="disabled")
        except NotConfigured:
            return None, ProviderStatus(provider=provider, status="not_configured")
        except UPSTREAM_ERRORS:
            return None, ProviderStatus(provider=provider, status="unavailable")

    @app.get(
        "/v1/enrich/{provider}/{identifier}", response_model=Enrichment, dependencies=[Depends(authorize)]
    )
    async def enrich(request: Request, provider: Literal["omdb", "steam"], identifier: str):
        gateway = request.app.state.gateway
        kind = "movie" if provider == "omdb" else "game"
        if not gateway.valid(provider, kind, identifier, enrichment=True):
            raise HTTPException(422, "Invalid enrichment identifier")
        result, status = await load_enrichment(gateway, provider, identifier)
        if result is None:
            raise HTTPException(404 if status.status == "not_found" else 503, status.model_dump())
        return result

    @app.get(
        "/v1/items/{provider}/{kind}/{identifier}", response_model=Media, dependencies=[Depends(authorize)]
    )
    async def detail(request: Request, provider: Provider, kind: Kind, identifier: str, enrich: bool = False):
        gateway = request.app.state.gateway
        if not gateway.valid(provider, kind, identifier):
            raise HTTPException(422, "Invalid provider, kind or identifier combination")
        try:
            result = await gateway.detail(provider, kind, identifier)
        except Disabled:
            raise HTTPException(503, {"provider": provider, "status": "disabled"}) from None
        except NotConfigured:
            raise HTTPException(503, {"provider": provider, "status": "not_configured"}) from None
        except UPSTREAM_ERRORS:
            raise HTTPException(503, {"provider": provider, "status": "unavailable"}) from None
        if result is None:
            raise HTTPException(404, "Item not found")
        # A provider must return the exact selected record, never a silent alternate match.
        if result.source.id.lower() != identifier.lower() or result.kind != kind:
            raise HTTPException(503, "Provider returned a mismatched record")
        if enrich:
            target = None
            if provider == "tmdb" and result.external_ids.get("imdb"):
                target = ("omdb", result.external_ids["imdb"])
            elif provider == "igdb" and result.external_ids.get("steam"):
                target = ("steam", result.external_ids["steam"])
            if target:
                name, external_id = target
                if gateway.valid(name, kind, external_id, enrichment=True):
                    extra, state = await load_enrichment(gateway, name, external_id)
                    result.enrichment_status.append(state)
                    if extra:
                        result.enrichments.append(extra)
        return result

    return app


app = create_app()
