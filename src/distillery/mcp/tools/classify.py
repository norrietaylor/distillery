"""Classification tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_classify: Store a pre-computed classification result onto an existing entry
  - distillery_resolve_review: Approve, reclassify, or archive a pending-review entry

Note: review queue listing is handled by distillery_list with output_mode="review".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.mcp.tools._common import (
    error_response,
    success_response,
    validate_required,
    validate_type,
)
from distillery.mcp.tools.crud import _VALID_ENTRY_TYPES

logger = logging.getLogger(__name__)

# Valid resolve-review actions.
_VALID_REVIEW_ACTIONS = {"approve", "reclassify", "archive"}


# ---------------------------------------------------------------------------
# _handle_classify
# ---------------------------------------------------------------------------


async def _handle_classify(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_classify`` tool.

    Stores a pre-computed classification result onto an existing entry.
    Updates the entry's type, status, and classification metadata fields.
    Handles reclassification of already-classified entries.

    Args:
        store: Initialised ``DuckDBStore``.
        config: The loaded Distillery configuration (for confidence threshold).
        arguments: Raw MCP tool arguments dict.

    Returns:
        MCP content list with the serialised updated entry or an error.
    """

    from distillery.models import EntryStatus, EntryType, validate_tag

    # --- input validation ---------------------------------------------------
    err = validate_required(arguments, "entry_id", "entry_type", "confidence")
    if err:
        return error_response("INVALID_PARAMS", err)

    entry_id: str = arguments["entry_id"]
    entry_type_str: str = arguments["entry_type"]
    confidence_raw = arguments["confidence"]

    if entry_type_str not in _VALID_ENTRY_TYPES:
        return error_response(
            "INVALID_PARAMS",
            f"Invalid entry_type {entry_type_str!r}. "
            f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
        )

    if not isinstance(confidence_raw, (int, float)):
        return error_response("INVALID_PARAMS", "Field 'confidence' must be a number")
    confidence = float(confidence_raw)
    if not (0.0 <= confidence <= 1.0):
        return error_response("INVALID_PARAMS", "Field 'confidence' must be in [0.0, 1.0]")

    tags_err = validate_type(arguments, "suggested_tags", list, "list of strings")
    if tags_err:
        return error_response("INVALID_PARAMS", tags_err)

    # --- retrieve existing entry --------------------------------------------
    try:
        entry = await store.get(entry_id)
    except Exception:  # noqa: BLE001
        logger.exception("Error fetching entry id=%s for classify", entry_id)
        return error_response("INTERNAL", "Failed to retrieve entry")

    if entry is None:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )

    # --- build updates ------------------------------------------------------
    threshold = config.classification.confidence_threshold
    new_status = EntryStatus.ACTIVE if confidence >= threshold else EntryStatus.PENDING_REVIEW

    # Merge suggested tags with existing tags (de-duplicate, preserve order).
    # Filter out invalid tags from LLM suggestions to prevent validation failures.
    suggested_tags_raw = list(arguments.get("suggested_tags") or [])
    suggested_tags: list[str] = []
    for t in suggested_tags_raw:
        if not isinstance(t, str):
            logger.warning("Dropping non-string LLM-suggested tag: %r", t)
            continue
        try:
            validate_tag(t)
            suggested_tags.append(t)
        except ValueError:
            logger.warning("Dropping invalid LLM-suggested tag: %r", t)
    merged_tags = list(entry.tags) + [t for t in suggested_tags if t not in entry.tags]

    # Build updated metadata -- preserve existing metadata, add classification fields.
    new_metadata: dict[str, Any] = dict(entry.metadata)

    # If this entry was already classified, record the previous type.
    if "classified_at" in new_metadata:
        new_metadata["reclassified_from"] = entry.entry_type.value

    classified_at = datetime.now(tz=UTC).isoformat()
    new_metadata["confidence"] = confidence
    new_metadata["classified_at"] = classified_at
    if "reasoning" in arguments:
        new_metadata["classification_reasoning"] = arguments["reasoning"]

    suggested_project: str | None = arguments.get("suggested_project")

    updates: dict[str, Any] = {
        "entry_type": EntryType(entry_type_str),
        "status": new_status,
        "tags": merged_tags,
        "metadata": new_metadata,
    }
    if suggested_project and entry.project is None:
        updates["project"] = suggested_project

    # --- persist ------------------------------------------------------------
    try:
        updated_entry = await store.update(entry_id, updates)
    except KeyError:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Error updating entry id=%s during classify", entry_id)
        return error_response("INTERNAL", "Failed to update entry")

    return success_response(updated_entry.to_dict())


# ---------------------------------------------------------------------------
# _handle_resolve_review
# ---------------------------------------------------------------------------


async def _handle_resolve_review(
    store: Any,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_resolve_review`` tool.

    Resolves a pending-review entry by approving, reclassifying, or archiving
    it.

    * **approve**: sets ``status=active`` and records ``reviewed_at`` /
      ``reviewed_by`` in metadata.
    * **reclassify**: updates ``entry_type`` and sets ``reclassified_from`` in
      metadata.  Requires ``new_entry_type``.
    * **archive**: soft-deletes the entry by setting ``status=archived``.

    Args:
        store: Initialised ``DuckDBStore``.
        arguments: Raw MCP tool arguments dict.

    Returns:
        MCP content list with the serialised updated entry or an error.
    """

    from distillery.models import EntryStatus, EntryType

    # --- input validation ---------------------------------------------------
    err = validate_required(arguments, "entry_id", "action")
    if err:
        return error_response("INVALID_PARAMS", err)

    entry_id: str = arguments["entry_id"]
    action: str = arguments["action"]

    if action not in _VALID_REVIEW_ACTIONS:
        return error_response(
            "INVALID_PARAMS",
            f"Invalid action {action!r}. Must be one of: {', '.join(sorted(_VALID_REVIEW_ACTIONS))}.",
        )

    # --- retrieve existing entry --------------------------------------------
    try:
        entry = await store.get(entry_id)
    except Exception:  # noqa: BLE001
        logger.exception("Error fetching entry id=%s for resolve_review", entry_id)
        return error_response("INTERNAL", "Failed to retrieve entry")

    if entry is None:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )

    # --- build updates per action -------------------------------------------
    now = datetime.now(tz=UTC).isoformat()
    reviewer: str | None = arguments.get("reviewer")
    new_metadata: dict[str, Any] = dict(entry.metadata)

    updates: dict[str, Any] = {}

    if action == "approve":
        updates["status"] = EntryStatus.ACTIVE
        new_metadata["reviewed_at"] = now
        if reviewer:
            new_metadata["reviewed_by"] = reviewer
        updates["metadata"] = new_metadata

    elif action == "reclassify":
        new_type_str: str | None = arguments.get("new_entry_type")
        if not new_type_str:
            return error_response(
                "INVALID_PARAMS",
                "Field 'new_entry_type' is required when action='reclassify'.",
            )
        if new_type_str not in _VALID_ENTRY_TYPES:
            return error_response(
                "INVALID_PARAMS",
                f"Invalid new_entry_type {new_type_str!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_ENTRY_TYPES))}.",
            )
        new_metadata["reclassified_from"] = entry.entry_type.value
        new_metadata["reviewed_at"] = now
        if reviewer:
            new_metadata["reviewed_by"] = reviewer
        updates["entry_type"] = EntryType(new_type_str)
        updates["metadata"] = new_metadata

    elif action == "archive":
        updates["status"] = EntryStatus.ARCHIVED
        new_metadata["archived_at"] = now
        if reviewer:
            new_metadata["archived_by"] = reviewer
        updates["metadata"] = new_metadata

    # --- persist ------------------------------------------------------------
    try:
        updated_entry = await store.update(entry_id, updates)
    except KeyError:
        return error_response(
            "NOT_FOUND",
            f"No entry found with id={entry_id!r}.",
            details={"entry_id": entry_id},
        )
    except Exception:  # noqa: BLE001
        logger.exception("Error updating entry id=%s during resolve_review", entry_id)
        return error_response("INTERNAL", "Failed to update entry")

    return success_response(updated_entry.to_dict())


__all__ = [
    "_handle_classify",
    "_handle_resolve_review",
    "_VALID_REVIEW_ACTIONS",
]