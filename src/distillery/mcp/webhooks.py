"""Webhook REST endpoints for scheduled Distillery operations.

.. deprecated::
    The ``/hooks/poll``, ``/hooks/rescore``, and ``/hooks/classify-batch``
    endpoints are deprecated in favour of Claude Code routines for scheduling.
    The ``/api/maintenance`` endpoint is retained for orchestrated maintenance.
    See issue #272 for migration details.

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
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from distillery.config import DistilleryConfig
from distillery.feeds.poller import FeedPoller

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default cooldown intervals (seconds)
# ---------------------------------------------------------------------------

_COOLDOWN_SECONDS: dict[str, int] = {
    "poll": 300,  # 5 minutes
    "rescore": 3600,  # 1 hour
    "maintenance": 21600,  # 6 hours
    "classify-batch": 300,  # 5 minutes
}

# Per-endpoint locks to serialize dispatch and prevent TOCTOU races on
# cooldown checks.  Created lazily in the app factory.
_endpoint_locks: dict[str, asyncio.Lock] = {}

# Lock to serialize cold-start store initialisation so that concurrent
# first-hit requests (e.g. workflow_dispatch "all") don't each create a
# separate DuckDBStore.
_init_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Async job registry (in-process)
# ---------------------------------------------------------------------------
#
# The /poll, /rescore, and /maintenance endpoints return 202 immediately and
# run the actual work on a background asyncio task.  Callers poll
# GET /jobs/{id} to observe progress.  Records are kept in a bounded FIFO
# buffer per process; state is NOT persisted across restarts (scheduler loss
# is acceptable — cron will re-trigger).

# Maximum number of job records to retain in memory.
_JOBS_MAX = 100


@dataclass
class _JobStatus:
    """In-process record of an async webhook job."""

    id: str
    endpoint: str
    state: str  # "queued" | "running" | "succeeded" | "failed"
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    task: asyncio.Task[Any] | None = field(default=None, repr=False, compare=False)


_jobs: OrderedDict[str, _JobStatus] = OrderedDict()
_active_job_by_endpoint: dict[str, str] = {}
_jobs_lock = asyncio.Lock()


async def _register_job(endpoint: str) -> _JobStatus:
    """Allocate a new job id and mark it active for *endpoint*.

    Evicts the oldest job record once :data:`_JOBS_MAX` is exceeded.  Callers
    must have already verified (under the endpoint lock) that no other job is
    active for *endpoint* — this function does not re-check.
    """
    async with _jobs_lock:
        job = _JobStatus(
            id=uuid.uuid4().hex[:16],
            endpoint=endpoint,
            state="queued",
            submitted_at=datetime.now(UTC),
        )
        _jobs[job.id] = job
        while len(_jobs) > _JOBS_MAX:
            _jobs.popitem(last=False)
        _active_job_by_endpoint[endpoint] = job.id
        return job


async def _active_job_id(endpoint: str) -> str | None:
    """Return the current active job id for *endpoint*, if any is in flight.

    Stale pointers (job record evicted or already terminal) are cleaned up so
    subsequent requests aren't blocked by a pointer to a completed job.
    """
    async with _jobs_lock:
        job_id = _active_job_by_endpoint.get(endpoint)
        if job_id is None:
            return None
        job = _jobs.get(job_id)
        if job is None or job.state in ("succeeded", "failed"):
            _active_job_by_endpoint.pop(endpoint, None)
            return None
        return job_id


async def _finish_job(
    job: _JobStatus,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Mark *job* terminal and clear the active-job pointer."""
    async with _jobs_lock:
        job.state = "failed" if error is not None else "succeeded"
        job.finished_at = datetime.now(UTC)
        job.result = result
        job.error = error
        if _active_job_by_endpoint.get(job.endpoint) == job.id:
            del _active_job_by_endpoint[job.endpoint]


async def _mark_job_running(job: _JobStatus) -> None:
    """Transition *job* from queued to running."""
    async with _jobs_lock:
        job.state = "running"
        job.started_at = datetime.now(UTC)


def _job_to_dict(job: _JobStatus) -> dict[str, Any]:
    """Serialise a :class:`_JobStatus` for the GET /jobs/{id} response."""
    return {
        "job_id": job.id,
        "endpoint": job.endpoint,
        "state": job.state,
        "submitted_at": job.submitted_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "result": job.result,
        "error": job.error,
    }


async def _execute_job(
    job: _JobStatus,
    state: dict[str, Any],
    runner: Callable[..., Awaitable[JSONResponse]],
    kwargs: dict[str, Any],
) -> None:
    """Background driver: run *runner* and store the outcome on *job*.

    Any exception escaping *runner* is caught and recorded as a failure so it
    surfaces through :func:`jobs_route`.  Audit records are written
    best-effort after completion.

    After the runner finishes — success or failure — this helper calls
    ``store.rollback()`` (when the store exposes one) to clear any aborted
    DuckDB transaction state that may have leaked through a code path that
    bypasses :meth:`DuckDBStore._run_sync`.  Issue #396 documents an
    aborted-transaction cascade observed during poll runs: without this
    best-effort rollback, the *next* webhook job on the same process can
    inherit a poisoned connection and fail every query with
    ``TransactionContext Error: Current transaction is aborted (please
    ROLLBACK)``.  Errors from rollback itself are logged and swallowed.
    """
    await _mark_job_running(job)
    try:
        response = await runner(state, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Webhook %s (job=%s): background runner raised", job.endpoint, job.id)
        error_message = str(exc) or "unexpected error"
        await _try_rollback(state.get("store"), job)

        # Persist an audit record for the failure too — the happy path
        # writes one below; skipping it on the except branch left the
        # most-interesting failure mode invisible in the ``webhook_audit:*``
        # metadata row.  Manufacture a response shape that matches the
        # runner's own 500 JSON so ``_record_audit`` sees a consistent
        # ``{"ok": false, "error": "..."}`` payload.
        failure_response = JSONResponse(
            {"ok": False, "error": error_message},
            status_code=500,
        )
        try:
            await _record_audit(state["store"], job.endpoint, failure_response)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Webhook %s (job=%s): failed to persist audit record on exception path",
                job.endpoint,
                job.id,
            )

        # Transition terminal last so callers polling GET /jobs/{id} only see
        # "failed" once every side effect (rollback + audit here; audit below
        # on the success path) has landed.  Otherwise tests that poll until
        # terminal and then exit the TestClient can race a dangling bg write.
        await _finish_job(job, error=error_message)
        return

    try:
        body: dict[str, Any] = json.loads(bytes(response.body).decode())
    except Exception:  # noqa: BLE001
        body = {}

    # Runners catch their own exceptions and return 500 JSON on failure, so
    # reaching here with ``ok=False`` still means the runner handled an
    # exception internally — roll back defensively in that case too.
    if not body.get("ok"):
        await _try_rollback(state.get("store"), job)

    try:
        await _record_audit(state["store"], job.endpoint, response)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Webhook %s (job=%s): failed to persist audit record", job.endpoint, job.id
        )

    # Finish last: the job's terminal state is the "all work complete"
    # signal callers poll for.  Flipping it before the audit / rollback
    # finishes lets a test's ``_wait_for_job`` return, the TestClient
    # teardown cancel the task, and a dangling store write race the next
    # test's fresh store.
    if body.get("ok"):
        await _finish_job(job, result=body.get("data", {}))
    else:
        await _finish_job(job, error=body.get("error", "unknown error"))


async def _try_rollback(store: Any, job: _JobStatus) -> None:
    """Call ``store.rollback()`` best-effort; never raise."""
    rollback = getattr(store, "rollback", None) if store is not None else None
    if rollback is None:
        return
    try:
        await rollback()
    except Exception:  # noqa: BLE001
        logger.exception(
            "Webhook %s (job=%s): post-failure store.rollback() raised",
            job.endpoint,
            job.id,
        )

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
#
# In-memory cache (``_cooldown_ts``) keyed by endpoint name is the
# authoritative *in-process* source of truth for cooldowns.  DuckDB
# metadata is still written through so cooldowns survive process restarts
# (see :func:`test_cooldown_persisted`), but reads prefer the cache.
#
# Rationale: the bg task spawned by a successful POST (e.g. audit writes,
# feed-poll work) shares the single DuckDB connection with the dispatcher
# handling the *next* request.  DuckDB's Python binding serialises
# statements on a single connection only when called from the same thread;
# ``asyncio.to_thread`` dispatches to the default threadpool and can run
# two store coroutines on different workers concurrently.  In practice
# that produces flaky ``get_metadata`` reads that miss a just-committed
# ``set_metadata`` write — which presented as "second POST returned 409
# (job_in_progress) instead of 429 (too_early)" across Python 3.11-3.14
# on CI.  The in-memory cache sidesteps the race entirely for the common
# single-process case; DuckDB retains its persistence role untouched.

_cooldown_ts: dict[str, datetime] = {}


async def _check_cooldown(
    store: Any,
    endpoint: str,
) -> int | None:
    """Check whether *endpoint* is within its cooldown window.

    Consults :data:`_cooldown_ts` first (in-process cache, immune to the
    DuckDB-across-threadpool race described above).  Falls back to
    ``store.get_metadata`` on cache miss so a freshly-started process
    picks up cooldowns persisted by a previous run.

    Args:
        store: A :class:`~distillery.store.protocol.DistilleryStore` instance.
        endpoint: The endpoint name (``"poll"``, ``"rescore"``, or
            ``"maintenance"``).

    Returns:
        The number of seconds remaining until the cooldown expires, or
        ``None`` if the endpoint is not in cooldown.
    """
    last_run = _cooldown_ts.get(endpoint)
    if last_run is None:
        key = f"webhook_cooldown:{endpoint}"
        raw = await store.get_metadata(key)
        if raw is None:
            return None
        try:
            last_run = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None
        # Populate the cache for subsequent checks in this process.
        _cooldown_ts[endpoint] = last_run

    cooldown = _COOLDOWN_SECONDS.get(endpoint, 300)
    now = datetime.now(UTC)
    elapsed = (now - last_run).total_seconds()
    remaining = cooldown - elapsed
    if remaining > 0:
        return int(remaining) + 1  # round up to avoid edge-case zero
    return None


async def _set_cooldown(store: Any, endpoint: str) -> None:
    """Record the current time as the cooldown timestamp for *endpoint*.

    Writes to :data:`_cooldown_ts` and to DuckDB.  The in-memory write is
    what subsequent same-process :func:`_check_cooldown` calls read; the
    DuckDB write is only consulted after a restart.

    Args:
        store: A :class:`~distillery.store.protocol.DistilleryStore` instance.
        endpoint: The endpoint name.
    """
    now = datetime.now(UTC)
    _cooldown_ts[endpoint] = now
    key = f"webhook_cooldown:{endpoint}"
    await store.set_metadata(key, now.isoformat())


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
# Route handlers
# ---------------------------------------------------------------------------


async def _run_poll(
    state: dict[str, Any],
    source_url: str | None = None,
) -> JSONResponse:
    """Core poll logic shared by ``/poll`` and ``/hooks/poll`` routes.

    Instantiates :class:`~distillery.feeds.poller.FeedPoller` using the
    initialised store and config from *state*, runs a poll cycle (optionally
    restricted to *source_url*), and returns aggregate statistics.

    The interest profile needed for relevance scoring is computed internally
    by :class:`~distillery.feeds.poller.FeedPoller` — it does not depend on
    the separate ``distillery_interests`` MCP tool.

    Args:
        state: The populated shared-state dict containing ``"store"``,
            ``"config"``, and ``"embedding_provider"`` keys.
        source_url: When provided, only this source is polled; ``None`` polls
            all configured sources.

    Returns:
        JSON response with ``{"ok": true, "data": {"sources_polled": N,
        "items_fetched": N, "items_stored": N, "errors": [...]}}``, or
        ``{"ok": false, "error": "<message>"}`` with status 500 on failure.
    """
    store = state["store"]
    config = state["config"]

    logger.info("Webhook poll: starting poll cycle (source_url=%r)", source_url)
    try:
        poller = FeedPoller(store=store, config=config)
        summary = await poller.poll(source_url=source_url)
    except Exception:  # noqa: BLE001
        # Keep the full traceback in logs; return a stable generic message to
        # the client so exception internals are not leaked over HTTP.
        logger.exception("Webhook poll: poll cycle failed")
        return JSONResponse({"ok": False, "error": "poll cycle failed"}, status_code=500)

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


async def _parse_poll_params(
    request: Request,
) -> dict[str, Any] | JSONResponse:
    """Parse ``source_url`` from query string or JSON body.

    Returns a kwargs dict ``{"source_url": str | None}`` on success, or a
    ``JSONResponse`` with status 400 describing the problem.  Parsing happens
    synchronously before the request returns 202 so that malformed requests
    fail fast rather than through the async job status.

    Args:
        request: The incoming Starlette request.
    """
    source_url: str | None = request.query_params.get("source_url")
    if source_url is None:
        body = await request.body()
        if body:
            try:
                payload = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return JSONResponse(
                    {"ok": False, "error": "Invalid JSON in request body"},
                    status_code=400,
                )
            if not isinstance(payload, dict):
                return JSONResponse(
                    {"ok": False, "error": "request body must be a JSON object"},
                    status_code=400,
                )
            # If a JSON body is supplied it must carry source_url. Silently
            # treating `{}` or typo'd keys like `{"src":"…"}` as an all-sources
            # poll turns a malformed targeted request into the most expensive
            # mutation path in this handler. Callers that want an all-sources
            # poll should send no body (or an empty body) instead.
            val = payload.get("source_url")
            if not isinstance(val, str):
                return JSONResponse(
                    {
                        "ok": False,
                        "error": (
                            "source_url is required in the request body and must "
                            "be a string; send an empty body to poll all sources"
                        ),
                    },
                    status_code=400,
                )
            source_url = val
    return {"source_url": source_url}


async def _run_rescore(
    state: dict[str, Any],
    limit: int = 200,
) -> JSONResponse:
    """Core rescore logic shared by ``/rescore`` and ``/hooks/rescore`` routes.

    Re-scores up to *limit* existing feed entries against the current store.

    Args:
        state: The populated shared-state dict containing ``"store"`` and
            ``"config"`` keys.
        limit: Maximum number of entries to rescore (default 200).

    Returns:
        JSON response with ``{"ok": true, "data": {"rescored": N,
        "upgraded": N, "downgraded": N}}``, or an error response with
        status 500 on failure.
    """
    store = state["store"]
    config = state["config"]

    logger.info("Webhook rescore: starting rescore (limit=%d)", limit)
    try:
        poller = FeedPoller(store=store, config=config)
        stats = await poller.rescore(limit=limit)
    except Exception:  # noqa: BLE001
        # Keep the full traceback in logs; return a stable generic message.
        logger.exception("Webhook rescore: rescore failed")
        return JSONResponse({"ok": False, "error": "rescore failed"}, status_code=500)

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


async def _parse_rescore_params(
    request: Request,
) -> dict[str, Any] | JSONResponse:
    """Parse ``limit`` from query string or JSON body.

    Query string takes precedence over the body.  Returns a kwargs dict
    ``{"limit": int}`` on success, or a ``JSONResponse`` with status 400.

    Args:
        request: The incoming Starlette request.
    """
    qs_limit: str | None = request.query_params.get("limit")
    if isinstance(qs_limit, str):
        try:
            limit = int(qs_limit)
        except (ValueError, TypeError):
            return JSONResponse(
                {"ok": False, "error": "limit query parameter must be an integer"},
                status_code=400,
            )
        if limit <= 0:
            return JSONResponse(
                {"ok": False, "error": "limit must be a positive integer"},
                status_code=400,
            )
    else:
        limit = 200
        body = await request.body()
        if body:
            try:
                payload = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                return JSONResponse(
                    {"ok": False, "error": "malformed JSON body"},
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
                if raw_limit <= 0:
                    return JSONResponse(
                        {"ok": False, "error": "limit must be a positive integer"},
                        status_code=400,
                    )
                limit = raw_limit

    return {"limit": limit}


async def _run_maintenance(state: dict[str, Any]) -> JSONResponse:
    """Core maintenance logic invoked by the background job runner.

    Sequentially orchestrates three sub-operations:

    1. **poll** -- fetch new items from all configured feed sources.
    2. **rescore** -- re-score existing feed entries against the current
       interest profile (up to 200 entries).
    3. **classify-batch** -- classify pending inbox entries using the
       configured classification mode.

    Each sub-operation is invoked via its internal ``_run_*`` helper so that
    no HTTP self-calls are made.  Each sub-operation returns its result dict;
    all three are merged into the combined response under ``poll``,
    ``rescore``, and ``classify_batch`` keys.

    Sub-phase cooldowns are reserved briefly (under the phase endpoint lock)
    BEFORE the long-running phase work runs, so a direct ``POST /hooks/poll``
    arriving mid-maintenance sees the cooldown and returns 429 rather than
    running a duplicate fetch.  The phase work itself runs outside the lock so
    it doesn't block the fast-path of unrelated webhook requests.

    If a sub-operation fails, its result is recorded as
    ``{"ok": false, "error": "<message>"}`` and the remaining sub-operations
    still run — maintenance is best-effort.

    Args:
        state: The populated shared-state dict containing ``"store"``,
            ``"config"``, and ``"embedding_provider"`` keys.

    Returns:
        JSON response with ``{"ok": true, "data": {"poll": {...},
        "rescore": {...}, "classify_batch": {...}}}``.  The top-level
        ``ok`` is ``true`` even when individual sub-operations fail so that
        the caller always receives the combined report.  A status 500 is
        returned only when maintenance cannot start at all (e.g. store
        unavailable).
    """
    logger.info("Webhook maintenance: starting maintenance cycle (poll → rescore → classify-batch)")

    def _extract(response: JSONResponse) -> dict[str, Any]:
        try:
            body: dict[str, Any] = json.loads(bytes(response.body).decode())
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "failed to parse sub-operation response"}
        return body

    store = state["store"]

    # 1. Poll — fetch new feed items.  Reserve the poll cooldown before
    # running the phase so a concurrent direct POST /hooks/poll sees the
    # reservation and returns 429 rather than duplicating the fetch work.
    poll_lock = _endpoint_locks.setdefault("poll", asyncio.Lock())
    async with poll_lock:
        await _set_cooldown(store, "poll")
    poll_response = await _run_poll(state)
    poll_body = _extract(poll_response)
    poll_result: dict[str, Any] = (
        {"ok": True, **poll_body.get("data", {})}
        if poll_body.get("ok")
        else {"ok": False, "error": poll_body.get("error", "poll failed")}
    )

    # 2. Rescore — re-score existing entries.
    rescore_lock = _endpoint_locks.setdefault("rescore", asyncio.Lock())
    async with rescore_lock:
        await _set_cooldown(store, "rescore")
    rescore_response = await _run_rescore(state)
    rescore_body = _extract(rescore_response)
    rescore_result: dict[str, Any] = (
        {"ok": True, **rescore_body.get("data", {})}
        if rescore_body.get("ok")
        else {"ok": False, "error": rescore_body.get("error", "rescore failed")}
    )

    # 3. Classify-batch — classify pending inbox entries.
    classify_lock = _endpoint_locks.setdefault("classify-batch", asyncio.Lock())
    async with classify_lock:
        await _set_cooldown(store, "classify-batch")
    classify_response = await _run_classify_batch(state)
    classify_body = _extract(classify_response)
    classify_result: dict[str, Any] = (
        {"ok": True, **classify_body.get("data", {})}
        if classify_body.get("ok")
        else {"ok": False, "error": classify_body.get("error", "classify-batch failed")}
    )

    # 4. Search log retention — prune old search_log rows.
    retention_result: dict[str, Any] = {"ok": True, "deleted": 0}
    config = state.get("config")
    if config is not None and config.rate_limit.search_log_retention_days > 0:
        retention_days = config.rate_limit.search_log_retention_days
        try:
            # Delegate to the store's async helper so the DuckDB connection is
            # used from its owning thread (the store's to_thread worker),
            # rather than accessed directly from this webhook coroutine.
            deleted = await store.prune_search_log(retention_days)
            retention_result = {"ok": True, "deleted": deleted}
            if deleted:
                logger.info(
                    "Maintenance: pruned %d search_log rows older than %d days",
                    deleted,
                    retention_days,
                )
        except Exception:  # noqa: BLE001
            # Log full details server-side; keep the client-facing message
            # stable and free of exception internals.
            retention_result = {"ok": False, "error": "search_log retention failed"}
            logger.exception("Maintenance: search_log retention failed")

    logger.info(
        "Webhook maintenance: completed — poll_ok=%s rescore_ok=%s classify_ok=%s",
        poll_body.get("ok"),
        rescore_body.get("ok"),
        classify_body.get("ok"),
    )
    return JSONResponse(
        {
            "ok": True,
            "data": {
                "poll": poll_result,
                "rescore": rescore_result,
                "classify_batch": classify_result,
                "search_log_retention": retention_result,
            },
        }
    )


_DEFAULT_CLASSIFY_BATCH_LIMIT: int = 500
"""Default maximum number of entries to classify in a single batch."""


async def _run_classify_batch(
    state: dict[str, Any],
    entry_type: str = "inbox",
    mode: str | None = None,
    limit: int = _DEFAULT_CLASSIFY_BATCH_LIMIT,
) -> JSONResponse:
    """Core classify-batch logic shared by ``/hooks/classify-batch`` route.

    Fetches entries matching *entry_type* filter with
    ``status=pending_review``. For ``mode="heuristic"`` each entry is
    classified in-process using the embedding-centroid-based
    :class:`~distillery.classification.heuristic.HeuristicClassifier` and
    persisted. For ``mode="llm"`` the webhook is **intentionally headless for
    v1** — it counts the backlog and returns all entries as
    ``pending_review`` so a human can triage via ``/classify --review``. It
    will not dispatch an LLM call even if ``state["llm_client"]`` is
    populated; that responsibility belongs to the skill side.

    Args:
        state: The populated shared-state dict containing ``"store"``,
            ``"config"``, and ``"embedding_provider"`` keys.
        entry_type: Only entries with this ``entry_type`` are classified.
            Defaults to ``"inbox"``.
        mode: Classification mode — ``"llm"`` or ``"heuristic"``.  When
            ``None``, the value from ``config.classification.mode`` (falling
            back to ``"llm"``) is used.
        limit: Maximum number of entries to classify in a single batch.
            Defaults to :data:`_DEFAULT_CLASSIFY_BATCH_LIMIT` (500).

    Returns:
        JSON response ``{"ok": true, "data": {"classified": N,
        "pending_review": N, "errors": N, "by_type": {type: count}}}``,
        or ``{"ok": false, "error": "<message>"}`` with status 500 on failure.
    """
    from distillery.classification import HeuristicClassifier
    from distillery.models import EntryStatus

    store = state["store"]
    config = state["config"]
    embedding_provider = state.get("embedding_provider")

    # Resolve effective mode.
    effective_mode = mode
    if effective_mode is None:
        effective_mode = getattr(config.classification, "mode", "llm")

    logger.info(
        "Webhook classify-batch: starting (entry_type=%r, mode=%r, limit=%d)",
        entry_type,
        effective_mode,
        limit,
    )

    try:
        # Fetch entries awaiting classification.
        result = await store.list_entries(
            filters={"entry_type": entry_type, "status": EntryStatus.PENDING_REVIEW.value},
            limit=limit,
            offset=0,
        )
        if len(result if isinstance(result, list) else []) >= limit:
            logger.warning(
                "Webhook classify-batch: batch limit reached (%d entries) — "
                "additional pending entries may exist; consider increasing the limit.",
                limit,
            )
        entries = result if isinstance(result, list) else []

        classified_count = 0
        pending_review_count = 0
        error_count = 0
        by_type: dict[str, int] = {}

        if effective_mode == "heuristic" and entries:
            classifier = HeuristicClassifier()
            if embedding_provider is None:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "heuristic mode requires an embedding provider",
                    },
                    status_code=500,
                )
            # Delegate to classify_batch which computes centroids once for the
            # entire batch — avoids redundant store queries per entry (#261).
            classifications = await classifier.classify_batch(entries, store, embedding_provider)
            for entry, classification in zip(entries, classifications, strict=True):
                try:
                    # Merge classification fields into the existing metadata so
                    # previously-set keys (e.g. external_id, source_url, repo)
                    # are preserved. Store the score under "confidence" — the
                    # key that distillery_list(output_mode="review") reads.
                    merged_metadata = {
                        **(entry.metadata or {}),
                        "confidence": classification.confidence,
                        "classification_reasoning": classification.reasoning,
                    }
                    await store.update(
                        entry.id,
                        {
                            "entry_type": classification.entry_type.value,
                            "status": classification.status.value,
                            "metadata": merged_metadata,
                        },
                    )
                    if classification.status == EntryStatus.ACTIVE:
                        classified_count += 1
                        type_key = classification.entry_type.value
                        by_type[type_key] = by_type.get(type_key, 0) + 1
                    else:
                        pending_review_count += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Webhook classify-batch: heuristic classification failed for %s: %s",
                        entry.id,
                        exc,
                    )
                    error_count += 1
        else:
            # LLM mode (v1): intentionally headless. The webhook is meant to
            # surface backlog to human reviewers via ``/classify --review``
            # rather than drive expensive LLM calls from the cron path. Every
            # pending inbox entry is therefore written back as
            # ``pending_review`` regardless of any ``llm_client`` that happens
            # to be present in shared state. If a future release moves LLM
            # classification into the webhook, bump the contract with a new
            # ``mode`` (e.g. ``"llm-sync"``) rather than changing this branch
            # in place.
            pending_review_count += len(entries)

    except Exception:  # noqa: BLE001
        # Keep the full traceback in logs; return a stable generic message.
        logger.exception("Webhook classify-batch: batch operation failed")
        return JSONResponse({"ok": False, "error": "classify-batch failed"}, status_code=500)

    logger.info(
        "Webhook classify-batch: completed — classified=%d pending_review=%d errors=%d",
        classified_count,
        pending_review_count,
        error_count,
    )
    return JSONResponse(
        {
            "ok": True,
            "data": {
                "classified": classified_count,
                "pending_review": pending_review_count,
                "errors": error_count,
                "by_type": by_type,
            },
        }
    )


async def _handle_classify_batch(request: Request, state: dict[str, Any]) -> JSONResponse:
    """Handler for ``POST /hooks/classify-batch``.

    Delegates to :func:`_run_classify_batch`.  Accepts optional query
    parameters:

    - ``entry_type`` (default ``"inbox"``): filter entries by type.
    - ``mode`` (default from config): ``"llm"`` or ``"heuristic"``.
    - ``limit`` (default 500): maximum number of entries to classify per batch.

    Args:
        request: The incoming Starlette request.
        state: The populated shared-state dict.

    Returns:
        A :class:`~starlette.responses.JSONResponse` from
        :func:`_run_classify_batch`.
    """
    from distillery.models import EntryType

    entry_type = request.query_params.get("entry_type", "inbox")
    valid_entry_types = {member.value for member in EntryType}
    if entry_type not in valid_entry_types:
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    f"entry_type must be one of: {sorted(valid_entry_types)}, got: {entry_type!r}"
                ),
            },
            status_code=400,
        )

    mode_param = request.query_params.get("mode")
    if mode_param is not None and not mode_param.strip():
        return JSONResponse(
            {"ok": False, "error": "mode must be 'llm' or 'heuristic'"},
            status_code=400,
        )
    mode: str | None = mode_param.strip() if isinstance(mode_param, str) else None

    if mode is not None and mode not in ("llm", "heuristic"):
        return JSONResponse(
            {"ok": False, "error": f"mode must be 'llm' or 'heuristic', got: {mode!r}"},
            status_code=400,
        )

    # Parse optional limit query param.
    limit_param: str | None = request.query_params.get("limit")
    limit = _DEFAULT_CLASSIFY_BATCH_LIMIT
    if limit_param is not None:
        try:
            limit = int(limit_param)
        except (ValueError, TypeError):
            return JSONResponse(
                {"ok": False, "error": "limit query parameter must be an integer"},
                status_code=400,
            )
        if limit <= 0:
            return JSONResponse(
                {"ok": False, "error": "limit must be a positive integer"},
                status_code=400,
            )

    return await _run_classify_batch(state, entry_type=entry_type, mode=mode, limit=limit)


# ---------------------------------------------------------------------------
# Async endpoint dispatch table
# ---------------------------------------------------------------------------
#
# Each async endpoint defines a parser (validates the request synchronously
# and returns kwargs or a 400 error response) and a runner (the work to do
# in the background).  The dispatcher in :func:`create_webhook_app`
# synchronously auths → parses → reserves cooldown → registers the job →
# returns 202 with a job id.  The runner executes via :func:`_execute_job`
# on a detached asyncio task.

_AsyncParser = Callable[[Request], Awaitable["dict[str, Any] | JSONResponse"]]
_AsyncRunner = Callable[..., Awaitable[JSONResponse]]


async def _parse_maintenance_params(
    request: Request,
) -> dict[str, Any] | JSONResponse:
    """``/maintenance`` takes no request-level parameters."""
    return {}


_ASYNC_ENDPOINTS: dict[str, tuple[_AsyncParser, _AsyncRunner]] = {
    "poll": (_parse_poll_params, _run_poll),
    "rescore": (_parse_rescore_params, _run_rescore),
    "maintenance": (_parse_maintenance_params, _run_maintenance),
}


# Synchronous dispatch table — retained for ``/hooks/classify-batch`` which
# remains synchronous (its deprecation path is out of issue #396 scope).
_SYNC_HANDLERS: dict[str, Callable[[Request, dict[str, Any]], Awaitable[JSONResponse]]] = {
    "classify-batch": _handle_classify_batch,
}


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_webhook_app(
    shared_state: dict[str, Any],
    config: DistilleryConfig,
) -> Starlette:
    """Build a Starlette application serving the webhook REST endpoints.

    The returned app provides:

    - ``POST /poll``, ``/rescore``, ``/maintenance`` — async endpoints that
      enqueue a background job and return ``202 Accepted`` with a ``job_id``.
      Callers poll ``GET /jobs/{job_id}`` to observe progress.
    - ``POST /hooks/poll``, ``/hooks/rescore`` — deprecated aliases sharing
      the async contract of their canonical counterparts.
    - ``POST /hooks/classify-batch`` — deprecated synchronous endpoint.
    - ``GET /jobs/{job_id}`` — status endpoint for async jobs.

    All endpoints require bearer-token authentication.  Per-endpoint
    cooldowns are enforced against DuckDB metadata.  A second request while
    a job is in flight returns ``409 Conflict`` with the existing ``job_id``
    so the scheduler can re-attach to the existing job rather than racing.

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

    async def _authenticate(request: Request) -> JSONResponse | None:
        """Return a 401 response if auth fails, else ``None``."""
        secret = os.environ.get(secret_env, "")
        if not secret or not _verify_bearer_token(request, secret):
            return JSONResponse(
                {"ok": False, "error": "unauthorized"},
                status_code=401,
            )
        return None

    async def _dispatch_async(
        request: Request,
        endpoint: str,
    ) -> JSONResponse:
        """Validate + reserve cooldown + schedule background job.

        Returns ``202`` with ``{"ok": true, "job_id": "...", "state":
        "queued", "status_url": "/jobs/..."}`` when the job is enqueued.
        Returns ``429``/``409``/``401``/``400`` for rejected requests.
        """
        auth_err = await _authenticate(request)
        if auth_err is not None:
            return auth_err

        state = await _ensure_store(shared_state, config)
        store = state["store"]

        parser, runner = _ASYNC_ENDPOINTS[endpoint]
        parsed = await parser(request)
        if isinstance(parsed, JSONResponse):
            return parsed

        # ``root_path`` is set by Starlette's ``Mount`` to the prefix the
        # webhook app is mounted at (e.g. ``"/api"``).  Using it in
        # ``status_url`` lets callers poll the job directly without knowing
        # the mount layout — essential for the scheduler in distill_ops.
        root_path = request.scope.get("root_path", "")

        lock = _endpoint_locks.setdefault(endpoint, asyncio.Lock())
        async with lock:
            # Idempotency first: if a job is already running for this
            # endpoint, return 409 with the existing job id so the caller
            # re-attaches rather than racing a duplicate or backing off on a
            # cooldown that merely reflects its own in-flight work.  A 429
            # here would misdirect the scheduler into "try later" when the
            # correct action is "poll /jobs/{id} for completion".
            existing_job_id = await _active_job_id(endpoint)
            if existing_job_id is not None:
                return JSONResponse(
                    {
                        "ok": False,
                        "error": "job_in_progress",
                        "job_id": existing_job_id,
                        "status_url": f"{root_path}/jobs/{existing_job_id}",
                    },
                    status_code=409,
                )

            # Cooldown enforcement is preserved — scheduler cooldowns are the
            # primary debounce against runaway workflow re-triggers from a
            # caller that is NOT currently mid-job.
            retry_after = await _check_cooldown(store, endpoint)
            if retry_after is not None:
                return JSONResponse(
                    {"ok": False, "error": "too_early", "retry_after": retry_after},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )

            # Reserve cooldown + allocate a job record before releasing the
            # endpoint lock so subsequent requests see both signals.
            await _set_cooldown(store, endpoint)
            job = await _register_job(endpoint)

        # Detach the work.  The returned Task is retained on the job record
        # to avoid "Task was destroyed while pending" warnings when the event
        # loop's weak references drop it.
        job.task = asyncio.create_task(
            _execute_job(job, state, runner, parsed),
            name=f"webhook-{endpoint}-{job.id}",
        )

        return JSONResponse(
            {
                "ok": True,
                "job_id": job.id,
                "state": "queued",
                "status_url": f"{root_path}/jobs/{job.id}",
            },
            status_code=202,
        )

    async def _dispatch_sync(
        request: Request,
        endpoint: str,
    ) -> JSONResponse:
        """Synchronous dispatcher retained for ``/hooks/classify-batch``."""
        auth_err = await _authenticate(request)
        if auth_err is not None:
            return auth_err

        state = await _ensure_store(shared_state, config)
        store = state["store"]

        lock = _endpoint_locks.setdefault(endpoint, asyncio.Lock())
        async with lock:
            retry_after = await _check_cooldown(store, endpoint)
            if retry_after is not None:
                return JSONResponse(
                    {"ok": False, "error": "too_early", "retry_after": retry_after},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )

            await _set_cooldown(store, endpoint)
            handler = _SYNC_HANDLERS[endpoint]
            response = await handler(request, state)

            try:
                await _record_audit(store, endpoint, response)
            except Exception:  # noqa: BLE001
                logger.exception("Webhook %s: failed to persist audit record", endpoint)

            return response

    async def poll_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /poll`` (async)."""
        return await _dispatch_async(request, "poll")

    async def rescore_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /rescore`` (async)."""
        return await _dispatch_async(request, "rescore")

    async def maintenance_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /maintenance`` (async)."""
        return await _dispatch_async(request, "maintenance")

    async def hooks_poll_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /hooks/poll``.

        .. deprecated::
            This endpoint is deprecated. Use Claude Code routines for
            scheduled feed polling instead. See issue #272.

        Canonical path for the poll webhook; shares cooldown with ``/poll``.
        Accepts an optional ``source_url`` query parameter to poll a single
        source (e.g. ``POST /hooks/poll?source_url=https://example.com/feed``).
        Returns ``202`` with a job id like the canonical ``/poll`` route.
        """
        response = await _dispatch_async(request, "poll")
        if response.status_code != 401:
            logger.warning(
                "Webhook /hooks/poll is deprecated — migrate to Claude Code routines (see #272)"
            )
        return response

    async def hooks_rescore_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /hooks/rescore``.

        .. deprecated::
            This endpoint is deprecated. Use Claude Code routines for
            scheduled feed rescoring instead. See issue #272.

        Canonical path for the rescore webhook; shares cooldown with ``/rescore``.
        Accepts an optional ``limit`` query parameter controlling how many
        entries are rescored (e.g. ``POST /hooks/rescore?limit=50``).
        Returns ``202`` with a job id like the canonical ``/rescore`` route.
        """
        response = await _dispatch_async(request, "rescore")
        if response.status_code != 401:
            logger.warning(
                "Webhook /hooks/rescore is deprecated — migrate to Claude Code routines (see #272)"
            )
        return response

    async def hooks_classify_batch_route(request: Request) -> JSONResponse:
        """Route handler for ``POST /hooks/classify-batch``.

        .. deprecated::
            This endpoint is deprecated. Use Claude Code routines for
            scheduled batch classification instead. See issue #272.

        Classify pending entries in batch using LLM or heuristic mode.
        Accepts optional query parameters:

        - ``entry_type`` (default ``"inbox"``): filter entries by type.
        - ``mode``: ``"llm"`` or ``"heuristic"`` (defaults to config value).

        Unlike the three async endpoints, this one remains synchronous — the
        issue #396 scope was limited to ``/poll``, ``/rescore``, and
        ``/maintenance``.
        """
        response = await _dispatch_sync(request, "classify-batch")
        if response.status_code != 401:
            logger.warning(
                "Webhook /hooks/classify-batch is deprecated"
                " — migrate to Claude Code routines (see #272)"
            )
        return response

    async def jobs_route(request: Request) -> JSONResponse:
        """Route handler for ``GET /jobs/{job_id}``.

        Returns the current state of a background job allocated by one of
        the async endpoints.  Requires the same bearer token as the POST
        endpoints.  Terminal states (``succeeded``, ``failed``) expose the
        full result or error so the scheduler can log the outcome without
        parsing server logs.

        Returns 404 when the job id is unknown (for example because the
        FIFO buffer has evicted it or the server restarted after the job
        was submitted).
        """
        auth_err = await _authenticate(request)
        if auth_err is not None:
            return auth_err

        job_id = request.path_params["job_id"]
        async with _jobs_lock:
            job = _jobs.get(job_id)
            snapshot = _job_to_dict(job) if job is not None else None

        if snapshot is None:
            return JSONResponse(
                {"ok": False, "error": "job not found"},
                status_code=404,
            )
        return JSONResponse({"ok": True, "data": snapshot})

    routes: list[Route] = [
        Route("/poll", poll_route, methods=["POST"]),
        Route("/rescore", rescore_route, methods=["POST"]),
        Route("/maintenance", maintenance_route, methods=["POST"]),
        Route("/hooks/poll", hooks_poll_route, methods=["POST"]),
        Route("/hooks/rescore", hooks_rescore_route, methods=["POST"]),
        Route("/hooks/classify-batch", hooks_classify_batch_route, methods=["POST"]),
        Route("/jobs/{job_id}", jobs_route, methods=["GET"]),
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
                # GET /jobs/{id} is a read-only status poll; schedulers poll
                # it every few seconds while a background job runs and would
                # trivially exhaust the 10/min mutating-endpoint budget.
                # The POST routes above keep their normal rate limit.
                skip_get_path_prefixes=("/jobs/",),
            ),
        ],
    )

    return app
