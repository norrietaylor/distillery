"""Context retrieval tool handler for the Distillery MCP server.

Implements the ``distillery_context`` tool: a combined tag/semantic retrieval
that returns entries sorted by relevance, weighted by recency.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.mcp.tools._common import (
    error_response,
    success_response,
    validate_type,
)
from distillery.mcp.tools._errors import validate_limit

logger = logging.getLogger(__name__)

_VALID_SCOPES = frozenset({"semantic", "tags", "all"})


async def _handle_context(
    store: Any,
    arguments: dict[str, Any],
    cfg: DistilleryConfig | None = None,
) -> list[types.TextContent]:
    """Implement the ``distillery_context`` tool.

    Combines tag-based filtering with optional semantic search to return
    entries relevant to a project or topic, weighted by recency.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Tool argument dict.  Accepts optional ``project`` (str),
            ``tags`` (list[str]), ``scope`` ("semantic"|"tags"|"all"),
            ``query`` (str, for semantic scoping), ``limit`` (int).

    Returns:
        MCP content list with a JSON payload of entries and metadata.
    """
    # --- validate scope -------------------------------------------------------
    scope_raw = arguments.get("scope", "all")
    err_scope = validate_type(arguments, "scope", str, "string")
    if err_scope:
        return error_response("INVALID_PARAMS", err_scope)
    scope: str = str(scope_raw)
    if scope not in _VALID_SCOPES:
        return error_response(
            "INVALID_PARAMS",
            f"Field 'scope' must be one of: {', '.join(sorted(_VALID_SCOPES))}",
        )

    # --- validate limit -------------------------------------------------------
    limit_result = validate_limit(arguments.get("limit", 20), min_val=1, max_val=200, default=20)
    if isinstance(limit_result, tuple):
        return error_response(*limit_result)
    limit: int = limit_result

    # --- validate tags --------------------------------------------------------
    tags_err = validate_type(arguments, "tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_PARAMS", tags_err)

    # --- validate query -------------------------------------------------------
    query_err = validate_type(arguments, "query", str, "string")
    if query_err:
        return error_response("INVALID_PARAMS", query_err)

    project: str | None = arguments.get("project")
    tags: list[str] | None = arguments.get("tags")
    query: str | None = arguments.get("query")

    # Build filters for project/tags.
    filters: dict[str, Any] = {"status": "active"}
    if project is not None:
        filters["project"] = project
    if tags:
        filters["tags"] = tags

    try:
        entries_out: list[dict[str, Any]] = []

        if scope == "semantic" or (scope == "all" and query):
            # Semantic search (optionally filtered by project/tags).
            if not query:
                return error_response(
                    "INVALID_PARAMS",
                    "Field 'query' is required when scope is 'semantic'.",
                )
            results = await store.search(query, filters=filters, limit=limit)
            for r in results:
                d = r.entry.to_dict()
                d["relevance_score"] = round(r.score, 4)
                entries_out.append(d)

        elif scope == "tags" or (scope == "all" and not query):
            # Tag/project filter only, sorted by recency.
            entries = await store.list_entries(filters=filters, limit=limit, offset=0)
            entries_out = [e.to_dict() for e in entries]

    except Exception as exc:  # noqa: BLE001
        logger.exception("Error in distillery_context")
        return error_response("CONTEXT_ERROR", f"Failed to retrieve context: {exc}")

    return success_response(
        {
            "entries": entries_out,
            "count": len(entries_out),
            "scope": scope,
            "project": project,
            "tags": tags,
            "query": query,
        }
    )


__all__ = ["_handle_context"]
