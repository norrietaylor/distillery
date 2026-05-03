"""Search tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_search: Semantic search over stored entries by query
  - distillery_find_similar: Find entries similar to a given content string,
    with optional dedup_action and conflict_check modes
  - distillery_aggregate: Count entries grouped by a field
"""

from __future__ import annotations

import logging
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.embedding.errors import EmbeddingProviderError
from distillery.mcp.tools._common import (
    error_response,
    success_response,
    validate_required,
    validate_type,
)
from distillery.mcp.tools._errors import upstream_error_response, validate_limit
from distillery.mcp.tools.crud import (
    _apply_default_status_filter,
    _build_filters_from_arguments,
)

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

    When ``expand_graph=True`` is passed, after the semantic-search seed set is computed
    a BFS expansion via ``store.get_related`` collects 1- or 2-hop neighbours, fetches
    their entries, scores them with a ``0.5 ** depth`` discount of the parent score, and
    merges them into a single result list sorted by descending score and capped at
    ``limit``.  Each result then carries a ``provenance`` flag (``"search"`` or
    ``"graph"``) and graph entries additionally carry ``depth`` and ``parent_id``.  The
    response envelope gains a ``graph_expansion`` summary (``seed_count``,
    ``expanded_count``).  When ``expand_graph=False`` (default) the existing behaviour
    and envelope are unchanged.

    Parameters:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        arguments: Dictionary containing at minimum the key `query` (str). May include
            optional filter keys (e.g., `entry_type`, `author`, `project`, `tags`,
            `status`, `date_from`, `date_to`), `limit` (int), and the additive
            graph-expansion params `expand_graph` (bool) and `expand_hops` (int, 1 or 2).
        cfg: Optional configuration used to enforce embedding budget.

    Returns:
        MCP content list containing a single JSON object with `results` (list of objects
        each with `score` and `entry`) and `count` (int) describing the number of results
        returned.  When ``expand_graph=True`` results also include ``provenance`` and the
        envelope includes a ``graph_expansion`` field.
    """
    from distillery.mcp.budget import EmbeddingBudgetError, record_and_check

    err = validate_required(arguments, "query")
    if err:
        return error_response("INVALID_PARAMS", err)

    query: str = arguments["query"]

    limit_result = validate_limit(arguments.get("limit", 10), min_val=1, max_val=200, default=10)
    if isinstance(limit_result, tuple):
        return error_response(*limit_result)
    limit = limit_result

    # --- graph expansion params (validated BEFORE embedding budget) ---------
    expand_graph: bool = bool(arguments.get("expand_graph", False))
    expand_hops_raw: Any = arguments.get("expand_hops", 1)
    # Reject bool explicitly: ``bool`` is a subclass of ``int`` in Python and we
    # want to surface a clear error rather than silently coercing True/False.
    if isinstance(expand_hops_raw, bool):
        return error_response("INVALID_PARAMS", "expand_hops must be an integer")
    if not isinstance(expand_hops_raw, int):
        return error_response("INVALID_PARAMS", "expand_hops must be an integer")
    expand_hops: int = expand_hops_raw
    if expand_hops not in (1, 2):
        return error_response("INVALID_PARAMS", "expand_hops must be 1 or 2")

    # --- embedding budget check (1 embed call per search) -------------------
    if cfg is not None:
        try:
            record_and_check(store.connection, cfg.rate_limit.embedding_budget_daily)
        except EmbeddingBudgetError as exc:
            return error_response("BUDGET_EXCEEDED", str(exc))

    filters = _build_filters_from_arguments(arguments)
    filter_result = _apply_default_status_filter(filters, arguments)
    if isinstance(filter_result, list):
        # Error response from status-filter validation.
        return filter_result
    filters = filter_result

    try:
        search_results = await store.search(query=query, filters=filters, limit=limit)
    except EmbeddingProviderError as exc:
        logger.warning(
            "Upstream embedding provider failed during search "
            "(provider=%s endpoint=%s status=%s retry_after=%s): %s",
            exc.provider,
            exc.endpoint,
            exc.status_code,
            exc.retry_after,
            exc,
        )
        return upstream_error_response(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Error in distillery_search")
        return error_response("INTERNAL", "Search failed")

    if not expand_graph:
        results = [
            {"score": round(sr.score, 6), "entry": sr.entry.to_dict()} for sr in search_results
        ]

        # Log the search event to search_log for later implicit-feedback correlation.
        search_logging = cfg is None or cfg.rate_limit.search_logging_enabled
        if search_results and search_logging:
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

    # ------------------------------------------------------------------
    # Graph expansion path (additive — only when expand_graph=True).
    # ------------------------------------------------------------------
    # Derive the status visibility contract that was applied to the seed
    # search so we can apply the same contract to BFS-expanded neighbours.
    # ``filters`` here is the post-``_apply_default_status_filter`` dict —
    # if it carries a ``status`` key, that is the allow-list (string or
    # list of strings).  Absence of ``status`` means "any status is ok".
    allowed_statuses: set[str] | None = _allowed_statuses_from_filters(filters)
    try:
        merged_results, seed_count, expanded_count = await _expand_search_with_graph(
            store, search_results, expand_hops, limit, allowed_statuses
        )
    except Exception:  # noqa: BLE001
        logger.exception("Error during graph expansion in distillery_search")
        return error_response("INTERNAL", "Graph expansion failed")

    # Log the seed search event (mirrors non-expand path).
    search_logging = cfg is None or cfg.rate_limit.search_logging_enabled
    if search_results and search_logging:
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

    return success_response(
        {
            "results": merged_results,
            "count": len(merged_results),
            "graph_expansion": {
                "seed_count": seed_count,
                "expanded_count": expanded_count,
            },
        }
    )


def _allowed_statuses_from_filters(
    filters: dict[str, Any] | None,
) -> set[str] | None:
    """Return the set of status strings allowed by the seed search filter.

    Returns ``None`` when no status filter is present (i.e. all statuses are
    allowed — the caller passed ``include_archived=True`` or
    ``status="any"``).  Otherwise returns a set of status strings (e.g.
    ``{"active", "pending_review"}``) that the seed search would have
    surfaced; expanded BFS neighbours must be filtered to this set so graph
    expansion does not leak entries the seed search would have hidden.
    """
    if filters is None or "status" not in filters:
        return None
    status_value = filters["status"]
    if isinstance(status_value, list):
        return {str(v) for v in status_value}
    return {str(status_value)}


async def _expand_search_with_graph(
    store: Any,
    search_results: list[Any],
    expand_hops: int,
    limit: int,
    allowed_statuses: set[str] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """BFS-expand the seed search results via ``store.get_related``.

    Returns ``(merged_results, seed_count, expanded_count)`` where
    ``merged_results`` is a list of result dicts already sorted by descending
    score and truncated to ``limit``.  Each dict carries a ``provenance``
    field; graph-only entries also carry ``depth`` and ``parent_id``.

    ``allowed_statuses`` mirrors the status-visibility contract that the
    seed ``store.search`` call applied.  When provided, BFS-expanded
    neighbours whose ``status`` is not in this set are dropped before the
    merge — preventing archived (or otherwise-filtered) entries from
    leaking into the result via graph expansion.  When ``None`` no
    status-based filtering is applied to expanded entries.
    """
    seed_ids: set[str] = {sr.entry.id for sr in search_results}
    seed_score_by_id: dict[str, float] = {sr.entry.id: float(sr.score) for sr in search_results}

    # Collected expansion entries keyed by id so we never duplicate one entry
    # across hops (closer hops always win because we visit depth=1 before
    # depth=2).
    expanded: dict[str, dict[str, Any]] = {}

    # depth-1 neighbours
    depth1_score_by_id: dict[str, float] = {}
    for sr in search_results:
        seed_id = sr.entry.id
        relations = await store.get_related(seed_id, direction="both")
        for rel in relations:
            other_id = rel["to_id"] if rel["from_id"] == seed_id else rel["from_id"]
            if other_id in seed_ids or other_id in expanded:
                continue
            score = seed_score_by_id[seed_id] * 0.5
            expanded[other_id] = {
                "_score": score,
                "_depth": 1,
                "_parent_id": seed_id,
            }
            depth1_score_by_id[other_id] = score

    # depth-2 neighbours (only when requested)
    if expand_hops == 2:
        for parent_id, parent_score in list(depth1_score_by_id.items()):
            relations = await store.get_related(parent_id, direction="both")
            for rel in relations:
                other_id = rel["to_id"] if rel["from_id"] == parent_id else rel["from_id"]
                if other_id in seed_ids or other_id in expanded:
                    continue
                score = parent_score * 0.5
                expanded[other_id] = {
                    "_score": score,
                    "_depth": 2,
                    "_parent_id": parent_id,
                }

    # Fetch entries for all expanded ids; skip any that have been deleted
    # or whose status would have been filtered out by the seed search.
    expanded_results: list[dict[str, Any]] = []
    for entry_id, info in expanded.items():
        entry = await store.get(entry_id)
        if entry is None:
            continue
        if allowed_statuses is not None and str(entry.status) not in allowed_statuses:
            # The seed search would have hidden this status; honour the same
            # contract for graph-expanded neighbours so archived (or other
            # filtered) entries never leak in via BFS.
            continue
        expanded_results.append(
            {
                "score": round(info["_score"], 6),
                "entry": entry.to_dict(),
                "provenance": "graph",
                "depth": info["_depth"],
                "parent_id": info["_parent_id"],
            }
        )

    seed_dicts: list[dict[str, Any]] = [
        {
            "score": round(sr.score, 6),
            "entry": sr.entry.to_dict(),
            "provenance": "search",
        }
        for sr in search_results
    ]

    merged: list[dict[str, Any]] = sorted(
        seed_dicts + expanded_results, key=lambda r: r["score"], reverse=True
    )[:limit]

    return merged, len(seed_dicts), len(expanded_results)


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

    Optional modes (progressive disclosure):

    * **dedup_action** (bool, default ``False``): when ``True``, runs the
      extracted dedup helper and adds a ``dedup`` field to the response
      containing ``action`` and ``similar_entries``.

    * **conflict_check** (bool, default ``False``): when ``True``, runs
      conflict pass 1 and adds a ``conflict_prompt`` field alongside each
      similar entry in the results.

    * **llm_responses** (list[dict] | None): when provided together with
      ``conflict_check=True``, runs conflict pass 2 and adds a
      ``conflict_evaluation`` field to the response.

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
        return error_response("INVALID_PARAMS", err)

    content: str = arguments["content"]

    threshold_raw = arguments.get("threshold", 0.8)
    err_threshold = validate_type(arguments, "threshold", (int, float), "number")
    if err_threshold:
        return error_response("INVALID_PARAMS", err_threshold)
    threshold = float(threshold_raw) if threshold_raw is not None else 0.8
    if not (0.0 <= threshold <= 1.0):
        return error_response("INVALID_PARAMS", "Field 'threshold' must be in [0.0, 1.0]")

    limit_result = validate_limit(arguments.get("limit", 10), min_val=1, max_val=200, default=10)
    if isinstance(limit_result, tuple):
        return error_response(*limit_result)
    limit = limit_result

    # --- optional mode flags ------------------------------------------------
    dedup_action: bool = bool(arguments.get("dedup_action", False))
    conflict_check: bool = bool(arguments.get("conflict_check", False))
    llm_responses_raw: list[dict[str, Any]] | None = arguments.get("llm_responses")

    # Validate llm_responses type if provided
    if llm_responses_raw is not None and not isinstance(llm_responses_raw, list):
        return error_response("INVALID_PARAMS", "Field 'llm_responses' must be a list of objects")

    # llm_responses without conflict_check is invalid
    if llm_responses_raw is not None and not conflict_check:
        return error_response(
            "INVALID_PARAMS",
            "Field 'llm_responses' requires conflict_check=true",
        )

    # --- embedding budget check (1 embed call) ----------------------------
    if cfg is not None:
        try:
            record_and_check(store.connection, cfg.rate_limit.embedding_budget_daily)
        except EmbeddingBudgetError as exc:
            return error_response("BUDGET_EXCEEDED", str(exc))

    try:
        search_results = await store.find_similar(content=content, threshold=threshold, limit=limit)
    except EmbeddingProviderError as exc:
        logger.warning(
            "Upstream embedding provider failed during find_similar "
            "(provider=%s endpoint=%s status=%s retry_after=%s): %s",
            exc.provider,
            exc.endpoint,
            exc.status_code,
            exc.retry_after,
            exc,
        )
        return upstream_error_response(exc)
    except Exception:  # noqa: BLE001
        logger.exception("Error in distillery_find_similar")
        return error_response("INTERNAL", "find_similar failed")

    results = [{"score": round(sr.score, 6), "entry": sr.entry.to_dict()} for sr in search_results]
    payload: dict[str, Any] = {
        "results": results,
        "count": len(results),
        "threshold": threshold,
    }

    # --- dedup_action mode ---------------------------------------------------
    if dedup_action:
        if cfg is None:
            return error_response(
                "INVALID_PARAMS",
                "dedup_action requires server configuration (classification settings)",
            )
        try:
            from distillery.mcp.tools.quality import run_dedup_check

            dedup_result = await run_dedup_check(store, cfg.classification, content)
            payload["dedup"] = dedup_result
        except Exception:  # noqa: BLE001
            logger.exception("Error running dedup check in find_similar")
            return error_response("INTERNAL", "Deduplication check failed")

    # --- conflict_check mode -------------------------------------------------
    if conflict_check:
        if cfg is None:
            return error_response(
                "INVALID_PARAMS",
                "conflict_check requires server configuration (classification settings)",
            )
        conflict_threshold = cfg.classification.conflict_threshold

        if llm_responses_raw is not None:
            # --- second pass: evaluate LLM responses ---
            parsed_responses: dict[str, tuple[bool, str]] = {}
            for item in llm_responses_raw:
                if not isinstance(item, dict):
                    return error_response(
                        "INVALID_PARAMS",
                        "Each item in llm_responses must be an object with "
                        "'entry_id', 'is_conflict', and 'reasoning'.",
                    )
                entry_id = item.get("entry_id")
                if entry_id is None:
                    return error_response(
                        "INVALID_PARAMS",
                        "Each llm_responses item must have an 'entry_id' field.",
                    )
                is_conflict_val = item.get("is_conflict")
                if is_conflict_val is None:
                    return error_response(
                        "INVALID_PARAMS",
                        f"llm_responses item for entry {entry_id!r} is missing 'is_conflict'.",
                    )
                reasoning = str(item.get("reasoning", ""))
                parsed_responses[str(entry_id)] = (bool(is_conflict_val), reasoning)

            try:
                from distillery.mcp.tools.quality import run_conflict_evaluation

                eval_result = await run_conflict_evaluation(
                    store, conflict_threshold, content, parsed_responses
                )
                payload["conflict_evaluation"] = eval_result
            except Exception:  # noqa: BLE001
                logger.exception("Error running conflict evaluation in find_similar")
                return error_response("INTERNAL", "Conflict evaluation failed")
        else:
            # --- first pass: discover conflict candidates ---
            try:
                from distillery.mcp.tools.quality import run_conflict_discovery

                discovery_result = await run_conflict_discovery(store, conflict_threshold, content)
                # Attach conflict_prompt to matching entries in results
                prompt_map: dict[str, str] = {}
                for candidate in discovery_result.get("conflict_candidates", []):
                    prompt_map[candidate["entry_id"]] = candidate["conflict_prompt"]

                for result_item in results:
                    entry_id = result_item["entry"].get("id", "")
                    if entry_id in prompt_map:
                        result_item["conflict_prompt"] = prompt_map[entry_id]

                payload["conflict_candidates"] = discovery_result.get("conflict_candidates", [])
                payload["conflict_candidates_count"] = len(payload["conflict_candidates"])
                payload["conflict_message"] = discovery_result.get("message", "")
            except Exception:  # noqa: BLE001
                logger.exception("Error running conflict discovery in find_similar")
                return error_response("INTERNAL", "Conflict check failed")

    return success_response(payload)


# ---------------------------------------------------------------------------
# _handle_aggregate and its constants
# ---------------------------------------------------------------------------

_AGGREGATE_GROUP_BY_MAP: dict[str, str] = {
    "entry_type": "entry_type",
    "status": "status",
    "author": "author",
    "project": "project",
    "source": "source",
    "tags": "UNNEST(tags)",
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
    err_group_by = validate_type(arguments, "group_by", str, "string")
    if err_group_by:
        return error_response("INVALID_PARAMS", err_group_by)
    err = validate_required(arguments, "group_by")
    if err:
        return error_response("INVALID_PARAMS", err)
    group_by: str = arguments["group_by"]
    if group_by not in _AGGREGATE_GROUP_BY_MAP:
        return error_response(
            "INVALID_PARAMS",
            f"Field 'group_by' must be one of: {', '.join(sorted(_AGGREGATE_GROUP_BY_MAP))}",
        )

    limit_result = validate_limit(arguments.get("limit", 50), min_val=1, max_val=500, default=50)
    if isinstance(limit_result, tuple):
        return error_response(*limit_result)
    limit = limit_result

    filters = _build_filters_from_arguments(arguments)

    try:
        result = await store.aggregate_entries(
            group_by=group_by,
            filters=filters,
            limit=limit,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Error in distillery_aggregate")
        return error_response("INTERNAL", "aggregate_entries failed")

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
