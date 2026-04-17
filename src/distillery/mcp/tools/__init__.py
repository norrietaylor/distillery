"""Tools package for Distillery MCP server.

Domain modules:
  - crud.py      — store, get, update, list
  - search.py    — search, find_similar, aggregate
  - classify.py  — classify, resolve_review
  - quality.py   — run_dedup_check, run_conflict_discovery, run_conflict_evaluation (helpers)
  - analytics.py — metrics, stale, tag_tree, interests (with optional
                   suggest_sources), type_schemas
  - feeds.py     — watch, poll, rescore
  - configure.py — distillery_configure runtime config tool
  - meta.py      — distillery_status (server/health metadata probe)
  - _common.py   — shared helpers (error/success response, validation)
  - _errors.py   — standardized error code constants

Note: review queue listing is handled by distillery_list with output_mode="review".
"""

from distillery.mcp.tools.analytics import (
    _handle_interests,
    _handle_metrics,
    _handle_stale,
    _handle_tag_tree,
    _handle_type_schemas,
)
from distillery.mcp.tools.classify import (
    _handle_classify,
    _handle_resolve_review,
)
from distillery.mcp.tools.configure import _handle_configure
from distillery.mcp.tools.crud import (
    _handle_get,
    _handle_list,
    _handle_store,
    _handle_update,
)
from distillery.mcp.tools.feeds import (
    _handle_gh_sync,
    _handle_poll,
    _handle_rescore,
    _handle_store_batch,
    _handle_sync_status,
    _handle_watch,
)
from distillery.mcp.tools.meta import _handle_status
from distillery.mcp.tools.quality import (
    run_conflict_discovery,
    run_conflict_evaluation,
    run_dedup_check,
)
from distillery.mcp.tools.search import (
    _handle_aggregate,
    _handle_find_similar,
    _handle_search,
)

__all__ = [
    "_handle_configure",
    "_handle_status",
    "_handle_classify",
    "_handle_resolve_review",
    "_handle_get",
    "_handle_list",
    "_handle_store",
    "_handle_update",
    "run_dedup_check",
    "run_conflict_discovery",
    "run_conflict_evaluation",
    "_handle_search",
    "_handle_find_similar",
    "_handle_aggregate",
    "_handle_gh_sync",
    "_handle_poll",
    "_handle_rescore",
    "_handle_store_batch",
    "_handle_sync_status",
    "_handle_watch",
    "_handle_interests",
    "_handle_metrics",
    "_handle_stale",
    "_handle_tag_tree",
    "_handle_type_schemas",
]
