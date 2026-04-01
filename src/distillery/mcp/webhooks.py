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

import contextlib
import hmac
import logging
import os
from datetime import UTC, datetime
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

    Because asyncio is single-threaded there is no true race condition --
    this simply checks whether init has already occurred and runs it if not.

    Args:
        shared_state: The mutable shared-state dict (same object passed to
            the MCP lifespan).
        config: The loaded Distillery configuration.

    Returns:
        The populated shared-state dict.
    """
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
# Stub route handlers
# ---------------------------------------------------------------------------


async def _handle_poll(request: Request) -> JSONResponse:
    """Stub handler for ``POST /poll``.

    The actual polling logic is implemented by the handler task (T02).
    This stub returns a success response with an empty data payload.

    Args:
        request: The incoming Starlette request.

    Returns:
        JSON response with ``{"ok": true, "data": {}}``.
    """
    return JSONResponse({"ok": True, "data": {}})


async def _handle_rescore(request: Request) -> JSONResponse:
    """Stub handler for ``POST /rescore``.

    The actual rescoring logic is implemented by the handler task (T02).
    This stub returns a success response with an empty data payload.

    Args:
        request: The incoming Starlette request.

    Returns:
        JSON response with ``{"ok": true, "data": {}}``.
    """
    return JSONResponse({"ok": True, "data": {}})


async def _handle_maintenance(request: Request) -> JSONResponse:
    """Stub handler for ``POST /maintenance``.

    The actual maintenance logic is implemented by the handler task (T02).
    This stub returns a success response with an empty data payload.

    Args:
        request: The incoming Starlette request.

    Returns:
        JSON response with ``{"ok": true, "data": {}}``.
    """
    return JSONResponse({"ok": True, "data": {}})


# Mapping of endpoint names to their handler callables.
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

        # --- Cooldown -------------------------------------------------------
        retry_after = await _check_cooldown(store, endpoint)
        if retry_after is not None:
            return JSONResponse(
                {"ok": False, "error": "too_early", "retry_after": retry_after},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        # --- Dispatch -------------------------------------------------------
        handler = _HANDLERS[endpoint]
        response: JSONResponse = await handler(request)

        # Record cooldown only on success.
        if response.status_code < 400:
            await _set_cooldown(store, endpoint)

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
