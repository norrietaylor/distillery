"""Relations tool handler for the Distillery MCP server.

Implements the following tool:
  - distillery_relations: Manage typed relations between knowledge entries.
    Actions: 'add', 'get', 'remove', 'traverse', 'metrics'.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from mcp import types

from distillery.mcp.tools._common import (
    error_response,
    success_response,
)

logger = logging.getLogger(__name__)

# Multi-hop BFS bounds for action="traverse" — capped at 3 hops to bound cost
# and prevent runaway traversal on heavily connected subgraphs.
_TRAVERSE_MIN_HOPS = 1
_TRAVERSE_MAX_HOPS = 3

# Fixed BFS depth used to assemble the ego-graph for action="metrics" / scope="ego".
_METRICS_EGO_HOPS = 2

# Pagination page size and hard cap when filtering the entries corpus down to
# the set whose IDs anchor a global-scope relations graph.  A single
# ``list_entries`` call could truncate IDs on large corpora; we paginate until
# the corpus is exhausted or the cap is hit (CodeRabbit, PR #426).
_GRAPH_METRICS_PAGE_SIZE = 1000
_GRAPH_METRICS_MAX_IDS = 100_000

_VALID_METRICS = {"bridges", "communities"}
_VALID_SCOPES = {"global", "ego"}

# ---------------------------------------------------------------------------
# distillery_relations handler
# ---------------------------------------------------------------------------

_VALID_DIRECTIONS = {"outgoing", "incoming", "both"}

_VALID_RELATION_TYPES = {
    "link",
    "corrects",
    "supersedes",
    "related",
    "blocks",
    "depends_on",
    "citation",
    "duplicate",
    "merge_source",
    "sync_source",
}


async def _handle_relations(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_relations`` tool.

    Supports ``add``, ``get``, and ``remove`` actions against the
    ``entry_relations`` table.

    Args:
        store: An initialised storage backend with relation methods.
        arguments: Parsed tool arguments dict.

    Returns:
        A structured MCP success or error response.
    """
    action_raw = arguments.get("action")
    if action_raw is None or not isinstance(action_raw, str):
        return error_response(
            "INVALID_PARAMS",
            f"action must be a non-null string, got: {action_raw!r}",
        )
    action = action_raw.strip().lower()

    if action not in ("add", "get", "remove", "traverse", "metrics"):
        return error_response(
            "INVALID_PARAMS",
            f"action must be one of 'add', 'get', 'remove', 'traverse', 'metrics'; got: {action!r}",
        )

    # ------------------------------------------------------------------
    # action == "add"
    # ------------------------------------------------------------------
    if action == "add":
        from_id_raw = arguments.get("from_id")
        if from_id_raw is None or not isinstance(from_id_raw, str):
            return error_response("INVALID_PARAMS", "from_id is required for action='add'")
        from_id = from_id_raw.strip()
        if not from_id:
            return error_response("INVALID_PARAMS", "from_id must be a non-empty string")

        to_id_raw = arguments.get("to_id")
        if to_id_raw is None or not isinstance(to_id_raw, str):
            return error_response("INVALID_PARAMS", "to_id is required for action='add'")
        to_id = to_id_raw.strip()
        if not to_id:
            return error_response("INVALID_PARAMS", "to_id must be a non-empty string")

        relation_type_raw = arguments.get("relation_type")
        if relation_type_raw is None or not isinstance(relation_type_raw, str):
            return error_response("INVALID_PARAMS", "relation_type is required for action='add'")
        relation_type = relation_type_raw.strip()
        if not relation_type:
            return error_response("INVALID_PARAMS", "relation_type must be a non-empty string")
        if relation_type not in _VALID_RELATION_TYPES:
            return error_response(
                "INVALID_PARAMS",
                f"Invalid relation_type {relation_type!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_RELATION_TYPES))}.",
            )

        try:
            relation_id = await store.add_relation(from_id, to_id, relation_type)
        except ValueError as exc:
            return error_response(
                "NOT_FOUND",
                f"Cannot create relation: {exc}",
            )
        except Exception:  # noqa: BLE001
            logger.exception("distillery_relations add: unexpected error")
            return error_response("INTERNAL", "Failed to add relation")

        return success_response(
            {
                "relation_id": relation_id,
                "from_id": from_id,
                "to_id": to_id,
                "relation_type": relation_type,
            }
        )

    # ------------------------------------------------------------------
    # action == "get"
    # ------------------------------------------------------------------
    if action == "get":
        entry_id_raw = arguments.get("entry_id")
        if entry_id_raw is None or not isinstance(entry_id_raw, str):
            return error_response("INVALID_PARAMS", "entry_id is required for action='get'")
        entry_id = entry_id_raw.strip()
        if not entry_id:
            return error_response("INVALID_PARAMS", "entry_id must be a non-empty string")

        direction_raw = arguments.get("direction", "both")
        if not isinstance(direction_raw, str):
            return error_response(
                "INVALID_PARAMS",
                f"direction must be a string, got: {type(direction_raw).__name__}",
            )
        direction = direction_raw.strip().lower()
        if direction not in _VALID_DIRECTIONS:
            return error_response(
                "INVALID_PARAMS",
                f"direction must be one of {sorted(_VALID_DIRECTIONS)}, got: {direction!r}",
            )

        get_relation_type_raw = arguments.get("relation_type")
        get_relation_type: str | None = None
        if get_relation_type_raw is not None:
            if not isinstance(get_relation_type_raw, str):
                return error_response(
                    "INVALID_PARAMS",
                    f"relation_type must be a string, got: {type(get_relation_type_raw).__name__}",
                )
            get_relation_type = get_relation_type_raw.strip() or None

        try:
            relations = await store.get_related(
                entry_id, direction=direction, relation_type=get_relation_type
            )
        except Exception:  # noqa: BLE001
            logger.exception("distillery_relations get: unexpected error")
            return error_response("INTERNAL", "Failed to get relations")

        return success_response(
            {
                "entry_id": entry_id,
                "direction": direction,
                "relation_type": get_relation_type,
                "relations": relations,
                "count": len(relations),
            }
        )

    # ------------------------------------------------------------------
    # action == "traverse"
    # ------------------------------------------------------------------
    if action == "traverse":
        entry_id_raw = arguments.get("entry_id")
        if entry_id_raw is None or not isinstance(entry_id_raw, str):
            return error_response("INVALID_PARAMS", "entry_id is required for action='traverse'")
        root_id = entry_id_raw.strip()
        if not root_id:
            return error_response("INVALID_PARAMS", "entry_id must be a non-empty string")

        hops_raw = arguments.get("hops", 2)
        if isinstance(hops_raw, bool) or not isinstance(hops_raw, int):
            return error_response(
                "INVALID_PARAMS",
                f"hops must be an integer in [{_TRAVERSE_MIN_HOPS}, {_TRAVERSE_MAX_HOPS}], "
                f"got: {hops_raw!r}",
            )
        hops = hops_raw
        if hops < _TRAVERSE_MIN_HOPS or hops > _TRAVERSE_MAX_HOPS:
            return error_response(
                "INVALID_PARAMS",
                f"hops must be in [{_TRAVERSE_MIN_HOPS}, {_TRAVERSE_MAX_HOPS}], got: {hops}",
            )

        traverse_direction_raw = arguments.get("direction", "both")
        if not isinstance(traverse_direction_raw, str):
            return error_response(
                "INVALID_PARAMS",
                f"direction must be a string, got: {type(traverse_direction_raw).__name__}",
            )
        traverse_direction = traverse_direction_raw.strip().lower()
        if traverse_direction not in _VALID_DIRECTIONS:
            return error_response(
                "INVALID_PARAMS",
                "direction must be one of "
                f"{sorted(_VALID_DIRECTIONS)}, got: {traverse_direction!r}",
            )

        traverse_relation_type_raw = arguments.get("relation_type")
        traverse_relation_type: str | None = None
        if traverse_relation_type_raw is not None:
            if not isinstance(traverse_relation_type_raw, str):
                return error_response(
                    "INVALID_PARAMS",
                    "relation_type must be a string, got: "
                    f"{type(traverse_relation_type_raw).__name__}",
                )
            stripped = traverse_relation_type_raw.strip()
            if stripped:
                if stripped not in _VALID_RELATION_TYPES:
                    return error_response(
                        "INVALID_PARAMS",
                        f"Invalid relation_type {stripped!r}. "
                        f"Must be one of: {', '.join(sorted(_VALID_RELATION_TYPES))}.",
                    )
                traverse_relation_type = stripped

        # Verify root exists.
        try:
            root_entry = await store.get(root_id)
        except Exception:  # noqa: BLE001
            logger.exception("distillery_relations traverse: unexpected error fetching root")
            return error_response("INTERNAL", "Failed to fetch root entry")
        if root_entry is None:
            return error_response("NOT_FOUND", f"Entry not found: {root_id!r}")

        # BFS — track visited node ids and per-node depth; collect deduped edges.
        nodes: list[dict[str, Any]] = [{"id": root_id, "depth": 0}]
        visited: dict[str, int] = {root_id: 0}
        edges: list[dict[str, Any]] = []
        edge_keys: set[tuple[str, str, str]] = set()
        queue: deque[tuple[str, int]] = deque([(root_id, 0)])

        try:
            while queue:
                node_id, depth = queue.popleft()
                if depth >= hops:
                    continue
                neighbours = await store.get_related(
                    node_id,
                    direction=traverse_direction,
                    relation_type=traverse_relation_type,
                )
                for row in neighbours:
                    from_id = row["from_id"]
                    to_id = row["to_id"]
                    rel_type = row["relation_type"]
                    edge_key = (from_id, to_id, rel_type)
                    if edge_key not in edge_keys:
                        edge_keys.add(edge_key)
                        edges.append(
                            {
                                "from_id": from_id,
                                "to_id": to_id,
                                "relation_type": rel_type,
                            }
                        )
                    # Determine the "other" endpoint relative to the current node.
                    if from_id == node_id:
                        other = to_id
                    elif to_id == node_id:
                        other = from_id
                    else:
                        # Should not happen — defensive guard.
                        continue
                    if other not in visited:
                        visited[other] = depth + 1
                        nodes.append({"id": other, "depth": depth + 1})
                        queue.append((other, depth + 1))
        except Exception:  # noqa: BLE001
            logger.exception("distillery_relations traverse: unexpected error during BFS")
            return error_response("INTERNAL", "Failed to traverse relations")

        return success_response(
            {
                "action": "traverse",
                "root": root_id,
                "hops": hops,
                "direction": traverse_direction,
                "relation_type": traverse_relation_type,
                "nodes": nodes,
                "edges": edges,
                "node_count": len(nodes),
                "edge_count": len(edges),
            }
        )

    # ------------------------------------------------------------------
    # action == "metrics"
    # ------------------------------------------------------------------
    if action == "metrics":
        return await _handle_metrics(store, arguments)

    # ------------------------------------------------------------------
    # action == "remove"
    # ------------------------------------------------------------------
    relation_id_raw = arguments.get("relation_id")
    if relation_id_raw is None or not isinstance(relation_id_raw, str):
        return error_response("INVALID_PARAMS", "relation_id is required for action='remove'")
    relation_id = relation_id_raw.strip()
    if not relation_id:
        return error_response("INVALID_PARAMS", "relation_id must be a non-empty string")

    try:
        removed = await store.remove_relation(relation_id)
    except Exception:  # noqa: BLE001
        logger.exception("distillery_relations remove: unexpected error")
        return error_response("INTERNAL", "Failed to remove relation")

    return success_response(
        {
            "relation_id": relation_id,
            "removed": removed,
        }
    )


# ---------------------------------------------------------------------------
# action == "metrics" — graph metrics over relations subgraph
# ---------------------------------------------------------------------------


def _validate_optional_str(
    arguments: dict[str, Any], field: str
) -> tuple[str | None, list[types.TextContent] | None]:
    """Return (value-or-None, error-response-or-None) for an optional string field."""
    raw = arguments.get(field)
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, error_response(
            "INVALID_PARAMS",
            f"{field} must be a string, got: {type(raw).__name__}",
        )
    stripped = raw.strip()
    return (stripped or None), None


def _validate_optional_str_list(
    arguments: dict[str, Any], field: str
) -> tuple[list[str] | None, list[types.TextContent] | None]:
    """Return (value-or-None, error-response-or-None) for an optional list-of-strings field."""
    raw = arguments.get(field)
    if raw is None:
        return None, None
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        return None, error_response(
            "INVALID_PARAMS",
            f"{field} must be a list of strings",
        )
    return list(raw), None


async def _collect_global_relations(
    store: Any,
    *,
    project: str | None,
    tags: list[str] | None,
    date_from: str | None,
    date_to: str | None,
) -> list[dict[str, Any]]:
    """Fetch all entry_relations rows, optionally filtered by entry-side filters.

    Goes through ``store.list_relations`` (an async store method) so all DB I/O
    runs off the event loop via the shared ``_run_sync`` lock — no direct sync
    ``conn.execute()`` from this async handler (CodeRabbit, PR #426).
    """
    relations: list[dict[str, Any]] = await store.list_relations()

    if not (project or tags or date_from or date_to):
        return relations

    # Use store.list_entries to resolve which entry ids match the filter set;
    # then keep relations whose endpoints both fall within that set.
    filters: dict[str, Any] = {}
    if project is not None:
        filters["project"] = project
    if tags:
        filters["tags"] = tags
    if date_from is not None:
        filters["date_from"] = date_from
    if date_to is not None:
        filters["date_to"] = date_to

    # Paginate so corpora larger than a single page are not silently truncated.
    matching_ids: set[str] = set()
    offset = 0
    while True:
        page = await store.list_entries(
            filters=filters,
            limit=_GRAPH_METRICS_PAGE_SIZE,
            offset=offset,
        )
        if not page:
            break
        for entry in page:
            matching_ids.add(entry.id)
        if len(page) < _GRAPH_METRICS_PAGE_SIZE:
            break
        offset += _GRAPH_METRICS_PAGE_SIZE
        # Safety bound — refuse to materialise an unbounded id set in memory.
        if len(matching_ids) >= _GRAPH_METRICS_MAX_IDS:
            logger.warning(
                "graph metrics: matching_ids exceeds %d cap; truncating",
                _GRAPH_METRICS_MAX_IDS,
            )
            break

    return [r for r in relations if r["from_id"] in matching_ids and r["to_id"] in matching_ids]


async def _collect_ego_relations(
    store: Any,
    *,
    root_id: str,
    hops: int,
) -> list[dict[str, Any]]:
    """BFS the relations graph from ``root_id`` to ``hops`` depth and collect edges."""
    visited: set[str] = {root_id}
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    queue: deque[tuple[str, int]] = deque([(root_id, 0)])

    while queue:
        node_id, depth = queue.popleft()
        if depth >= hops:
            continue
        neighbours = await store.get_related(node_id, direction="both", relation_type=None)
        for row in neighbours:
            from_id = row["from_id"]
            to_id = row["to_id"]
            rel_type = row["relation_type"]
            edge_key = (from_id, to_id, rel_type)
            if edge_key not in edge_keys:
                edge_keys.add(edge_key)
                edges.append(
                    {
                        "from_id": from_id,
                        "to_id": to_id,
                        "relation_type": rel_type,
                    }
                )
            if from_id == node_id:
                other = to_id
            elif to_id == node_id:
                other = from_id
            else:
                continue
            if other not in visited:
                visited.add(other)
                queue.append((other, depth + 1))
    return edges


async def _handle_metrics(  # noqa: PLR0911, PLR0912
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Compute graph metrics on the relations subgraph.

    See module docstring for the response envelope and failure modes.
    """
    # NetworkX availability gate.
    from distillery.graph import is_available

    if not is_available():
        return error_response(
            "INTERNAL",
            "NetworkX not installed; run: pip install distillery-mcp[graph]",
        )

    # ----- metric -----
    metric_raw = arguments.get("metric")
    if metric_raw is None or not isinstance(metric_raw, str):
        return error_response("INVALID_PARAMS", "metric is required for action='metrics'")
    metric = metric_raw.strip().lower()
    if metric not in _VALID_METRICS:
        return error_response(
            "INVALID_PARAMS",
            f"metric must be one of {sorted(_VALID_METRICS)}, got: {metric_raw!r}",
        )

    # ----- scope -----
    scope_raw = arguments.get("scope", "global")
    if not isinstance(scope_raw, str):
        return error_response(
            "INVALID_PARAMS",
            f"scope must be a string, got: {type(scope_raw).__name__}",
        )
    scope = scope_raw.strip().lower() or "global"
    if scope not in _VALID_SCOPES:
        return error_response(
            "INVALID_PARAMS",
            f"scope must be one of {sorted(_VALID_SCOPES)}, got: {scope_raw!r}",
        )

    # ----- entry_id (required for ego scope) -----
    entry_id_value, err = _validate_optional_str(arguments, "entry_id")
    if err is not None:
        return err
    if scope == "ego" and not entry_id_value:
        return error_response(
            "INVALID_PARAMS",
            "entry_id is required when scope='ego'",
        )

    # ----- limit -----
    limit_raw = arguments.get("limit", 10)
    if isinstance(limit_raw, bool) or not isinstance(limit_raw, int) or limit_raw < 1:
        return error_response("INVALID_PARAMS", "limit must be a positive integer")
    limit = int(limit_raw)

    # ----- entry-side filters (global scope only) -----
    project, err = _validate_optional_str(arguments, "project")
    if err is not None:
        return err
    tags, err = _validate_optional_str_list(arguments, "tags")
    if err is not None:
        return err
    date_from, err = _validate_optional_str(arguments, "date_from")
    if err is not None:
        return err
    date_to, err = _validate_optional_str(arguments, "date_to")
    if err is not None:
        return err

    # ----- cache lookup -----
    from distillery.graph.builders import build_relations_graph
    from distillery.graph.cache import default_cache
    from distillery.graph.metrics import bridges, communities

    cache = default_cache()
    cache_key = (
        f"{scope}:{entry_id_value or ''}:{project or ''}:"
        f"{','.join(tags or [])}:{date_from or ''}:{date_to or ''}"
    )
    cached_graph = cache.get(cache_key)
    cache_hit = cached_graph is not None

    # ----- assemble graph (fetch + build) on miss -----
    try:
        if cached_graph is None:
            if scope == "ego":
                # Verify root exists before traversal.
                assert entry_id_value is not None  # for mypy — checked above
                root_id = entry_id_value
                root_entry = await store.get(root_id)
                if root_entry is None:
                    return error_response("NOT_FOUND", f"Entry not found: {root_id!r}")
                relations = await _collect_ego_relations(
                    store, root_id=root_id, hops=_METRICS_EGO_HOPS
                )
            else:
                relations = await _collect_global_relations(
                    store,
                    project=project,
                    tags=tags,
                    date_from=date_from,
                    date_to=date_to,
                )
            g = build_relations_graph(relations, directed=True)
            cache.set(cache_key, g)
        else:
            g = cached_graph
    except RuntimeError:
        # build_relations_graph raises this when nx is missing — but we already
        # gated on is_available() above, so this is purely a defensive path.
        # Log the raw exception server-side; never leak it to the client.
        logger.exception("distillery_relations metrics: runtime error during graph build")
        return error_response("INTERNAL", "Failed to build relations graph")
    except Exception:  # noqa: BLE001
        logger.exception("distillery_relations metrics: failed to build graph")
        return error_response("INTERNAL", "Failed to build relations graph")

    # ----- compute metric -----
    try:
        if metric == "bridges":
            ranked = bridges(g, k=limit)
            results: list[dict[str, Any]] = [
                {"id": node, "score": round(score, 6)} for node, score in ranked
            ]
        else:  # metric == "communities"
            comms = communities(g)
            comms_sorted = sorted(comms, key=lambda c: len(c), reverse=True)[:limit]
            results = [{"members": sorted(c)} for c in comms_sorted]
    except Exception:  # noqa: BLE001
        logger.exception("distillery_relations metrics: metric computation failed")
        return error_response("INTERNAL", "Failed to compute graph metric")

    return success_response(
        {
            "action": "metrics",
            "metric": metric,
            "scope": scope,
            "node_count": g.number_of_nodes(),
            "edge_count": g.number_of_edges(),
            "results": results,
            "count": len(results),
            "computed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cache_hit": cache_hit,
        }
    )
