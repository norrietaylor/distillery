"""Relations tool handler for the Distillery MCP server.

Implements the following tool:
  - distillery_relations: Manage typed relations between knowledge entries.
    Actions: 'add', 'get', 'remove', 'traverse'.
"""

from __future__ import annotations

import logging
from collections import deque
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

    if action not in ("add", "get", "remove", "traverse"):
        return error_response(
            "INVALID_PARAMS",
            f"action must be one of 'add', 'get', 'remove', 'traverse'; got: {action!r}",
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
