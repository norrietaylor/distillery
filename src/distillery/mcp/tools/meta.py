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


async def _handle_status(
    *,
    store: Any,
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
        store: Initialised storage backend.
        config: Loaded :class:`~distillery.config.DistilleryConfig`.
        embedding_provider: Active embedding provider (used for its name).
        tool_count: Number of MCP tools registered on the current server.
        transport: ``"stdio"`` or ``"http"`` when known, else ``None``.
        started_at: Server startup timestamp (UTC); ``None`` if unknown.

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    from distillery import __build_sha__, __version__

    payload: dict[str, Any] = {
        "status": "ok",
        "version": __version__,
        "build_sha": __build_sha__,
        "transport": transport if transport in ("stdio", "http") else "unknown",
        "tool_count": int(tool_count),
    }

    # --- store stats ---------------------------------------------------------
    entry_count: int | None = None
    try:
        conn = getattr(store, "connection", None)
        if conn is not None:
            row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
            entry_count = int(row[0]) if row else 0
    except Exception:  # noqa: BLE001
        logger.debug("distillery_status: entry_count query failed", exc_info=True)

    db_size = _db_size_bytes(config)
    store_info: dict[str, Any] = {
        "entry_count": entry_count,
        "db_size_bytes": db_size,
    }
    payload["store"] = store_info

    # --- embedding provider --------------------------------------------------
    payload["embedding_provider"] = (
        getattr(embedding_provider, "model_name", None) or type(embedding_provider).__name__
    )

    # --- feed poll summary (optional, best-effort) ---------------------------
    feed_summary: dict[str, Any] = {"source_count": 0, "last_poll_at": None}
    try:
        sources = await store.list_feed_sources()
        feed_summary["source_count"] = len(sources)
    except Exception:  # noqa: BLE001
        logger.debug("distillery_status: list_feed_sources failed", exc_info=True)

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
