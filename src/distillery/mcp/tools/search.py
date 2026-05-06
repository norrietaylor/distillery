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
        return error_response("INVALID_PARAMS", err)

    query: str = arguments["query"]

    limit_result = validate_limit(arguments.get("limit", 10), min_val=1, max_val=200, default=10)
    if isinstance(limit_result, tuple):
        return error_response(*limit_result)
    limit = limit_result

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

    results = [{"score": round(sr.score, 6), "entry": sr.entry.to_dict()} for sr in search_results]

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

    * **source_entry_id** (str | None): when set, the entry's content is used
      as the similarity probe if ``content`` is omitted, the source entry is
      always self-excluded from results, and (combined with ``exclude_linked``)
      the entry's existing relations form the exclusion anchor.

    * **exclude_linked** (bool, default ``False``): when ``True``, filters out
      entries already linked to ``source_entry_id`` via ``entry_relations``
      (any direction, any relation_type). Requires ``source_entry_id``.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        arguments: Tool argument dict; must contain ``content`` or
            ``source_entry_id``.
        cfg: Optional configuration used to enforce embedding budget.

    Returns:
        MCP content list with a JSON payload of ``results`` and ``count``.
    """
    from distillery.mcp.budget import EmbeddingBudgetError, record_and_check

    # --- new graph-extension parameters (parsed first so we can use them
    # when validating content/source_entry_id requirements below) ---------
    err_source_id_type = validate_type(arguments, "source_entry_id", str, "string")
    if err_source_id_type:
        return error_response("INVALID_PARAMS", err_source_id_type)
    source_entry_id_raw: str | None = arguments.get("source_entry_id")
    source_entry_id: str | None = source_entry_id_raw if source_entry_id_raw else None

    exclude_linked: bool = bool(arguments.get("exclude_linked", False))
    if exclude_linked and source_entry_id is None:
        return error_response(
            "INVALID_PARAMS",
            "exclude_linked=true requires source_entry_id",
        )

    # Resolve source entry up-front so we can supply its content as the
    # similarity probe when caller omits an explicit ``content`` argument.
    source_entry = None
    if source_entry_id is not None:
        source_entry = await store.get(source_entry_id)
        if source_entry is None:
            return error_response("NOT_FOUND", f"Entry not found: {source_entry_id}")

    # Either ``content`` or ``source_entry_id`` must yield a non-empty probe.
    raw_content = arguments.get("content")
    content_provided = isinstance(raw_content, str) and raw_content.strip() != ""
    if not content_provided and source_entry is None:
        return error_response(
            "INVALID_PARAMS",
            "Missing required fields: content",
        )

    if content_provided:
        content: str = raw_content  # type: ignore[assignment]
    else:
        # source_entry is not None here (guarded above)
        assert source_entry is not None
        content = source_entry.content
        if not content or not content.strip():
            return error_response(
                "INVALID_PARAMS",
                "Field 'content' must be a non-empty string",
            )

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

    # --- graph-extension filtering (self + linked exclusion) ---------------
    excluded_linked_count = 0
    if source_entry_id is not None:
        count_before = len(search_results)
        linked_ids: set[str] = set()
        if exclude_linked:
            try:
                relations = await store.get_related(source_entry_id, direction="both")
            except Exception:  # noqa: BLE001
                logger.exception("Error fetching relations in find_similar")
                return error_response("INTERNAL", "Failed to fetch related entries")
            for rel in relations:
                from_id = rel.get("from_id")
                to_id = rel.get("to_id")
                if isinstance(from_id, str) and from_id != source_entry_id:
                    linked_ids.add(from_id)
                if isinstance(to_id, str) and to_id != source_entry_id:
                    linked_ids.add(to_id)
            search_results = [
                sr
                for sr in search_results
                if sr.entry.id != source_entry_id and sr.entry.id not in linked_ids
            ]
        else:
            # Self-exclusion only when source_entry_id is set without
            # exclude_linked.
            search_results = [sr for sr in search_results if sr.entry.id != source_entry_id]
        excluded_linked_count = count_before - len(search_results)

    results = [{"score": round(sr.score, 6), "entry": sr.entry.to_dict()} for sr in search_results]
    payload: dict[str, Any] = {
        "results": results,
        "count": len(results),
        "threshold": threshold,
    }
    if source_entry_id is not None or exclude_linked:
        payload["excluded_linked_count"] = excluded_linked_count

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
