"""Tools package for Distillery MCP server.

This package contains domain-specific MCP tool handlers and shared utilities.
"""

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
from distillery.mcp.tools.search import (
    _handle_aggregate,
    _handle_find_similar,
    _handle_search,
)

__all__ = [
    "_handle_classify",
    "_handle_resolve_review",
    "_handle_review_queue",
    "_handle_get",
    "_handle_list",
    "_handle_status",
    "_handle_store",
    "_handle_update",
    "_handle_search",
    "_handle_find_similar",
    "_handle_aggregate",
]
