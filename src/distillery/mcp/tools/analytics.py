"""Analytics tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_metrics: Aggregate usage and quality metrics from the DuckDB store.
  - distillery_quality: Search and feedback quality summary.
  - distillery_stale: Entries not accessed within a staleness window.
  - distillery_tag_tree: Nested tag hierarchy from active entries.
  - distillery_interests: Interest profile mined from stored entries.
  - distillery_type_schemas: Full metadata schema registry for all entry types.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.mcp.tools._common import (
    error_response,
    success_response,
    validate_type,
)

logger = logging.getLogger(__name__)

# Default stale threshold: entries not accessed in this many days are "stale".
_DEFAULT_STALE_DAYS = 30


# ---------------------------------------------------------------------------
# Storage path helpers (duplicated here to avoid circular imports with server)
# ---------------------------------------------------------------------------


def _is_remote_db_path(path: str) -> bool:
    """Return True for S3 or MotherDuck URIs that should not be treated as local paths."""
    return path.startswith("s3://") or path.startswith("md:")


def _normalize_db_path(raw: str) -> str:
    """Expand ``~`` for local paths; leave cloud URIs (S3/MotherDuck) untouched."""
    if _is_remote_db_path(raw):
        return raw
    return os.path.expanduser(raw)


# ---------------------------------------------------------------------------
# _handle_tag_tree
# ---------------------------------------------------------------------------


async def _handle_tag_tree(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_tag_tree`` tool.

    Fetches all tags from active entries and builds a nested dict tree.
    Each node has a ``count`` (entries whose tags fall under that subtree)
    and a ``children`` dict.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Dict with optional key ``prefix`` (str | None).

    Returns:
        MCP content list with a JSON payload containing ``tree`` and ``prefix``.
    """
    prefix: str | None = arguments.get("prefix")

    def _sync_build_tree() -> dict[str, Any]:
        """Query all tags and build the nested hierarchy synchronously."""
        conn = store.connection
        # Only include active entries to avoid noise from archived ones.
        result = conn.execute("SELECT tags FROM entries WHERE status != 'archived'")
        rows = result.fetchall()

        # Collect all individual tag strings paired with a row index so we
        # can count distinct entries (not tag occurrences) per tree node.
        all_tags: list[tuple[str, int]] = []
        for idx, (tags_col,) in enumerate(rows):
            if tags_col:
                for t in tags_col:
                    all_tags.append((t, idx))

        # Filter by prefix when requested.  A tag matches a prefix when it
        # either equals the prefix exactly or starts with "prefix/".
        if prefix is not None:
            prefix_slash = prefix + "/"
            all_tags = [
                (t, idx) for t, idx in all_tags if t == prefix or t.startswith(prefix_slash)
            ]
            # Strip the prefix (and its trailing slash) from the remaining tags
            # so that the returned tree is rooted at the prefix.
            stripped: list[tuple[str, int]] = []
            for t, idx in all_tags:
                if t == prefix:
                    # The tag is exactly the prefix -- represents the root node.
                    stripped.append(("", idx))
                else:
                    stripped.append((t[len(prefix_slash) :], idx))
            all_tags = stripped

        # Build the tree from path segments.
        # Each node: {"count": int, "children": {segment: node}, "_entry_ids": set}
        # _entry_ids tracks distinct entries to avoid overcounting when one
        # entry has multiple tags under the same namespace.
        root: dict[str, Any] = {"count": 0, "children": {}, "_entry_ids": set()}

        for tag, idx in all_tags:
            if not tag:
                # This tag exactly matched the prefix — count it at the root.
                root["_entry_ids"].add(idx)
                continue
            segments = tag.split("/")
            node = root
            for seg in segments:
                if seg not in node["children"]:
                    node["children"][seg] = {"count": 0, "children": {}, "_entry_ids": set()}
                node = node["children"][seg]
                node["_entry_ids"].add(idx)

        # Convert _entry_ids sets to counts and strip the internal sets.
        def _finalize(n: dict[str, Any]) -> None:
            n["count"] = len(n.pop("_entry_ids"))
            for child in n["children"].values():
                _finalize(child)

        _finalize(root)

        return root

    try:
        tree = await asyncio.to_thread(_sync_build_tree)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_tag_tree")
        return error_response("TAG_TREE_ERROR", f"Failed to build tag tree: {exc}")

    return success_response({"tree": tree, "prefix": prefix})


# ---------------------------------------------------------------------------
# _handle_type_schemas
# ---------------------------------------------------------------------------


async def _handle_type_schemas() -> list[types.TextContent]:
    """Implement the ``distillery_type_schemas`` tool.

    Returns the full metadata schema registry for all known entry types.
    Types with structured schemas (``person``, ``project``, ``digest``,
    ``github``) include their required/optional/constraints definitions.
    Legacy types are reported with empty required/optional dicts.

    Returns:
        MCP content list with a JSON payload containing a ``schemas`` dict.
    """
    from distillery.models import TYPE_METADATA_SCHEMAS, EntryType

    all_schemas: dict[str, Any] = {}

    # For each known entry type, include its schema (or empty dicts for legacy).
    for et in EntryType:
        schema = TYPE_METADATA_SCHEMAS.get(et.value, {})
        all_schemas[et.value] = {
            "required": schema.get("required", {}),
            "optional": schema.get("optional", {}),
        }
        if "constraints" in schema:
            all_schemas[et.value]["constraints"] = schema["constraints"]

    return success_response({"schemas": all_schemas})


# ---------------------------------------------------------------------------
# _handle_metrics
# ---------------------------------------------------------------------------


async def _handle_metrics(
    store: Any,
    config: DistilleryConfig,
    embedding_provider: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """
    Aggregate usage and quality metrics from the DuckDB store for the Distillery instance.

    Parameters:
        store: Initialised store with a live ``connection``.
        config: Loaded :class:`~distillery.config.DistilleryConfig`.
        embedding_provider: Active embedding provider (used to report model metadata).
        arguments: Tool arguments; supports optional ``period_days`` (int) specifying
            the lookback window in days (must be >= 1).

    Returns:
        MCP content list with aggregated metrics (entries, activity, search, quality,
        staleness, and storage sections).
    """
    # --- validate period_days -----------------------------------------------
    period_days_raw = arguments.get("period_days", 30)
    err_period = validate_type(arguments, "period_days", int, "integer")
    if err_period:
        return error_response("VALIDATION_ERROR", err_period)
    period_days = int(period_days_raw) if period_days_raw is not None else 30
    if period_days < 1:
        return error_response("VALIDATION_ERROR", "Field 'period_days' must be >= 1")

    try:
        metrics = await asyncio.to_thread(
            _sync_gather_metrics, store, config, embedding_provider, period_days
        )
        return success_response(metrics)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering metrics")
        return error_response("METRICS_ERROR", f"Failed to gather metrics: {exc}")


def _sync_gather_metrics(
    store: Any,
    config: DistilleryConfig,
    embedding_provider: Any,
    period_days: int,
) -> dict[str, Any]:
    """
    Gather comprehensive DuckDB-backed metrics for Distillery.

    Collects entry counts, activity windows, search statistics (if available),
    feedback quality (if available), staleness estimates, and storage/embedding
    metadata; missing auxiliary tables yield zeroed metrics.

    Parameters:
        store: Initialized DuckDBStore exposing a live ``connection``.
        config: Loaded DistilleryConfig (used for storage path resolution).
        embedding_provider: Active embedding provider (used to report model metadata).
        period_days: Number of days for the "recent" activity/search window.

    Returns:
        A JSON-serializable dict with keys: ``entries``, ``activity``, ``search``,
        ``quality``, ``staleness``, and ``storage``, each containing aggregated metrics.
    """
    conn = store.connection

    # ------------------------------------------------------------------ #
    # entries section                                                      #
    # ------------------------------------------------------------------ #
    total_row = conn.execute("SELECT COUNT(*) FROM entries WHERE status != 'archived'").fetchone()
    total_entries: int = total_row[0] if total_row else 0

    type_rows = conn.execute(
        "SELECT entry_type, COUNT(*) AS cnt FROM entries "
        "WHERE status != 'archived' GROUP BY entry_type ORDER BY cnt DESC"
    ).fetchall()
    by_type = {row[0]: row[1] for row in type_rows}

    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM entries GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    by_status = {row[0]: row[1] for row in status_rows}

    source_rows = conn.execute(
        "SELECT source, COUNT(*) AS cnt FROM entries "
        "WHERE status != 'archived' GROUP BY source ORDER BY cnt DESC"
    ).fetchall()
    by_source = {row[0]: row[1] for row in source_rows}

    entries_section: dict[str, Any] = {
        "total": total_entries,
        "by_type": by_type,
        "by_status": by_status,
        "by_source": by_source,
    }

    # ------------------------------------------------------------------ #
    # activity section                                                     #
    # ------------------------------------------------------------------ #
    def _count_where(column: str, days: int) -> int:
        """
        Count entries in the ``entries`` table whose timestamp in the given column
        is within the past ``days``.

        Parameters:
            column: Name of a datetime column in the ``entries`` table.
            days: Number of days for the lookback window.

        Returns:
            int: The number of rows matching the condition.
        """
        row = conn.execute(
            f"SELECT COUNT(*) FROM entries "
            f"WHERE {column} > CURRENT_TIMESTAMP - (? * INTERVAL '1 day')",
            [days],
        ).fetchone()
        return row[0] if row else 0

    activity_section: dict[str, Any] = {
        "created_7d": _count_where("created_at", 7),
        "created_30d": _count_where("created_at", 30),
        "created_90d": _count_where("created_at", 90),
        "updated_7d": _count_where("updated_at", 7),
        "updated_30d": _count_where("updated_at", 30),
        "updated_90d": _count_where("updated_at", 90),
        f"created_{period_days}d": _count_where("created_at", period_days),
        f"updated_{period_days}d": _count_where("updated_at", period_days),
    }

    # ------------------------------------------------------------------ #
    # search section (search_log table may not exist yet)                 #
    # ------------------------------------------------------------------ #
    search_section: dict[str, Any] = {
        "total_searches": 0,
        "searches_7d": 0,
        "searches_30d": 0,
        f"searches_{period_days}d": 0,
        "avg_results_per_search": 0.0,
    }
    try:
        _table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'search_log'"
        ).fetchone()
        if _table_exists and _table_exists[0] > 0:
            total_searches_row = conn.execute("SELECT COUNT(*) FROM search_log").fetchone()
            total_searches: int = total_searches_row[0] if total_searches_row else 0

            def _count_searches(days: int) -> int:
                """
                Count search log entries with timestamps within the last ``days`` days.

                Parameters:
                    days: Number of days to look back from the current time.

                Returns:
                    int: Number of search_log rows with timestamp > now - ``days`` days.
                """
                r = conn.execute(
                    f"SELECT COUNT(*) FROM search_log "
                    f"WHERE timestamp > CURRENT_TIMESTAMP - INTERVAL '{days} days'"
                ).fetchone()
                return r[0] if r else 0

            avg_row = conn.execute(
                "SELECT AVG(array_length(result_entry_ids)) FROM search_log"
            ).fetchone()
            avg_results = float(avg_row[0]) if avg_row and avg_row[0] is not None else 0.0

            search_section = {
                "total_searches": total_searches,
                "searches_7d": _count_searches(7),
                "searches_30d": _count_searches(30),
                f"searches_{period_days}d": _count_searches(period_days),
                "avg_results_per_search": round(avg_results, 4),
            }
    except Exception:  # noqa: BLE001
        # Table doesn't exist or is not accessible; return zeros.
        pass

    # ------------------------------------------------------------------ #
    # quality section (feedback_log table may not exist yet)              #
    # ------------------------------------------------------------------ #
    quality_section: dict[str, Any] = {
        "total_feedback": 0,
        "feedback_30d": 0,
        "positive_rate": 0.0,
    }
    try:
        _fb_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'feedback_log'"
        ).fetchone()
        if _fb_exists and _fb_exists[0] > 0:
            total_fb_row = conn.execute("SELECT COUNT(*) FROM feedback_log").fetchone()
            total_fb: int = total_fb_row[0] if total_fb_row else 0

            positive_row = conn.execute(
                "SELECT COUNT(*) FROM feedback_log WHERE signal = 'positive'"
            ).fetchone()
            positive_count: int = positive_row[0] if positive_row else 0

            fb_30d_row = conn.execute(
                "SELECT COUNT(*) FROM feedback_log "
                "WHERE timestamp > CURRENT_TIMESTAMP - INTERVAL '30 days'"
            ).fetchone()
            fb_30d: int = fb_30d_row[0] if fb_30d_row else 0

            positive_rate = (positive_count / total_fb) if total_fb > 0 else 0.0

            quality_section = {
                "total_feedback": total_fb,
                "feedback_30d": fb_30d,
                "positive_rate": round(positive_rate, 4),
            }
    except Exception:  # noqa: BLE001
        # Table doesn't exist or is not accessible; return zeros.
        pass

    # ------------------------------------------------------------------ #
    # staleness section                                                    #
    # ------------------------------------------------------------------ #
    stale_days = _DEFAULT_STALE_DAYS

    # accessed_at column may not exist yet (added by T02.1).
    # Fall back to updated_at if the column is absent.
    stale_count = 0
    stale_by_type: dict[str, int] = {}
    try:
        stale_row = conn.execute(
            f"SELECT COUNT(*) FROM entries "
            f"WHERE status != 'archived' "
            f"AND COALESCE(accessed_at, updated_at) < "
            f"CURRENT_TIMESTAMP - INTERVAL '{stale_days} days'"
        ).fetchone()
        stale_count = stale_row[0] if stale_row else 0

        stale_type_rows = conn.execute(
            f"SELECT entry_type, COUNT(*) AS cnt FROM entries "
            f"WHERE status != 'archived' "
            f"AND COALESCE(accessed_at, updated_at) < "
            f"CURRENT_TIMESTAMP - INTERVAL '{stale_days} days' "
            f"GROUP BY entry_type ORDER BY cnt DESC"
        ).fetchall()
        stale_by_type = {row[0]: row[1] for row in stale_type_rows}
    except Exception:  # noqa: BLE001
        # If accessed_at column doesn't exist, try without it.
        try:
            stale_row = conn.execute(
                f"SELECT COUNT(*) FROM entries "
                f"WHERE status != 'archived' "
                f"AND updated_at < CURRENT_TIMESTAMP - INTERVAL '{stale_days} days'"
            ).fetchone()
            stale_count = stale_row[0] if stale_row else 0

            stale_type_rows = conn.execute(
                f"SELECT entry_type, COUNT(*) AS cnt FROM entries "
                f"WHERE status != 'archived' "
                f"AND updated_at < CURRENT_TIMESTAMP - INTERVAL '{stale_days} days' "
                f"GROUP BY entry_type ORDER BY cnt DESC"
            ).fetchall()
            stale_by_type = {row[0]: row[1] for row in stale_type_rows}
        except Exception:  # noqa: BLE001
            pass

    staleness_section: dict[str, Any] = {
        "stale_count": stale_count,
        "stale_days": stale_days,
        "by_type": stale_by_type,
    }

    # ------------------------------------------------------------------ #
    # storage section                                                      #
    # ------------------------------------------------------------------ #
    db_path = _normalize_db_path(config.storage.database_path)
    db_file_size: int | None = None
    if db_path != ":memory:" and not _is_remote_db_path(db_path):
        try:
            db_file_size = Path(db_path).stat().st_size
        except OSError:
            db_file_size = None

    model_name = getattr(embedding_provider, "model_name", "unknown")
    embedding_dimensions = getattr(embedding_provider, "dimensions", None)

    storage_section: dict[str, Any] = {
        "db_file_size": db_file_size,
        "embedding_model": model_name,
        "embedding_dimensions": embedding_dimensions,
    }

    return {
        "entries": entries_section,
        "activity": activity_section,
        "search": search_section,
        "quality": quality_section,
        "staleness": staleness_section,
        "storage": storage_section,
    }


# ---------------------------------------------------------------------------
# _handle_quality
# ---------------------------------------------------------------------------


async def _handle_quality(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """
    Aggregate search and feedback metrics and produce a quality summary payload.

    Reads the read-only ``search_log`` and ``feedback_log`` tables and computes
    ``total_searches``, ``total_feedback``, ``positive_rate``, ``avg_result_count``,
    and an optional ``per_type_breakdown``. If ``entry_type`` is provided in
    ``arguments``, results are filtered to that entry type when possible.

    Parameters:
        store: Initialized DuckDBStore providing access to log tables.
        arguments: Tool arguments; accepts optional ``entry_type`` (str) to filter results.

    Returns:
        MCP content list with a single JSON ``TextContent`` block containing the
        computed quality metrics.
    """
    entry_type_filter: str | None = arguments.get("entry_type")

    try:
        result = await asyncio.to_thread(_sync_gather_quality, store, entry_type_filter)
        return success_response(result)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering quality metrics")
        return error_response("QUALITY_ERROR", f"Failed to gather quality metrics: {exc}")


def _sync_gather_quality(
    store: Any,
    entry_type_filter: str | None,
) -> dict[str, Any]:
    """
    Compute aggregated quality metrics from the DuckDB-backed store.

    Handles missing ``search_log`` or ``feedback_log`` tables by returning zeroed
    metrics for the missing data.

    Parameters:
        store: Initialized DuckDBStore exposing a live ``connection`` to execute queries.
        entry_type_filter: Optional entry-type to include a per-type feedback breakdown.

    Returns:
        A dictionary containing:
            - total_searches (int): Total number of search events (0 if unavailable).
            - total_feedback (int): Total number of feedback records (0 if unavailable).
            - positive_rate (float): Fraction of feedback that is positive, rounded to 4 decimals.
            - avg_result_count (float): Average number of results per search, rounded to 4 decimals.
            - per_type_breakdown (dict): Mapping of the ``entry_type_filter`` to a dict with
              ``total_feedback``, ``positive_count``, and ``positive_rate``. Empty if no filter
              provided or data unavailable.
    """
    conn = store.connection

    total_searches = 0
    total_feedback = 0
    positive_count = 0
    avg_result_count = 0.0

    try:
        sl_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'search_log'"
        ).fetchone()
        if sl_exists and sl_exists[0] > 0:
            row = conn.execute("SELECT COUNT(*) FROM search_log").fetchone()
            total_searches = row[0] if row else 0

            avg_row = conn.execute(
                "SELECT AVG(array_length(result_entry_ids)) FROM search_log"
            ).fetchone()
            avg_result_count = float(avg_row[0]) if avg_row and avg_row[0] is not None else 0.0
    except Exception:  # noqa: BLE001
        pass

    try:
        fl_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'feedback_log'"
        ).fetchone()
        if fl_exists and fl_exists[0] > 0:
            row = conn.execute("SELECT COUNT(*) FROM feedback_log").fetchone()
            total_feedback = row[0] if row else 0

            pos_row = conn.execute(
                "SELECT COUNT(*) FROM feedback_log WHERE signal = 'positive'"
            ).fetchone()
            positive_count = pos_row[0] if pos_row else 0
    except Exception:  # noqa: BLE001
        pass

    positive_rate = (positive_count / total_feedback) if total_feedback > 0 else 0.0

    # Per-type breakdown: join feedback_log -> search_log -> entries
    per_type_breakdown: dict[str, Any] = {}
    if entry_type_filter is not None:
        try:
            sl_exists2 = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'search_log'"
            ).fetchone()
            fl_exists2 = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'feedback_log'"
            ).fetchone()
            if (sl_exists2 and sl_exists2[0] > 0) and (fl_exists2 and fl_exists2[0] > 0):
                type_fb_row = conn.execute(
                    "SELECT COUNT(*) FROM feedback_log fl "
                    "JOIN entries e ON fl.entry_id = e.id "
                    "WHERE e.entry_type = ?",
                    [entry_type_filter],
                ).fetchone()
                type_fb = type_fb_row[0] if type_fb_row else 0

                type_pos_row = conn.execute(
                    "SELECT COUNT(*) FROM feedback_log fl "
                    "JOIN entries e ON fl.entry_id = e.id "
                    "WHERE e.entry_type = ? AND fl.signal = 'positive'",
                    [entry_type_filter],
                ).fetchone()
                type_pos = type_pos_row[0] if type_pos_row else 0

                type_rate = (type_pos / type_fb) if type_fb > 0 else 0.0
                per_type_breakdown[entry_type_filter] = {
                    "total_feedback": type_fb,
                    "positive_count": type_pos,
                    "positive_rate": round(type_rate, 4),
                }
        except Exception:  # noqa: BLE001
            pass

    return {
        "total_searches": total_searches,
        "total_feedback": total_feedback,
        "positive_rate": round(positive_rate, 4),
        "avg_result_count": round(avg_result_count, 4),
        "per_type_breakdown": per_type_breakdown,
    }


# ---------------------------------------------------------------------------
# _handle_stale
# ---------------------------------------------------------------------------


async def _handle_stale(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_stale`` tool.

    Returns entries that have not been accessed within the configured
    staleness window.  An entry's last access time is determined by
    ``COALESCE(accessed_at, updated_at)`` so that entries without an
    explicit access timestamp fall back to their last modification time.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        config: The loaded Distillery configuration.
        arguments: Tool argument dict.  Accepts optional ``days`` (int),
            ``limit`` (int), and ``entry_type`` (str).

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    # --- validate days -------------------------------------------------------
    err_days = validate_type(arguments, "days", int, "integer")
    if err_days:
        return error_response("VALIDATION_ERROR", err_days)
    days_raw = arguments.get("days")
    days: int = int(days_raw) if days_raw is not None else config.classification.stale_days
    if days < 1:
        return error_response("VALIDATION_ERROR", "Field 'days' must be >= 1")

    # --- validate limit -------------------------------------------------------
    err_limit = validate_type(arguments, "limit", int, "integer")
    if err_limit:
        return error_response("VALIDATION_ERROR", err_limit)
    limit_raw = arguments.get("limit")
    limit: int = int(limit_raw) if limit_raw is not None else 20
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")

    # --- validate entry_type -------------------------------------------------
    entry_type_filter: str | None = arguments.get("entry_type")
    if entry_type_filter is not None and not isinstance(entry_type_filter, str):
        return error_response("VALIDATION_ERROR", "Field 'entry_type' must be a string")

    try:
        stale_entries = await asyncio.to_thread(
            _sync_gather_stale, store, days, limit, entry_type_filter
        )
        return success_response(
            {
                "days_threshold": days,
                "entry_type_filter": entry_type_filter,
                "stale_count": len(stale_entries),
                "entries": stale_entries,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering stale entries")
        return error_response("STALE_ERROR", f"Failed to gather stale entries: {exc}")


def _sync_gather_stale(
    store: Any,
    days: int,
    limit: int,
    entry_type_filter: str | None,
) -> list[dict[str, Any]]:
    """
    Return entries whose last access (accessed_at or updated_at) is older than the given days.

    Parameters:
        store: Initialized DuckDBStore used to query entries.
        days: Staleness threshold in days; entries last accessed strictly earlier than
            now - days are returned.
        limit: Maximum number of entries to return.
        entry_type_filter: Optional entry_type value to restrict results to a single type.

    Returns:
        List of stale entry summaries ordered stalest-first. Each dict contains:
            - id: entry identifier
            - content_preview: first 200 characters of the content (empty string if None)
            - entry_type: entry type string
            - author: author string
            - project: project string or None
            - last_accessed: ISO 8601 timestamp string of the last access or None
            - days_since_access: integer days since last access or None
    """
    conn = store.connection

    params: list[Any] = [days]
    type_clause = ""
    if entry_type_filter is not None:
        type_clause = " AND entry_type = ?"
        params.append(entry_type_filter)
    params.append(limit)

    sql = f"""
        SELECT
            id,
            content,
            entry_type,
            author,
            project,
            COALESCE(accessed_at, updated_at) AS last_accessed
        FROM entries
        WHERE status != 'archived'
          AND COALESCE(accessed_at, updated_at) < NOW() - INTERVAL (CAST(? AS INT)) DAYS
          {type_clause}
        ORDER BY last_accessed ASC
        LIMIT ?
    """

    rows = conn.execute(sql, params).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        entry_id, content, entry_type, author, project, last_accessed = row
        content_preview = (content or "")[:200]
        # Calculate days since access
        if last_accessed is not None:
            if hasattr(last_accessed, "tzinfo") and last_accessed.tzinfo is None:
                last_accessed_aware = last_accessed.replace(tzinfo=UTC)
            else:
                last_accessed_aware = last_accessed
            now = datetime.now(UTC)
            days_since = (now - last_accessed_aware).days
            last_accessed_iso = last_accessed_aware.isoformat()
        else:
            days_since = None
            last_accessed_iso = None

        result.append(
            {
                "id": entry_id,
                "content_preview": content_preview,
                "entry_type": entry_type,
                "author": author,
                "project": project,
                "last_accessed": last_accessed_iso,
                "days_since_access": days_since,
            }
        )

    return result


# ---------------------------------------------------------------------------
# _handle_interests
# ---------------------------------------------------------------------------


async def _handle_interests(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_interests`` tool.

    Builds an :class:`~distillery.feeds.interests.InterestProfile` by mining
    the active entries in *store* and returns it as a JSON payload.

    Args:
        store: An initialised storage backend.
        config: The current :class:`~distillery.config.DistilleryConfig`.
        arguments: Parsed tool arguments dict (``recency_days``, ``top_n``).

    Returns:
        A structured MCP success or error response.
    """
    from distillery.feeds.interests import InterestExtractor

    recency_days_raw = arguments.get("recency_days", 90)
    try:
        recency_days = int(recency_days_raw)
    except (TypeError, ValueError):
        return error_response(
            "INVALID_FIELD",
            f"recency_days must be an integer, got: {recency_days_raw!r}",
        )
    if recency_days <= 0:
        return error_response(
            "INVALID_FIELD",
            f"recency_days must be a positive integer, got: {recency_days}",
        )

    top_n_raw = arguments.get("top_n", 20)
    try:
        top_n = int(top_n_raw)
    except (TypeError, ValueError):
        return error_response(
            "INVALID_FIELD",
            f"top_n must be an integer, got: {top_n_raw!r}",
        )
    if top_n <= 0:
        return error_response(
            "INVALID_FIELD",
            f"top_n must be a positive integer, got: {top_n}",
        )

    extractor = InterestExtractor(
        store=store,
        recency_days=recency_days,
        top_n=top_n,
    )
    try:
        profile = await extractor.extract()
    except Exception as exc:  # noqa: BLE001
        logger.exception("distillery_interests: extraction failed")
        return error_response("EXTRACTION_ERROR", f"Interest extraction failed: {exc}")

    return success_response(
        {
            "top_tags": [[tag, weight] for tag, weight in profile.top_tags],
            "bookmark_domains": profile.bookmark_domains,
            "tracked_repos": profile.tracked_repos,
            "expertise_areas": profile.expertise_areas,
            "watched_sources": profile.watched_sources,
            "suggestion_context": profile.suggestion_context,
            "entry_count": profile.entry_count,
            "generated_at": profile.generated_at.isoformat(),
        }
    )


__all__ = [
    "_DEFAULT_STALE_DAYS",
    "_handle_interests",
    "_handle_metrics",
    "_handle_quality",
    "_handle_stale",
    "_handle_tag_tree",
    "_handle_type_schemas",
]
