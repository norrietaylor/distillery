"""Search tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_search: Semantic search over stored entries by query
  - distillery_find_similar: Find entries similar to a given content string
  - distillery_aggregate: Count entries grouped by a field
"""

from __future__ import annotations

import logging
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.mcp.tools._common import (
    error_response,
    success_response,
    validate_required,
    validate_type,
)
from distillery.mcp.tools.crud import _build_filters_from_arguments

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# _handle_search
# ---------------------------------------------------------------------------


async def _handle_search(
    store: Any,
    arguments: dict[str, Any],
    cfg: DistilleryConfig | None = None,
) -> list[types.TextContent]:
    """
    Search stored entries for a text query and return matching entries ranked by similarity.

    Performs validation on `query` and `limit`, applies optional filters from `arguments`,
    and returns search hits ordered by descending similarity. When results are non-empty,
    logs the search to ``search_log`` for later implicit-feedback correlation via
    ``_handle_get``; failures to log do not affect the returned results.

    Parameters:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        arguments: Dictionary containing at minimum the key `query` (str). May include
            optional filter keys (e.g., `entry_type`, `author`, `project`, `tags`,
            `status`, `date_from`, `date_to`) and `limit` (int).
        cfg: Optional configuration used to enforce embedding budget.

    Returns:
        MCP content list containing a single JSON object with `results` (list of objects
        each with `score` and `entry`) and `count` (int) describing the number of results
        returned.
    """
    from distillery.mcp.budget import EmbeddingBudgetError, record_and_check

    err = validate_required(arguments, "query")
    if err:
        return error_response("VALIDATION_ERROR", err)

    query: str = arguments["query"]

    limit_raw = arguments.get("limit", 10)
    err_limit = validate_type(arguments, "limit", int, "integer")
    if err_limit:
        return error_response("VALIDATION_ERROR", err_limit)
    limit = int(limit_raw) if limit_raw is not None else 10
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")
    if limit > 200:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be <= 200")

    # --- embedding budget check (1 embed call per search) -------------------
    if cfg is not None:
        try:
            record_and_check(store.connection, cfg.rate_limit.embedding_budget_daily)
        except EmbeddingBudgetError as exc:
            return error_response("BUDGET_EXCEEDED", str(exc))

    filters = _build_filters_from_arguments(arguments)

    try:
        search_results = await store.search(query=query, filters=filters, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_search")
        return error_response("SEARCH_ERROR", f"Search failed: {exc}")

    results = [{"score": round(sr.score, 6), "entry": sr.entry.to_dict()} for sr in search_results]

    # Log the search event to search_log for later implicit-feedback correlation.
    if search_results:
        result_entry_ids = [sr.entry.id for sr in search_results]
        result_scores = [sr.score for sr in search_results]
        try:
            await store.log_search(
                query=query,
                result_entry_ids=result_entry_ids,
                result_scores=result_scores,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to log search event; continuing without feedback tracking")

    return success_response({"results": results, "count": len(results)})


# ---------------------------------------------------------------------------
# _handle_find_similar
# ---------------------------------------------------------------------------


async def _handle_find_similar(
    store: Any,
    arguments: dict[str, Any],
    cfg: DistilleryConfig | None = None,
) -> list[types.TextContent]:
    """Implement the ``distillery_find_similar`` tool.

    Embeds *content* and returns stored entries whose cosine similarity
    exceeds *threshold*, sorted by descending similarity.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        arguments: Tool argument dict containing at minimum ``content``.
        cfg: Optional configuration used to enforce embedding budget.

    Returns:
        MCP content list with a JSON payload of ``results`` and ``count``.
    """
    from distillery.mcp.budget import EmbeddingBudgetError, record_and_check

    err = validate_required(arguments, "content")
    if err:
        return error_response("VALIDATION_ERROR", err)

    content: str = arguments["content"]

    threshold_raw = arguments.get("threshold", 0.8)
    err_threshold = validate_type(arguments, "threshold", (int, float), "number")
    if err_threshold:
        return error_response("VALIDATION_ERROR", err_threshold)
    threshold = float(threshold_raw) if threshold_raw is not None else 0.8
    if not (0.0 <= threshold <= 1.0):
        return error_response("VALIDATION_ERROR", "Field 'threshold' must be in [0.0, 1.0]")

    limit_raw = arguments.get("limit", 10)
    err_limit = validate_type(arguments, "limit", int, "integer")
    if err_limit:
        return error_response("VALIDATION_ERROR", err_limit)
    limit = int(limit_raw) if limit_raw is not None else 10
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")
    if limit > 200:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be <= 200")

    # --- embedding budget check (1 embed call) ----------------------------
    if cfg is not None:
        try:
            record_and_check(store.connection, cfg.rate_limit.embedding_budget_daily)
        except EmbeddingBudgetError as exc:
            return error_response("BUDGET_EXCEEDED", str(exc))

    try:
        search_results = await store.find_similar(content=content, threshold=threshold, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_find_similar")
        return error_response("FIND_SIMILAR_ERROR", f"find_similar failed: {exc}")

    results = [{"score": round(sr.score, 6), "entry": sr.entry.to_dict()} for sr in search_results]
    return success_response({"results": results, "count": len(results), "threshold": threshold})


# ---------------------------------------------------------------------------
# _handle_aggregate and its constants
# ---------------------------------------------------------------------------

_AGGREGATE_GROUP_BY_MAP: dict[str, str] = {
    "entry_type": "entry_type",
    "status": "status",
    "author": "author",
    "project": "project",
    "source": "source",
    "metadata.source_url": "json_extract_string(metadata, '$.source_url')",
    "metadata.source_type": "json_extract_string(metadata, '$.source_type')",
}


async def _handle_aggregate(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_aggregate`` tool.

    Returns count-by-group aggregates without fetching full entry payloads.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        arguments: Tool argument dict.

    Returns:
        MCP content list with a JSON payload containing ``group_by``,
        ``groups``, ``total_entries``, and ``total_groups``.
    """
    group_by = arguments.get("group_by", "")
    err_group_by = validate_type(arguments, "group_by", str, "string")
    if err_group_by:
        return error_response("VALIDATION_ERROR", err_group_by)
    if not group_by:
        return error_response("VALIDATION_ERROR", "Missing required field: group_by")
    if group_by not in _AGGREGATE_GROUP_BY_MAP:
        return error_response(
            "VALIDATION_ERROR",
            f"Field 'group_by' must be one of: {', '.join(sorted(_AGGREGATE_GROUP_BY_MAP))}",
        )

    limit_raw = arguments.get("limit", 50)
    if not isinstance(limit_raw, int):
        return error_response("VALIDATION_ERROR", "Field 'limit' must be an integer")
    limit = int(limit_raw)
    if limit < 1:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be >= 1")
    if limit > 500:
        return error_response("VALIDATION_ERROR", "Field 'limit' must be <= 500")

    filters = _build_filters_from_arguments(arguments)

    try:
        result = await store.aggregate_entries(
            group_by=group_by,
            filters=filters,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_aggregate")
        return error_response("AGGREGATE_ERROR", f"aggregate_entries failed: {exc}")

    return success_response(
        {
            "group_by": group_by,
            "groups": result["groups"],
            "total_entries": result["total_entries"],
            "total_groups": result["total_groups"],
        }
    )


__all__ = [
    "_handle_search",
    "_handle_find_similar",
    "_handle_aggregate",
    "_AGGREGATE_GROUP_BY_MAP",
]
