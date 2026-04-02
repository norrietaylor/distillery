"""Tools package for Distillery MCP server.

Domain modules:
  - crud.py      — status, store, get, update, list
  - search.py    — search, find_similar, aggregate
  - classify.py  — classify, review_queue, resolve_review
  - quality.py   — check_dedup, check_conflicts
  - analytics.py — metrics, quality, stale, tag_tree, interests, type_schemas
  - feeds.py     — watch, poll, rescore, suggest_sources
  - meta.py      — reserved for future cross-cutting tool concerns
  - _common.py   — shared helpers (error/success response, validation)
  - _errors.py   — standardized error code constants
"""

from distillery.mcp.tools.analytics import (
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
