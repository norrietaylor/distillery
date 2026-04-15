"""Relations tool handler for the Distillery MCP server.

Implements the following tool:
  - distillery_relations: Manage typed relations between knowledge entries.
    Actions: 'add', 'get', 'remove'.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp import types

from distillery.mcp.tools._common import (
    error_response,
    success_response,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# distillery_relations handler
# ---------------------------------------------------------------------------

_VALID_DIRECTIONS = {"outgoing", "incoming", "both"}

_VALID_RELATION_TYPES = {
    "link",
    "merge_source",
    "sync_source",
    "corrects",
    "supersedes",
    "related",
    "blocks",
    "depends_on",
    "citation",
    "duplicate",
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

    if action not in ("add", "get", "remove"):
        return error_response(
            "INVALID_PARAMS",
            f"action must be one of 'add', 'get', 'remove'; got: {action!r}",
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
