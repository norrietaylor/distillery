"""Webhook REST endpoints for scheduled Distillery operations.

Provides a Starlette sub-application with POST endpoints for ``/poll``,
``/rescore``, and ``/maintenance``.  Authentication is handled via a
bearer token verified with constant-time comparison.  Per-endpoint
cooldowns are persisted in DuckDB to prevent runaway scheduling.

The webhook app is mounted alongside the MCP server at ``/api`` by
:mod:`distillery.mcp.__main__` when HTTP transport is active and a
webhook secret is configured.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from distillery.config import DistilleryConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default cooldown intervals (seconds)
# ---------------------------------------------------------------------------

_COOLDOWN_SECONDS: dict[str, int] = {
    "poll": 300,  # 5 minutes
    "rescore": 3600,  # 1 hour
    "maintenance": 21600,  # 6 hours
}

# Per-endpoint locks to serialize dispatch and prevent TOCTOU races on
# cooldown checks.  Created lazily in the app factory.
_endpoint_locks: dict[str, asyncio.Lock] = {}

# Lock to serialize cold-start store initialisation so that concurrent
# first-hit requests (e.g. workflow_dispatch "all") don't each create a
# separate DuckDBStore.
_init_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Store initialisation helper
# ---------------------------------------------------------------------------


async def _ensure_store(
    shared_state: dict[str, Any],
    config: DistilleryConfig,
) -> dict[str, Any]:
    """Ensure the shared store, config, and embedding provider are initialised.

    When a webhook request arrives before any MCP client has connected the
    shared-state dict may be empty.  This function replicates the
    initialisation logic from the MCP lifespan so that webhook handlers
    always have a valid store.

    A module-level :data:`_init_lock` serialises entry so that concurrent
    first-hit requests (e.g. the ``operation: all`` workflow dispatch)
    cannot each create a separate ``DuckDBStore``.

    Args:
        shared_state: The mutable shared-state dict (same object passed to
            the MCP lifespan).
        config: The loaded Distillery configuration.

    Returns:
        The populated shared-state dict.
    """
    if shared_state:
        return shared_state

    async with _init_lock:
        # Double-check after acquiring the lock.
        if shared_state:
            return shared_state

        logger.info("Webhook: initialising store (no MCP client connected yet)")

        from distillery.mcp.server import _create_embedding_provider, _normalize_db_path

        embedding_provider = _create_embedding_provider(config)
        db_path = _normalize_db_path(config.storage.database_path)

        # Apply MotherDuck token from the configured env var name if set.
        if db_path.startswith("md:"):
            token = os.environ.get(config.storage.motherduck_token_env)
            if token:
                os.environ["MOTHERDUCK_TOKEN"] = token
            else:
                logger.warning(
                    "motherduck_token_env is set to %r but the environment variable is not set",
                    config.storage.motherduck_token_env,
                )

        from distillery.store.duckdb import DuckDBStore

        store = DuckDBStore(
            db_path=db_path,
            embedding_provider=embedding_provider,
            s3_region=config.storage.s3_region,
            s3_endpoint=config.storage.s3_endpoint,
        )
        await store.initialize()

        # Seed YAML feed sources into DB exactly once.
        if await store.get_metadata("feeds_seeded") != "true":
            for source in config.feeds.sources:
                with contextlib.suppress(ValueError):
                    await store.add_feed_source(
                        url=source.url,
                        source_type=source.source_type,
                        label=source.label,
                        poll_interval_minutes=source.poll_interval_minutes,
                        trust_weight=source.trust_weight,
                    )
            await store.set_metadata("feeds_seeded", "true")

        shared_state["store"] = store
        shared_state["config"] = config
        shared_state["embedding_provider"] = embedding_provider

        logger.info(
            "Webhook: store ready (db=%s, embedding=%s)",
            db_path,
            getattr(embedding_provider, "model_name", "unknown"),
        )
        return shared_state


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------


def _verify_bearer_token(request: Request, secret: str) -> bool:
    """Check the ``Authorization: Bearer <token>`` header.

    Uses :func:`hmac.compare_digest` for constant-time comparison to
    prevent timing-based attacks on the token value.

    Args:
        request: The incoming Starlette request.
        secret: The expected bearer token value.

    Returns:
        ``True`` if the token matches, ``False`` otherwise.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[len("Bearer ") :]
    return hmac.compare_digest(token, secret)


# ---------------------------------------------------------------------------
# Cooldown helpers
# ---------------------------------------------------------------------------


async def _check_cooldown(
    store: Any,
    endpoint: str,
) -> int | None:
    """Check whether *endpoint* is within its cooldown window.

    Args:
        store: A :class:`~distillery.store.protocol.DistilleryStore` instance.
        endpoint: The endpoint name (``"poll"``, ``"rescore"``, or
            ``"maintenance"``).

    Returns:
        The number of seconds remaining until the cooldown expires, or
        ``None`` if the endpoint is not in cooldown.
    """
    key = f"webhook_cooldown:{endpoint}"
    raw = await store.get_metadata(key)
    if raw is None:
        return None

    try:
        last_run = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None

    cooldown = _COOLDOWN_SECONDS.get(endpoint, 300)
    now = datetime.now(UTC)
    elapsed = (now - last_run).total_seconds()
    remaining = cooldown - elapsed
    if remaining > 0:
        return int(remaining) + 1  # round up to avoid edge-case zero
    return None


async def _set_cooldown(store: Any, endpoint: str) -> None:
    """Record the current time as the cooldown timestamp for *endpoint*.

    Args:
        store: A :class:`~distillery.store.protocol.DistilleryStore` instance.
        endpoint: The endpoint name.
    """
    key = f"webhook_cooldown:{endpoint}"
    now = datetime.now(UTC).isoformat()
    await store.set_metadata(key, now)


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------


async def _record_audit(store: Any, endpoint: str, response: JSONResponse) -> None:
    """Persist a lightweight audit record for the last webhook invocation.

    Stores a JSON object under ``webhook_audit:{endpoint}`` containing the
    timestamp, HTTP status, and response data (on success) or error message
    (on failure).  Only the most recent invocation per endpoint is kept —
    previous records are overwritten.

    Args:
        store: A :class:`~distillery.store.protocol.DistilleryStore` instance.
        endpoint: The endpoint name (``"poll"``, ``"rescore"``, or
            ``"maintenance"``).
        response: The :class:`~starlette.responses.JSONResponse` returned
            by the handler.
    """
    try:
        body = json.loads(bytes(response.body).decode())
    except Exception:  # noqa: BLE001
        body = {}

    record: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "status": response.status_code,
        "ok": body.get("ok", False),
    }

    if body.get("ok"):
        record["data"] = body.get("data", {})
    else:
        record["error"] = body.get("error", "unknown")

    key = f"webhook_audit:{endpoint}"
    await store.set_metadata(key, json.dumps(record))


# ---------------------------------------------------------------------------
# Maintenance helpers
# ---------------------------------------------------------------------------

#: The maintenance digest covers a trailing 7-day window.
_MAINTENANCE_PERIOD = timedelta(days=7)


def _parse_mcp_response(result: Any) -> dict[str, Any]:
    """Extract the JSON payload from an MCP ``TextContent`` response list.

    MCP handler functions return ``list[types.TextContent]``.  Each element
    has a ``.text`` attribute containing a JSON-serialised string.  This
    helper parses the first element and returns the dict, falling back to
    an empty dict on any parse error.

    Args:
        result: The return value of an ``_handle_*`` function from
            :mod:`distillery.mcp.server`.

    Returns:
        The parsed dict, or ``{}`` on failure.
    """
    try:
        return dict(json.loads(result[0].text))
    except Exception:  # noqa: BLE001
        logger.warning("Failed to parse MCP response: %r", result)
        return {}


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


async def _handle_poll(request: Request, state: dict[str, Any]) -> JSONResponse:
    """Handler for ``POST /poll``.

    Instantiates :class:`~distillery.feeds.poller.FeedPoller` using the
    initialised store, config, and embedding provider from *state*, runs a
    full poll cycle, and returns aggregate statistics.

    Args:
        request: The incoming Starlette request (unused beyond signature
            compatibility with the dispatcher).
        state: The populated shared-state dict containing ``"store"``,
            ``"config"``, and ``"embedding_provider"`` keys.

    Returns:
        JSON response with ``{"ok": true, "data": {"sources_polled": N,
        "items_fetched": N, "items_stored": N, "errors": [...]}}``, or
        ``{"ok": false, "error": "<message>"}`` with status 500 on failure.
    """
    from distillery.feeds.poller import FeedPoller

    store = state["store"]
    config = state["config"]

    logger.info("Webhook poll: starting poll cycle")
    try:
        poller = FeedPoller(store=store, config=config)
        summary = await poller.poll()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Webhook poll: poll cycle failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    # Collect errors from all per-source results.
    errors: list[str] = []
    for result in summary.results:
        errors.extend(result.errors)

    logger.info(
        "Webhook poll: completed — sources=%d fetched=%d stored=%d errors=%d",
        summary.sources_polled,
        summary.total_fetched,
        summary.total_stored,
        len(errors),
    )
    return JSONResponse(
        {
            "ok": True,
            "data": {
                "sources_polled": summary.sources_polled,
                "items_fetched": summary.total_fetched,
                "items_stored": summary.total_stored,
                "errors": errors,
            },
        }
    )


async def _handle_rescore(request: Request, state: dict[str, Any]) -> JSONResponse:
    """Handler for ``POST /rescore``.

    Accepts an optional JSON body ``{"limit": N}`` (default 200) and
    re-scores up to *N* existing feed entries against the current store.

    Args:
        request: The incoming Starlette request.  The body is read and
            parsed for the optional ``limit`` parameter.
        state: The populated shared-state dict containing ``"store"`` and
            ``"config"`` keys.

    Returns:
        JSON response with ``{"ok": true, "data": {"rescored": N,
        "upgraded": N, "downgraded": N}}``, or an error response with
        status 400 (malformed body) or 500 (internal error).
    """
    from distillery.feeds.poller import FeedPoller

    # Parse optional body for limit parameter.
    limit = 200
    body = await request.body()
    if body:
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError) as exc:
            return JSONResponse(
                {"ok": False, "error": f"malformed JSON body: {exc}"},
                status_code=400,
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                {"ok": False, "error": "request body must be a JSON object"},
                status_code=400,
            )
        if "limit" in payload:
            raw_limit = payload["limit"]
            if not isinstance(raw_limit, int) or isinstance(raw_limit, bool):
                return JSONResponse(
                    {"ok": False, "error": "limit must be an integer"},
                    status_code=400,
                )
            limit = raw_limit

    store = state["store"]
    config = state["config"]

    logger.info("Webhook rescore: starting rescore (limit=%d)", limit)
    try:
        poller = FeedPoller(store=store, config=config)
        stats = await poller.rescore(limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Webhook rescore: rescore failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    logger.info(
        "Webhook rescore: completed — rescored=%d upgraded=%d downgraded=%d",
        stats.get("rescored", 0),
        stats.get("upgraded", 0),
        stats.get("downgraded", 0),
    )
    return JSONResponse(
        {
            "ok": True,
            "data": {
                "rescored": stats.get("rescored", 0),
                "upgraded": stats.get("upgraded", 0),
                "downgraded": stats.get("downgraded", 0),
            },
        }
    )


async def _handle_maintenance(request: Request, state: dict[str, Any]) -> JSONResponse:
    """Handler for ``POST /maintenance``.

    Sequentially executes four knowledge-base maintenance operations:

    1. **metrics** -- 7-day usage metrics (scope="summary")
    2. **quality** -- search/feedback quality summary (scope="search_quality")
    3. **stale_detection** -- entries not accessed in 30 days (limit 10)
    4. **interests** -- top 10 interests over the past 30 days, including up
       to 3 feed source suggestions (via ``suggest_sources=True``)

    On success a one-paragraph digest entry is stored in the knowledge base
    with ``entry_type="session"``, ``author="distillery-maintenance"``, and
    system tags for downstream retrieval.  The digest entry ID is returned
    in the response.

    Args:
        request: The incoming Starlette request (unused beyond signature
            compatibility with the dispatcher).
        state: The populated shared-state dict containing ``"store"``,
            ``"config"``, and ``"embedding_provider"`` keys.

    Returns:
        JSON response with ``{"ok": true, "data": {"metrics": {...},
        "quality": {...}, "stale_count": N, "top_interests": [...],
        "suggested_sources": [...], "digest_entry_id": "..."}}``, or
        ``{"ok": false, "error": "<message>"}`` with status 500 on failure.
    """
    from distillery.mcp.server import (
        _handle_interests,
        _handle_metrics,
        _handle_stale,
    )
    from distillery.models import Entry, EntrySource, EntryType

    store = state["store"]
    config: DistilleryConfig = state["config"]
    embedding_provider = state.get("embedding_provider")

    logger.info("Webhook maintenance: starting maintenance cycle")
    try:
        # 1. Metrics (7-day period)
        metrics_result = await _handle_metrics(
            store=store,
            config=config,
            embedding_provider=embedding_provider,
            arguments={"period_days": 7},
        )
        metrics_data = _parse_mcp_response(metrics_result)

        # 2. Quality (via metrics with scope=search_quality)
        quality_result = await _handle_metrics(
            store=store,
            config=config,
            embedding_provider=embedding_provider,
            arguments={"scope": "search_quality"},
        )
        quality_data = _parse_mcp_response(quality_result)

        # 3. Stale detection (30 days, limit 10)
        stale_result = await _handle_stale(
            store=store,
            config=config,
            arguments={"days": 30, "limit": 10},
        )
        stale_data = _parse_mcp_response(stale_result)
        stale_count: int = stale_data.get("stale_count", 0)

        # 4. Interests (30 days, top 10) with source suggestions (max 3)
        interests_result = await _handle_interests(
            store=store,
            config=config,
            arguments={"recency_days": 30, "top_n": 10, "suggest_sources": True, "max_suggestions": 3},
        )
        interests_data = _parse_mcp_response(interests_result)
        top_interests: list[Any] = interests_data.get("top_tags", [])
        suggested_sources: list[Any] = interests_data.get("suggestions", [])

        # Compose digest summary
        now = datetime.now(UTC)
        period_start = (now - _MAINTENANCE_PERIOD).isoformat()
        period_end = now.isoformat()

        total_entries = metrics_data.get("entries", {}).get("total", 0)
        digest_content = (
            f"Weekly maintenance completed on {now.strftime('%Y-%m-%d')}. "
            f"Knowledge base contains {total_entries} entries with "
            f"{stale_count} stale items detected (30-day threshold). "
            f"Top interests: {', '.join(t[0] for t in top_interests[:5]) or 'none identified'}. "
            f"Source suggestions: {len(suggested_sources)} new sources proposed."
        )

        # Store digest entry
        entry = Entry(
            content=digest_content,
            entry_type=EntryType.SESSION,
            source=EntrySource.MANUAL,
            author="distillery-maintenance",
            tags=["system/digest", "system/weekly", "system/maintenance"],
            metadata={
                "period_start": period_start,
                "period_end": period_end,
            },
        )
        entry_id = await store.store(entry)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Webhook maintenance: maintenance cycle failed")
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    logger.info(
        "Webhook maintenance: completed — stale=%d interests=%d suggestions=%d digest=%s",
        stale_count,
        len(top_interests),
        len(suggested_sources),
        entry_id,
    )
    return JSONResponse(
        {
            "ok": True,
            "data": {
                "metrics": metrics_data,
                "quality": quality_data,
                "stale_count": stale_count,
                "top_interests": top_interests,
                "suggested_sources": suggested_sources,
                "digest_entry_id": entry_id,
            },
        }
    )


# Mapping of endpoint names to their handler callables.
# Each handler receives (request, state) where state is the populated
# shared-state dict containing "store", "config", and "embedding_provider".
_HANDLERS: dict[str, Any] = {
    "poll": _handle_poll,
    "rescore": _handle_rescore,
    "maintenance": _handle_maintenance,
}


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_webhook_app(
    shared_state: dict[str, Any],
    config: DistilleryConfig,
) -> Starlette:
    """Build a Starlette application serving the webhook REST endpoints.

    The returned app provides three ``POST`` routes (``/poll``,
    ``/rescore``, ``/maintenance``) protected by bearer-token
    authentication and per-endpoint cooldown enforcement.

    Rate limiting is applied via
    :class:`~distillery.mcp.middleware.RateLimitMiddleware` with tighter
    limits (10 requests/minute, 100 requests/hour) than the main MCP
    endpoint.

    Args:
        shared_state: The mutable shared-state dict that is (or will be)
            populated with ``"store"``, ``"config"``, and
            ``"embedding_provider"`` keys by the MCP lifespan or
            :func:`_ensure_store`.
        config: The loaded Distillery configuration.

    Returns:
        A :class:`~starlette.applications.Starlette` application ready
        to be mounted at ``/api`` in the parent app.
    """
    secret_env = config.server.webhooks.secret_env

    async def _authenticated_endpoint(
        request: Request,
        endpoint: str,
    ) -> JSONResponse:
        """Dispatch a webhook request after auth and cooldown checks.

        Args:
            request: The incoming Starlette request.
            endpoint: The endpoint name (``"poll"``, ``"rescore"``, or
                ``"maintenance"``).

        Returns:
            A JSON response from the endpoint handler, or an error
            response for auth/cooldown failures.
        """
        # --- Auth -----------------------------------------------------------
        secret = os.environ.get(secret_env, "")
        if not secret or not _verify_bearer_token(request, secret):
            return JSONResponse(
                {"ok": False, "error": "unauthorized"},
                status_code=401,
            )

        # --- Store init -----------------------------------------------------
        state = await _ensure_store(shared_state, config)
        store = state["store"]

        # --- Per-endpoint lock (serialise cooldown check + handler) ---------
        lock = _endpoint_locks.setdefault(endpoint, asyncio.Lock())
        async with lock:
            # --- Cooldown ---------------------------------------------------
            retry_after = await _check_cooldown(store, endpoint)
            if retry_after is not None:
                return JSONResponse(
                    {"ok": False, "error": "too_early", "retry_after": retry_after},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )

            # Reserve the cooldown slot before running the handler so that
            # a second request arriving during execution sees the reservation.
            await _set_cooldown(store, endpoint)

            # --- Dispatch ---------------------------------------------------
            handler = _HANDLERS[endpoint]
            response: JSONResponse = await handler(request, state)

            # --- Audit record (best-effort) ---------------------------------
            try:
                await _record_audit(store, endpoint, response)
            except Exception:  # noqa: BLE001
                logger.exception("Webhook %s: failed to persist audit record", endpoint)

            return response

    async def poll_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /poll``."""
        return await _authenticated_endpoint(request, "poll")

    async def rescore_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /rescore``."""
        return await _authenticated_endpoint(request, "rescore")

    async def maintenance_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /maintenance``."""
        return await _authenticated_endpoint(request, "maintenance")

    routes: list[Route] = [
        Route("/poll", poll_route, methods=["POST"]),
        Route("/rescore", rescore_route, methods=["POST"]),
        Route("/maintenance", maintenance_route, methods=["POST"]),
    ]

    # Apply rate limiting with tighter webhook-specific limits via
    # Starlette's middleware parameter so the returned object stays a
    # proper Starlette instance (required for Mount).
    from distillery.mcp.middleware import RateLimitMiddleware

    app = Starlette(
        routes=routes,
        middleware=[
            Middleware(
                RateLimitMiddleware,
                requests_per_minute=10,
                requests_per_hour=100,
            ),
        ],
    )

    return app
