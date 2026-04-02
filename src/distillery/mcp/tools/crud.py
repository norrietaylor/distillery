"""CRUD tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_status: DB statistics
  - distillery_store: Create and persist a new entry
  - distillery_get: Retrieve an entry by ID
  - distillery_update: Update an existing entry
  - distillery_list: List entries with optional filtering and pagination
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.mcp.tools._common import (
    error_response,
    success_response,
    validate_required,
    validate_type,
)
from distillery.mcp.tools._errors import validate_limit

logger = logging.getLogger(__name__)

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
# CRUD-related constants
# ---------------------------------------------------------------------------

# Valid entry_type values (mirrors EntryType enum).
_VALID_ENTRY_TYPES = {
    "session",
    "bookmark",
    "minutes",
    "meeting",
    "reference",
    "idea",
    "inbox",
    "person",
    "project",
    "digest",
    "github",
    "feed",
}

# Valid status values (mirrors EntryStatus enum).
_VALID_STATUSES = {"active", "pending_review", "archived"}

# Fields that callers may never overwrite via distillery_update.
_IMMUTABLE_FIELDS = {"id", "created_at", "source"}

# Default similarity threshold for deduplication warnings.
_DEFAULT_DEDUP_THRESHOLD = 0.92
_DEFAULT_DEDUP_LIMIT = 3


# ---------------------------------------------------------------------------
# _handle_status and its synchronous helper
# ---------------------------------------------------------------------------


async def _handle_status(
    store: Any,
    embedding_provider: Any,
    config: DistilleryConfig,
) -> list[types.TextContent]:
    """Implement the ``distillery_status`` tool.

    Queries the DuckDB store for aggregate statistics and returns them as a
    JSON payload.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        embedding_provider: The active embedding provider instance.
        config: The loaded Distillery configuration.

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    try:
        stats = await asyncio.to_thread(_sync_gather_stats, store, embedding_provider, config)
        return success_response(stats)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering status stats")
        return error_response("STATUS_ERROR", f"Failed to gather status: {exc}")


def _sync_gather_stats(
    store: Any,
    embedding_provider: Any,
    config: DistilleryConfig,
) -> dict[str, Any]:
    """Synchronous helper that queries DuckDB for status statistics.

    Runs inside ``asyncio.to_thread`` so that blocking DuckDB calls do not
    stall the event loop.

    Args:
        store: Initialised ``DuckDBStore`` whose ``connection`` property is
            available.
        embedding_provider: Active embedding provider (for model metadata).
        config: Loaded ``DistilleryConfig``.

    Returns:
        A dict suitable for JSON serialisation.
    """
    conn = store.connection

    # Total entry count (all statuses).
    total_row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    total_entries: int = total_row[0] if total_row else 0

    # Counts grouped by entry_type.
    type_rows = conn.execute(
        "SELECT entry_type, COUNT(*) AS cnt FROM entries GROUP BY entry_type ORDER BY cnt DESC"
    ).fetchall()
    entries_by_type = {row[0]: row[1] for row in type_rows}

    # Counts grouped by status.
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM entries GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    entries_by_status = {row[0]: row[1] for row in status_rows}

    # Database file size.
    db_path = _normalize_db_path(config.storage.database_path)
    database_size_bytes: int | None = None
    if db_path != ":memory:" and not _is_remote_db_path(db_path):
        try:
            database_size_bytes = Path(db_path).stat().st_size
        except OSError:
            database_size_bytes = None

    # Embedding model info.
    model_name = getattr(embedding_provider, "model_name", "unknown")
    embedding_dimensions = getattr(embedding_provider, "dimensions", None)

    # Embedding budget usage.
    from distillery.mcp.budget import get_daily_usage

    embedding_usage_today = 0
    embedding_budget_daily = config.rate_limit.embedding_budget_daily
    with contextlib.suppress(Exception):
        embedding_usage_today = get_daily_usage(conn)

    # Storage warnings.
    warnings: list[str] = []
    rl = config.rate_limit
    if database_size_bytes is not None and rl.max_db_size_mb > 0:
        size_mb = database_size_bytes / (1024 * 1024)
        warn_threshold_mb = rl.max_db_size_mb * rl.warn_db_size_pct / 100
        if size_mb >= rl.max_db_size_mb:
            warnings.append(
                f"Database size ({size_mb:.1f} MB) has reached the limit "
                f"({rl.max_db_size_mb} MB). New writes will be rejected."
            )
        elif size_mb >= warn_threshold_mb:
            warnings.append(
                f"Database size ({size_mb:.1f} MB) is at "
                f"{size_mb / rl.max_db_size_mb * 100:.0f}% of the "
                f"{rl.max_db_size_mb} MB limit."
            )

    if embedding_budget_daily > 0 and embedding_usage_today >= embedding_budget_daily:
        warnings.append(
            f"Daily embedding budget exhausted: {embedding_usage_today}/{embedding_budget_daily} "
            "calls used."
        )

    result: dict[str, Any] = {
        "status": "ok",
        "total_entries": total_entries,
        "entries_by_type": entries_by_type,
        "entries_by_status": entries_by_status,
        "database_size_bytes": database_size_bytes,
        "embedding_model": model_name,
        "embedding_dimensions": embedding_dimensions,
        "database_path": db_path,
        "embedding_usage_today": embedding_usage_today,
        "embedding_budget_daily": embedding_budget_daily,
    }
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# _handle_store
# ---------------------------------------------------------------------------


async def _handle_store(
    store: Any,
    arguments: dict[str, Any],
    cfg: DistilleryConfig | None = None,
    created_by: str = "",
) -> list[types.TextContent]:
    """
    Create and persist a new Entry from the provided arguments, run deduplication and a non-fatal conflict check, and return the stored entry id along with any warnings or conflict candidates.

    Parameters:
        arguments (dict): MCP tool arguments. Required keys: `content`, `entry_type`, `author`. Optional keys: `project`, `tags` (list), `metadata` (dict), `dedup_threshold` (number), `dedup_limit` (int).
        cfg (DistilleryConfig | None): Optional configuration used to derive classification/conflict thresholds; when omitted a default conflict threshold of 0.60 is used.

    Returns:
        list[types.TextContent]: MCP content list containing a JSON-serializable object with at least `entry_id`. May also include:
          - `warnings`: list of similar-entry summaries (id, score, content_preview) when near-duplicates were found,
          - `warning_message`: human-readable summary of warnings,
          - `conflicts`: list of conflict candidate objects (entry_id, content_preview, similarity_score, conflict_reasoning),
          - `conflict_message`: guidance message when conflict candidates are returned.
    """
    from distillery.mcp.budget import EmbeddingBudgetError, record_and_check
    from distillery.models import Entry, EntrySource, EntryType

    # --- input validation ---------------------------------------------------
    err = validate_required(arguments, "content", "entry_type", "author")
    if err:
        return error_response("INVALID_PARAMS", err)

    entry_type_str = arguments["entry_type"]
    if entry_type_str not in _VALID_ENTRY_TYPES:
        return error_response(
            "INVALID_PARAMS",
            f"Invalid entry_type {entry_type_str!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
        )

    tags_err = validate_type(arguments, "tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_PARAMS", tags_err)

    metadata_err = validate_type(arguments, "metadata", dict, "object")
    if metadata_err:
        return error_response("INVALID_PARAMS", metadata_err)

    dedup_threshold = arguments.get("dedup_threshold", _DEFAULT_DEDUP_THRESHOLD)
    dedup_limit = arguments.get("dedup_limit", _DEFAULT_DEDUP_LIMIT)

    if not isinstance(dedup_threshold, (int, float)):
        return error_response("INVALID_PARAMS", "Field 'dedup_threshold' must be a number")
    if not isinstance(dedup_limit, int):
        return error_response("INVALID_PARAMS", "Field 'dedup_limit' must be an integer")

    # --- reserved prefix enforcement ----------------------------------------
    # Sources that are permitted to use tags under reserved top-level prefixes.
    _reserved_allowed_sources: set[str] = {EntrySource.IMPORT.value}
    entry_source_str: str = str(arguments.get("source", EntrySource.CLAUDE_CODE.value))
    if cfg is not None and cfg.tags.reserved_prefixes:
        tags_raw = list(arguments.get("tags") or [])
        for tag in tags_raw:
            if not isinstance(tag, str):
                return error_response(
                    "INVALID_PARAMS", f"Each tag must be a string, got: {type(tag).__name__}"
                )
        tags_to_check: list[str] = tags_raw
        if entry_source_str not in _reserved_allowed_sources:
            for tag in tags_to_check:
                top = tag.split("/")[0]
                if top in cfg.tags.reserved_prefixes:
                    return error_response(
                        "RESERVED_PREFIX",
                        f"Tag {tag!r} uses reserved prefix {top!r}. "
                        "Only internal sources may use this namespace.",
                    )

    # --- db size check (cheap, run first) ------------------------------------
    if cfg is not None and cfg.rate_limit.max_db_size_mb > 0:
        db_path = _normalize_db_path(cfg.storage.database_path)
        if db_path != ":memory:" and not _is_remote_db_path(db_path):
            try:
                size_mb = Path(db_path).stat().st_size / (1024 * 1024)
                if size_mb >= cfg.rate_limit.max_db_size_mb:
                    return error_response(
                        "DB_SIZE_EXCEEDED",
                        f"Database size ({size_mb:.1f} MB) exceeds limit "
                        f"({cfg.rate_limit.max_db_size_mb} MB). "
                        "Delete old entries or increase rate_limit.max_db_size_mb.",
                    )
            except OSError:
                pass  # can't stat, skip check

    # --- embedding budget check (store + dedup + conflict = 3 embeds) ------
    if cfg is not None:
        try:
            record_and_check(store.connection, cfg.rate_limit.embedding_budget_daily, count=3)
        except EmbeddingBudgetError as exc:
            return error_response("BUDGET_EXCEEDED", str(exc))

    # --- build entry --------------------------------------------------------
    try:
        # Determine EntrySource from arguments.
        try:
            resolved_source = EntrySource(entry_source_str)
        except ValueError:
            resolved_source = EntrySource.CLAUDE_CODE

        entry = Entry(
            content=arguments["content"],
            entry_type=EntryType(entry_type_str),
            source=resolved_source,
            author=arguments["author"],
            project=arguments.get("project"),
            tags=list(arguments.get("tags") or []),
            metadata=dict(arguments.get("metadata") or {}),
            created_by=created_by,
        )
    except Exception as exc:  # noqa: BLE001
        return error_response("INVALID_PARAMS", f"Failed to construct entry: {exc}")

    # --- persist ------------------------------------------------------------
    try:
        entry_id = await store.store(entry)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error storing entry")
        return error_response("STORE_ERROR", f"Failed to store entry: {exc}")

    # --- deduplication check ------------------------------------------------
    warnings: list[dict[str, Any]] = []
    try:
        similar = await store.find_similar(
            content=entry.content,
            threshold=float(dedup_threshold),
            limit=dedup_limit + 1,  # +1 because the new entry itself may appear
        )
        for result in similar:
            if result.entry.id != entry_id:
                warnings.append(
                    {
                        "similar_entry_id": result.entry.id,
                        "score": round(result.score, 4),
                        "content_preview": result.entry.content[:120],
                    }
                )
                if len(warnings) >= dedup_limit:
                    break
    except Exception as exc:  # noqa: BLE001
        logger.warning("find_similar failed during dedup check: %s", exc)
        # Non-fatal: still return the stored entry_id.

    # --- conflict check -------------------------------------------------------
    # Non-fatal: wrap in try/except so a conflict-checker failure never blocks
    # the store operation.  We return conflict_candidates (similar entries with
    # their content) so the calling LLM can evaluate them without us making an
    # LLM call ourselves.
    try:
        from distillery.classification.conflict import ConflictChecker

        conflict_threshold = float(
            cfg.classification.conflict_threshold if cfg is not None else 0.60
        )
        conflict_checker = ConflictChecker(store=store, threshold=conflict_threshold)
        conflict_similar = await store.find_similar(
            content=entry.content,
            threshold=conflict_threshold,
            limit=5,
        )
        if conflict_similar:
            conflicts = []
            for result in conflict_similar:
                if result.entry.id == entry_id:
                    continue
                lines = result.entry.content.splitlines()
                preview = lines[0][:120] if lines else result.entry.content[:120]
                prompt = conflict_checker.build_prompt(entry.content, result.entry.content)
                conflicts.append(
                    {
                        "entry_id": result.entry.id,
                        "content_preview": preview,
                        "similarity_score": round(result.score, 4),
                        "conflict_reasoning": prompt,
                    }
                )
            if conflicts:
                response_data: dict[str, Any] = {"entry_id": entry_id}
                if warnings:
                    response_data["warnings"] = warnings
                    response_data["warning_message"] = (
                        f"Found {len(warnings)} similar existing "
                        f"{'entry' if len(warnings) == 1 else 'entries'}. "
                        "Review before storing to avoid duplicates."
                    )
                response_data["conflicts"] = conflicts
                response_data["conflict_message"] = (
                    f"Found {len(conflicts)} potential conflict "
                    f"{'candidate' if len(conflicts) == 1 else 'candidates'}. "
                    "Use distillery_check_conflicts with LLM responses to confirm conflicts."
                )
                return success_response(response_data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Conflict check failed during store: %s", exc)
        # Non-fatal: fall through and return the entry_id without conflict info.

    response: dict[str, Any] = {"entry_id": entry_id}
    if warnings:
        response["warnings"] = warnings
        response["warning_message"] = (
            f"Found {len(warnings)} similar existing "
            f"{'entry' if len(warnings) == 1 else 'entries'}. "
            "Review before storing to avoid duplicates."
        )
    return success_response(response)


# ---------------------------------------------------------------------------
# _handle_get
# ---------------------------------------------------------------------------


async def _handle_get(
    store: Any,
    arguments: dict[str, Any],
    config: DistilleryConfig | None = None,
) -> list[types.TextContent]:
    """
    Retrieve an entry by its ID and, when applicable, record implicit positive feedback.

    Validates presence of `entry_id`, fetches the entry from `store`, and returns the
    serialized entry. Queries ``search_log`` directly for any recent search within the
    feedback window that returned this entry, then logs a positive feedback event per
    matching search. Failures to log feedback are caught and do not prevent returning
    the entry.

    Parameters:
        config (DistilleryConfig | None): Optional configuration used to read
            `classification.feedback_window_minutes`; defaults to 5 minutes when `None`.

    Returns:
        list[types.TextContent]: MCP content list containing the serialized entry on
        success, or an error response (e.g., `NOT_FOUND`, `INVALID_PARAMS`, `STORE_ERROR`).
    """
    err = validate_required(arguments, "entry_id")
    if err:
        return error_response("INVALID_PARAMS", err)

    entry_id: str = arguments["entry_id"]

    try:
        entry = await store.get(entry_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error fetching entry id=%s", entry_id)
        return error_response("STORE_ERROR", f"Failed to retrieve entry: {exc}")

    if entry is None:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )

    # Implicit feedback: query search_log for any recent search that returned this
    # entry and record a positive feedback signal. Using the DB directly (rather than
    # an in-memory list) ensures correctness in stateless deployments such as Lambda.
    feedback_window_minutes: int = 5
    if config is not None:
        feedback_window_minutes = config.classification.feedback_window_minutes

    since = datetime.now(UTC) - timedelta(minutes=feedback_window_minutes)
    try:
        recent_search_ids = await store.get_searches_for_entry(entry_id, since)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to query recent searches for entry_id=%s", entry_id)
        recent_search_ids = []

    logged_search_ids: set[str] = set()
    for search_id in recent_search_ids:
        if search_id not in logged_search_ids:
            try:
                await store.log_feedback(
                    search_id=search_id,
                    entry_id=entry_id,
                    signal="positive",
                )
                logged_search_ids.add(search_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to log implicit feedback for entry_id=%s search_id=%s",
                    entry_id,
                    search_id,
                )

    return success_response(entry.to_dict())


# ---------------------------------------------------------------------------
# _handle_update
# ---------------------------------------------------------------------------


async def _handle_update(
    store: Any,
    arguments: dict[str, Any],
    last_modified_by: str = "",
) -> list[types.TextContent]:
    """Implement the ``distillery_update`` tool.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Raw MCP tool arguments dict (must contain ``entry_id`` plus
            at least one updatable field).

    Returns:
        MCP content list with the serialised updated entry or an error.
    """
    from distillery.models import EntryStatus, EntryType

    err = validate_required(arguments, "entry_id")
    if err:
        return error_response("INVALID_PARAMS", err)

    entry_id: str = arguments["entry_id"]

    # Build the updates dict from all keys except entry_id.
    updatable_keys = {"content", "entry_type", "author", "project", "tags", "status", "metadata"}
    updates: dict[str, Any] = {}
    for key in updatable_keys:
        if key in arguments:
            updates[key] = arguments[key]

    # Reject attempts to modify immutable fields.
    bad_keys = _IMMUTABLE_FIELDS & (set(arguments.keys()) - {"entry_id"})
    if bad_keys:
        return error_response(
            "INVALID_PARAMS",
            f"Cannot update immutable field(s): {', '.join(sorted(bad_keys))}.",
        )

    if not updates:
        return error_response(
            "INVALID_PARAMS",
            "No updatable fields provided. Supply at least one of: "
            + ", ".join(sorted(updatable_keys))
            + ".",
        )

    # Inject last_modified_by *after* the emptiness check so auth metadata
    # alone cannot satisfy the "at least one field" requirement.
    if last_modified_by:
        updates["last_modified_by"] = last_modified_by

    # --- validate individual fields ----------------------------------------
    if "entry_type" in updates:
        et_str = updates["entry_type"]
        if et_str not in _VALID_ENTRY_TYPES:
            return error_response(
                "INVALID_PARAMS",
                f"Invalid entry_type {et_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
            )
        updates["entry_type"] = EntryType(et_str)

    if "status" in updates:
        st_str = updates["status"]
        if st_str not in _VALID_STATUSES:
            return error_response(
                "INVALID_PARAMS",
                f"Invalid status {st_str!r}. Must be one of: {', '.join(sorted(_VALID_STATUSES))}.",
            )
        updates["status"] = EntryStatus(st_str)

    tags_err = validate_type(updates, "tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_PARAMS", tags_err)

    metadata_err = validate_type(updates, "metadata", dict, "object")
    if metadata_err:
        return error_response("INVALID_PARAMS", metadata_err)

    # --- persist ------------------------------------------------------------
    try:
        updated_entry = await store.update(entry_id, updates)
    except KeyError:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )
    except ValueError as exc:
        return error_response("INVALID_PARAMS", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error updating entry id=%s", entry_id)
        return error_response("STORE_ERROR", f"Failed to update entry: {exc}")

    return success_response(updated_entry.to_dict())


# ---------------------------------------------------------------------------
# _handle_list and its helpers
# ---------------------------------------------------------------------------

_VALID_OUTPUT_MODES = frozenset({"full", "summary", "ids"})


def _entry_to_summary_dict(entry: Any) -> dict[str, Any]:
    """Serialise *entry* without the ``content`` field (summary mode)."""
    d: dict[str, Any] = entry.to_dict()
    d.pop("content", None)
    return d


def _entry_to_id_dict(entry: Any) -> dict[str, Any]:
    """Serialise *entry* as id/entry_type/created_at only (ids mode)."""
    result: dict[str, Any] = {
        "id": entry.id,
        "entry_type": entry.entry_type.value,
        "created_at": entry.created_at.isoformat(),
    }
    return result


async def _handle_list(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_list`` tool.

    Returns entries with optional metadata filtering and pagination.  Unlike
    ``distillery_search``, no semantic ranking is performed -- results are
    ordered by ``created_at`` descending (newest first).

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        arguments: Tool argument dict (all fields optional).

    Returns:
        MCP content list with a JSON payload of ``entries`` and ``count``.
    """
    limit_result = validate_limit(arguments.get("limit", 20), min_val=1, max_val=500, default=20)
    if isinstance(limit_result, tuple):
        return error_response(*limit_result)
    limit = limit_result

    offset_raw = arguments.get("offset", 0)
    err_offset = validate_type(arguments, "offset", int, "integer")
    if err_offset:
        return error_response("INVALID_PARAMS", err_offset)
    offset = int(offset_raw) if offset_raw is not None else 0
    if offset < 0:
        return error_response("INVALID_PARAMS", "Field 'offset' must be >= 0")

    output_mode = arguments.get("output_mode", "full")
    err_output_mode = validate_type(arguments, "output_mode", str, "string")
    if err_output_mode:
        return error_response("INVALID_PARAMS", err_output_mode)
    if output_mode not in _VALID_OUTPUT_MODES:
        return error_response(
            "INVALID_PARAMS",
            f"Field 'output_mode' must be one of: {', '.join(sorted(_VALID_OUTPUT_MODES))}",
        )

    content_max_length_raw = arguments.get("content_max_length")
    content_max_length: int | None = None
    if content_max_length_raw is not None:
        if not isinstance(content_max_length_raw, int):
            return error_response("INVALID_PARAMS", "Field 'content_max_length' must be an integer")
        if content_max_length_raw < 1:
            return error_response("INVALID_PARAMS", "Field 'content_max_length' must be >= 1")
        content_max_length = content_max_length_raw

    filters = _build_filters_from_arguments(arguments)

    try:
        entries = await store.list_entries(filters=filters, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_list")
        return error_response("LIST_ERROR", f"list_entries failed: {exc}")

    if output_mode == "summary":
        serialised = [_entry_to_summary_dict(e) for e in entries]
    elif output_mode == "ids":
        serialised = [_entry_to_id_dict(e) for e in entries]
    else:
        if content_max_length is not None:
            result_dicts = []
            for e in entries:
                d = e.to_dict()
                if isinstance(d.get("content"), str) and len(d["content"]) > content_max_length:
                    d["content"] = d["content"][:content_max_length] + "…"
                result_dicts.append(d)
            serialised = result_dicts
        else:
            serialised = [e.to_dict() for e in entries]

    return success_response(
        {
            "entries": serialised,
            "count": len(entries),
            "limit": limit,
            "offset": offset,
            "output_mode": output_mode,
        }
    )


# ---------------------------------------------------------------------------
# Shared filter builder (used by _handle_list and search handlers)
# ---------------------------------------------------------------------------


def _build_filters_from_arguments(arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Extract known filter keys from *arguments* into a filters dict.

    Keys extracted: ``entry_type``, ``author``, ``project``, ``tags``,
    ``status``, ``date_from``, ``date_to``.

    Args:
        arguments: The tool argument dict.

    Returns:
        A dict of filters, or ``None`` if no filter keys are present.
    """
    filter_keys = (
        "entry_type",
        "author",
        "project",
        "tags",
        "status",
        "date_from",
        "date_to",
        "tag_prefix",
    )
    filters: dict[str, Any] = {}
    for key in filter_keys:
        if key in arguments and arguments[key] is not None:
            filters[key] = arguments[key]
    return filters if filters else None


__all__ = [
    "_handle_status",
    "_handle_store",
    "_handle_get",
    "_handle_update",
    "_handle_list",
    "_build_filters_from_arguments",
    "_VALID_ENTRY_TYPES",
    "_VALID_STATUSES",
    "_IMMUTABLE_FIELDS",
    "_DEFAULT_DEDUP_THRESHOLD",
    "_DEFAULT_DEDUP_LIMIT",
    "_VALID_OUTPUT_MODES",
    "_entry_to_summary_dict",
    "_entry_to_id_dict",
    "_is_remote_db_path",
    "_normalize_db_path",
]
