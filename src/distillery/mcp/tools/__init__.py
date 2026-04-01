"""Tools package for Distillery MCP server.

This package contains domain-specific MCP tool handlers and shared utilities.
"""

from distillery.mcp.tools.analytics import (
    _DEFAULT_STALE_DAYS,
    _handle_interests,
    _handle_metrics,
    _handle_quality,
    _handle_stale,
    _handle_tag_tree,
    _handle_type_schemas,
)
from distillery.mcp.tools.classify import (
    _handle_classify,
    _handle_resolve_review,
    _handle_review_queue,
)
from distillery.mcp.tools.crud import (
    _handle_get,
    _handle_list,
    _handle_status,
    _handle_store,
    _handle_update,
)
from distillery.mcp.tools.feeds import (
    _handle_poll,
    _handle_rescore,
    _handle_suggest_sources,
    _handle_watch,
)
from distillery.mcp.tools.quality import (
    _handle_check_conflicts,
    _handle_check_dedup,
)
from distillery.mcp.tools.search import (
    _handle_aggregate,
    _handle_find_similar,
    _handle_search,
)

__all__ = [
    "_DEFAULT_STALE_DAYS",
    "_handle_classify",
    "_handle_resolve_review",
    "_handle_review_queue",
    "_handle_get",
    "_handle_list",
    "_handle_status",
    "_handle_store",
    "_handle_update",
    "_handle_check_dedup",
    "_handle_check_conflicts",
    "_handle_search",
    "_handle_find_similar",
    "_handle_aggregate",
    "_handle_poll",
    "_handle_rescore",
    "_handle_suggest_sources",
    "_handle_watch",
    "_handle_interests",
    "_handle_metrics",
    "_handle_quality",
    "_handle_stale",
    "_handle_tag_tree",
    "_handle_type_schemas",
]
