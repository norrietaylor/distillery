"""Quality tool handlers for the Distillery MCP server.

Implements the following tools:
  - distillery_check_dedup: Run deduplication check against the store and return
    an action (create/skip/merge/link) with similar entries.
  - distillery_check_conflicts: Two-pass conflict detection — first pass returns
    conflict candidates with prompts; second pass processes LLM responses and
    returns confirmed conflicts.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp import types

from distillery.config import DistilleryConfig
from distillery.mcp.budget import EmbeddingBudgetError, record_and_check
from distillery.mcp.tools._common import (
    error_response,
    success_response,
    validate_required,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# _handle_check_dedup
# ---------------------------------------------------------------------------


async def _handle_check_dedup(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_check_dedup`` tool.

    Runs :class:`~distillery.classification.dedup.DeduplicationChecker` against
    the store using thresholds from *config* and returns the deduplication
    result as a JSON payload.

    Args:
        store: Initialised store with a ``find_similar`` method.
        config: Loaded :class:`~distillery.config.DistilleryConfig` (dedup
            thresholds are read from ``config.classification``).
        arguments: Tool argument dict. Must contain ``"content"`` (str).

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    # --- validate input -----------------------------------------------------
    err = validate_required(arguments, "content")
    if err:
        return error_response("INVALID_INPUT", err)

    content = str(arguments["content"])

    # --- embedding budget check (1 embed call for find_similar) -------------
    try:
        record_and_check(store.connection, config.rate_limit.embedding_budget_daily)
    except EmbeddingBudgetError as exc:
        return error_response("BUDGET_EXCEEDED", str(exc))

    # --- run dedup checker --------------------------------------------------
    from distillery.classification.dedup import DeduplicationChecker

    cls_cfg = config.classification
    checker = DeduplicationChecker(
        store=store,
        skip_threshold=cls_cfg.dedup_skip_threshold,
        merge_threshold=cls_cfg.dedup_merge_threshold,
        link_threshold=cls_cfg.dedup_link_threshold,
        dedup_limit=cls_cfg.dedup_limit,
    )

    try:
        result = await checker.check(content)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error running dedup check")
        return error_response("DEDUP_ERROR", f"Deduplication check failed: {exc}")

    # --- serialise result ---------------------------------------------------
    similar_entries_serialised = []
    for sr in result.similar_entries:
        similar_entries_serialised.append(
            {
                "entry_id": str(sr.entry.id),
                "score": sr.score,
                "content_preview": sr.entry.content[:120],
                "entry_type": sr.entry.entry_type.value,
                "author": sr.entry.author,
                "project": sr.entry.project,
                "created_at": sr.entry.created_at.isoformat() if sr.entry.created_at else None,
            }
        )

    return success_response(
        {
            "action": result.action.value,
            "highest_score": result.highest_score,
            "reasoning": result.reasoning,
            "similar_entries": similar_entries_serialised,
        }
    )


# ---------------------------------------------------------------------------
# _handle_check_conflicts
# ---------------------------------------------------------------------------


async def _handle_check_conflicts(
    store: Any,
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Implement the ``distillery_check_conflicts`` tool.

    Supports a two-pass workflow:

    **First pass** (``llm_responses`` absent or ``None``):
    - Calls :class:`~distillery.classification.conflict.ConflictChecker` with
      ``llm_responses=None`` to discover candidate entry IDs.
    - Returns ``conflict_candidates`` with a prompt for each candidate pair so
      the calling LLM can evaluate them.

    **Second pass** (``llm_responses`` provided):
    - Converts the supplied ``{entry_id: {is_conflict, reasoning}}`` dict to
      the ``(bool, str)`` tuple format expected by
      :meth:`~distillery.classification.conflict.ConflictChecker.check`.
    - Returns the serialised :class:`~distillery.classification.conflict.ConflictResult`.

    Args:
        store: Initialised store with a ``find_similar`` method.
        config: Loaded :class:`~distillery.config.DistilleryConfig` (conflict
            threshold is read from ``config.classification.conflict_threshold``).
        arguments: Tool argument dict.  Must contain ``"content"`` (str).
            Optionally contains ``"llm_responses"`` (dict).

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    from distillery.classification.conflict import ConflictChecker

    # --- validate input -----------------------------------------------------
    err = validate_required(arguments, "content")
    if err:
        return error_response("INVALID_INPUT", err)

    content = str(arguments["content"])

    llm_responses_raw: dict[str, Any] | None = arguments.get("llm_responses")
    if llm_responses_raw is not None and not isinstance(llm_responses_raw, dict):
        return error_response("INVALID_INPUT", "Field 'llm_responses' must be an object")

    # --- build checker -------------------------------------------------------
    threshold = config.classification.conflict_threshold
    checker = ConflictChecker(store=store, threshold=threshold)

    # --- first pass: discover candidates (no llm_responses) ------------------
    if not llm_responses_raw:
        try:
            # Call check with no LLM responses to find similar entries.
            await checker.check(content, llm_responses=None)

            # Retrieve similar entries to build prompts for the caller.
            from distillery.classification.conflict import _DEFAULT_CONFLICT_LIMIT

            similar = await store.find_similar(
                content=content,
                threshold=threshold,
                limit=_DEFAULT_CONFLICT_LIMIT,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error during conflict discovery pass")
            return error_response("CONFLICT_ERROR", f"Conflict check failed: {exc}")

        if not similar:
            return success_response(
                {
                    "has_conflicts": False,
                    "conflicts": [],
                    "conflict_candidates": [],
                    "message": "No similar entries found above the conflict threshold.",
                }
            )

        candidates = []
        for result in similar:
            lines = result.entry.content.splitlines()
            preview = lines[0][:120] if lines else result.entry.content[:120]
            prompt = checker.build_prompt(content, result.entry.content)
            candidates.append(
                {
                    "entry_id": result.entry.id,
                    "content_preview": preview,
                    "similarity_score": round(result.score, 4),
                    "conflict_prompt": prompt,
                }
            )

        return success_response(
            {
                "has_conflicts": False,
                "conflicts": [],
                "conflict_candidates": candidates,
                "message": (
                    f"Found {len(candidates)} conflict "
                    f"{'candidate' if len(candidates) == 1 else 'candidates'}. "
                    "Evaluate each conflict_prompt with an LLM and call "
                    "distillery_check_conflicts again with llm_responses."
                ),
            }
        )

    # --- second pass: process LLM responses ----------------------------------
    # Convert {entry_id: {is_conflict: bool, reasoning: str}} ->
    #         {entry_id: (bool, str)}
    llm_responses: dict[str, tuple[bool, str]] = {}
    for entry_id, response_obj in llm_responses_raw.items():
        if not isinstance(response_obj, dict):
            return error_response(
                "INVALID_INPUT",
                f"llm_responses[{entry_id!r}] must be an object with 'is_conflict' and 'reasoning'.",
            )
        is_conflict_raw = response_obj.get("is_conflict")
        if is_conflict_raw is None:
            return error_response(
                "INVALID_INPUT",
                f"llm_responses[{entry_id!r}] is missing required field 'is_conflict'.",
            )
        reasoning = str(response_obj.get("reasoning", ""))
        llm_responses[str(entry_id)] = (bool(is_conflict_raw), reasoning)

    try:
        result = await checker.check(content, llm_responses=llm_responses)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error during conflict evaluation pass")
        return error_response("CONFLICT_ERROR", f"Conflict check failed: {exc}")

    # Serialise ConflictResult.
    conflicts_serialised = [
        {
            "entry_id": conflict.entry_id,
            "content_preview": conflict.content_preview,
            "similarity_score": round(conflict.similarity_score, 4),
            "conflict_reasoning": conflict.conflict_reasoning,
        }
        for conflict in result.conflicts
    ]

    return success_response(
        {
            "has_conflicts": result.has_conflicts,
            "conflicts": conflicts_serialised,
        }
    )


__all__ = [
    "_handle_check_dedup",
    "_handle_check_conflicts",
]
