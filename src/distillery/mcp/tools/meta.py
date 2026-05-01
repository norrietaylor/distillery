"""Meta/cross-cutting tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_status: Lightweight in-protocol health/metadata probe used by
    ``/setup`` and other skills to verify MCP connectivity without requiring
    an out-of-band HTTP ``/health`` curl.  Returns server version, transport,
    tool count, basic store stats, and embedding provider name.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.mcp.tools._common import success_response
from distillery.store.protocol import DistilleryStore

logger = logging.getLogger(__name__)


def _is_remote_db_path(path: str) -> bool:
    """Return True for S3 or MotherDuck URIs that should not be treated as local paths."""
    return path.startswith("s3://") or path.startswith("md:")


def _db_size_bytes(config: DistilleryConfig) -> int | None:
    """Return the database file size in bytes, or None for remote/in-memory paths."""
    raw = config.storage.database_path
    if raw == ":memory:" or _is_remote_db_path(raw):
        return None
    try:
        return Path(os.path.expanduser(raw)).stat().st_size
    except OSError:
        return None


def _max_last_polled_at(sources: list[dict[str, Any]]) -> str | None:
    """Return the most recent ``last_polled_at`` ISO timestamp across *sources*.

    ``sources`` is the list returned by
    :meth:`~distillery.store.protocol.DistilleryStore.list_feed_sources`,
    where each entry has a ``last_polled_at`` value that is either an ISO
    8601 string or ``None``.  Returns the lexicographically-greatest valid
    string (which is also the chronological maximum because every poll
    persists timestamps in the same UTC offset, ``+00:00``), or ``None``
    when no source has ever been polled.

    Used by :func:`_handle_status` so ``last_feed_poll.last_poll_at``
    reflects the per-source liveness column, which is updated synchronously
    by each :class:`~distillery.feeds.poller.FeedPoller` source poll —
    rather than the ``webhook_audit:poll`` metadata row, which is only
    written at the end of a webhook background task and can be lost when
    the host auto-stops mid-cycle (issue #404).
    """
    candidates: list[str] = [
        s["last_polled_at"] for s in sources if isinstance(s.get("last_polled_at"), str)
    ]
    if not candidates:
        return None
    return max(candidates)


async def _handle_status(
    *,
    store: DistilleryStore,
    config: DistilleryConfig,
    embedding_provider: Any,
    tool_count: int,
    transport: str | None,
    started_at: datetime | None,
) -> list[types.TextContent]:
    """Handle the ``distillery_status`` tool.

    Returns a lightweight health/metadata payload suitable for the ``/setup``
    wizard to verify MCP connectivity in-protocol (rather than curling the
    HTTP-only ``/health`` endpoint).

    Args:
        store: Initialised storage backend implementing :class:`DistilleryStore`.
        config: Loaded :class:`~distillery.config.DistilleryConfig`.
        embedding_provider: Active embedding provider (used for its name).
        tool_count: Number of MCP tools registered on the current server.
        transport: ``"stdio"`` or ``"http"`` when known, else ``None``.
        started_at: Server startup timestamp (UTC); ``None`` if unknown.

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    from distillery import __build_sha__, __version__

    degraded_reasons: list[str] = []

    payload: dict[str, Any] = {
        "status": "ok",
        "version": __version__,
        "build_sha": __build_sha__,
        "transport": transport if transport in ("stdio", "http") else "unknown",
        "tool_count": int(tool_count),
    }

    # --- store stats ---------------------------------------------------------
    # Use the async protocol contract rather than poking at the DuckDB-specific
    # ``store.connection`` — keeps this handler backend-agnostic and prevents
    # synchronous DB I/O on the async request path.
    #
    # Client-visible error strings are stable generic codes (not raw exception
    # text) so a durable unqueryable-DB state surfaces as ``degraded`` without
    # leaking DuckDB internals / filesystem paths / query fragments to the
    # caller.  The full exception is logged server-side for operators.
    entry_count: int | None = None
    count_error: str | None = None
    try:
        entry_count = await store.count_entries(filters=None)
    except Exception:  # noqa: BLE001
        count_error = "entry_count_unavailable"
        degraded_reasons.append(count_error)
        logger.exception("distillery_status: count_entries failed")

    db_size = _db_size_bytes(config)
    store_info: dict[str, Any] = {
        "entry_count": entry_count,
        "db_size_bytes": db_size,
    }
    if count_error is not None:
        store_info["entry_count_error"] = count_error
    payload["store"] = store_info

    # --- embedding provider --------------------------------------------------
    payload["embedding_provider"] = (
        getattr(embedding_provider, "model_name", None) or type(embedding_provider).__name__
    )

    # --- feed poll summary (optional, best-effort) ---------------------------
    feed_summary: dict[str, Any] = {"source_count": 0, "last_poll_at": None}
    feed_error: str | None = None
    sources: list[dict[str, Any]] = []
    try:
        sources = await store.list_feed_sources()
        feed_summary["source_count"] = len(sources)
    except Exception:  # noqa: BLE001
        feed_error = "feed_sources_unavailable"
        feed_summary["error"] = feed_error
        degraded_reasons.append(feed_error)
        logger.exception("distillery_status: list_feed_sources failed")

    # Prefer ``MAX(feed_sources.last_polled_at)`` over the webhook audit
    # record: per-source liveness is updated synchronously by each
    # ``_poll_source`` call (see :class:`distillery.feeds.poller.FeedPoller`),
    # so it advances even when the webhook background task is cancelled
    # before it can write ``webhook_audit:poll`` (issue #404).  Fall back
    # to the audit record only when no source has ever been polled — this
    # preserves the previous behaviour for fresh installs whose first
    # poll may have logged an audit but failed to update any source.
    max_last_polled: str | None = _max_last_polled_at(sources)
    if max_last_polled is not None:
        feed_summary["last_poll_at"] = max_last_polled
    else:
        with contextlib.suppress(Exception):
            raw_audit = await store.get_metadata("webhook_audit:poll")
            if raw_audit:
                try:
                    audit = json.loads(raw_audit)
                    if isinstance(audit, dict) and isinstance(audit.get("timestamp"), str):
                        feed_summary["last_poll_at"] = audit["timestamp"]
                except (TypeError, ValueError):
                    pass
    payload["last_feed_poll"] = feed_summary

    # --- readiness probe (issue #363 follow-up) -----------------------------
    # Actively probe that the store can answer a trivial query so operators
    # see durable "DB file mounts but queries fail" states instead of an
    # ``"ok"`` status with silently-null counts.
    probe_fn = getattr(store, "probe_readiness", None)
    if callable(probe_fn):
        raw_ready_error: str | None = None
        try:
            ready, raw_ready_error = await probe_fn()
        except Exception as exc:  # noqa: BLE001
            ready = False
            raw_ready_error = f"{type(exc).__name__}: {exc}"
        payload["store_ready"] = ready
        if not ready:
            # Log the raw probe error server-side; expose only the stable
            # generic code to clients.
            if raw_ready_error:
                logger.warning("distillery_status: readiness probe failed: %s", raw_ready_error)
            stable_code = "readiness_probe_failed"
            payload["store_ready_error"] = stable_code
            degraded_reasons.append(stable_code)

    if degraded_reasons:
        payload["status"] = "degraded"
        payload["degraded_reasons"] = degraded_reasons

    # --- uptime --------------------------------------------------------------
    if started_at is not None:
        try:
            if started_at.tzinfo is None:
                started_aware = started_at.replace(tzinfo=UTC)
            else:
                started_aware = started_at
            payload["uptime_seconds"] = int((datetime.now(UTC) - started_aware).total_seconds())
        except Exception:  # noqa: BLE001
            logger.debug("distillery_status: uptime calculation failed", exc_info=True)

    return success_response(payload)


__all__ = ["_handle_status"]
