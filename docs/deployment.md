# Server deployment and webapp connection

1. Clone this repository on a Linux host with Docker Compose.
2. Copy `.env.example` to `.env`, restrict access (`chmod 600 .env`), and generate a random service key with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Set `METADATA_API_KEY` and the desired provider credentials. Never commit secrets.
3. Run `docker compose config --quiet`, then `docker compose up -d --build`.
4. Check `docker compose ps`, logs, and `curl --fail http://127.0.0.1:8000/healthz`.
5. Configure the host reverse proxy with a dedicated HTTPS hostname forwarding to loopback port 8000. For a containerized proxy use a private Docker network. Set connection/body limits and a roughly 30-second upstream deadline.
6. Verify authenticated `/v1/providers`, then known search/detail/enrichment requests. Readiness indicates configuration exists, not that credentials have been verified.

Use one replica and one worker. Cache, provider pacing and the 60 authenticated requests/minute quota are process-local. Add shared cache/distributed quotas before horizontal scaling. Restarts clear cooldowns; avoid restart loops while throttled. Default provider deadlines are 12 seconds including lock wait and token acquisition; detail plus optional enrichment can consume two deadlines.

The container runs non-root with a read-only filesystem, dropped capabilities, 32-request concurrency limit and no persistent database. Cache defaults are 900 seconds, 256 entries and 32 MB of raw response data; decoded objects require additional memory. Upstream bodies are capped at 1 MB. Environment variables configure cache and deadline limits.

Health reports process availability, independently of third-party outages. Logs include request IDs, status and duration. Do not enable HTTPX/HTTPCore debug or request logging: OMDb requires its credential in the query string. Keep proxy Authorization headers out of logs. Compose config output can contain secrets; use `--quiet` for validation.

## Connecting the webapp later

Store `METADATA_API_BASE_URL` and `METADATA_API_KEY` in the webapp backend's secret environment. These are suggested integration variable names, not existing webapp configuration. The browser calls its own backend; the backend adds the bearer key when calling this API. Never put service/provider keys in public frontend environment variables. CORS is intentionally disabled.

The backend should proxy search with explicit kind/provider filters, fetch detail after the user chooses a result, and optionally request `enrich=true`. Preserve provider IDs, source timestamps and attribution when saving metadata. Do not overwrite personal edits automatically. Display partial/unavailable states honestly. Escape descriptions or sanitize labeled HTML/markup before rendering.

Verify the connection with one search, one selected detail, one saved library item, and a simulated provider outage. Confirm that credentials are absent from browser requests, bundles and logs. The webapp itself has not been modified by this API implementation.

## Updates and rollback

Deploy reviewed revisions and record the commit/image digest. Rebuild with `docker compose up -d --build`, then check health and a known item. Roll back to the previous recorded revision/image if necessary. No database migration is required. Keep secrets separate from images and source backups. Rotate the service key in both backends together.

Run `python -m pytest -q` and lint checks before publishing. CI builds and starts the hardened container. Opt-in `python -m scripts.smoke` checks public providers; credentialed checks use `--provider tmdb`, `--provider igdb`, or `--provider omdb`. Run live checks from the deployment host before launch. No remote server access or deployment is assumed.
