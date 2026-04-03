"""Importable helpers for deduplication and conflict detection.

Provides standalone async helper functions that can be imported by other
modules (e.g. ``search.py``).  These helpers accept typed arguments and
return typed dicts -- they do NOT depend on MCP handler signatures.

The ``distillery_check_dedup`` and ``distillery_check_conflicts`` tools have
been removed; their functionality is now available via
``distillery_find_similar(dedup_action=True)`` and
``distillery_find_similar(conflict_check=True)`` respectively.
"""

from __future__ import annotations

import logging
from typing import Any

from distillery.config import ClassificationConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: dedup check
# ---------------------------------------------------------------------------


async def run_dedup_check(
    store: Any,
    classification_config: ClassificationConfig,
    content: str,
) -> dict[str, Any]:
    """Run a deduplication check and return the result as a plain dict.

    This is a standalone helper that does NOT depend on MCP handler signatures.
    It can be imported and called directly from any module (e.g. ``search.py``).

    Args:
        store: Initialised store with a ``find_similar`` method.
        classification_config: Classification configuration containing dedup
            thresholds (``dedup_skip_threshold``, ``dedup_merge_threshold``,
            ``dedup_link_threshold``, ``dedup_limit``).
        content: The text content to check for duplicates.

    Returns:
        A dict with keys ``action`` (str), ``highest_score`` (float),
        ``reasoning`` (str), and ``similar_entries`` (list of dicts with
        ``entry_id``, ``score``, ``content_preview``, ``entry_type``,
        ``author``, ``project``, ``created_at``).

    Raises:
        Exception: Propagates any exception from the store or dedup checker.
    """
    from distillery.classification.dedup import DeduplicationChecker

    checker = DeduplicationChecker(
        store=store,
        skip_threshold=classification_config.dedup_skip_threshold,
        merge_threshold=classification_config.dedup_merge_threshold,
        link_threshold=classification_config.dedup_link_threshold,
        dedup_limit=classification_config.dedup_limit,
    )

    result = await checker.check(content)

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

    return {
        "action": result.action.value,
        "highest_score": result.highest_score,
        "reasoning": result.reasoning,
        "similar_entries": similar_entries_serialised,
    }


# ---------------------------------------------------------------------------
# Standalone helper: conflict discovery (first pass)
# ---------------------------------------------------------------------------


async def run_conflict_discovery(
    store: Any,
    threshold: float,
    content: str,
) -> dict[str, Any]:
    """Discover conflict candidates and return prompts for LLM evaluation.

    This is the first pass of the two-pass conflict workflow.  It finds
    similar entries above *threshold* and builds an LLM prompt for each
    candidate pair.

    Args:
        store: Initialised store with a ``find_similar`` method.
        threshold: Minimum cosine similarity for a stored entry to be
            considered a conflict candidate.
        content: The text content to check for conflicts.

    Returns:
        A dict with keys ``has_conflicts`` (always ``False`` in first pass),
        ``conflicts`` (always ``[]``), ``conflict_candidates`` (list of dicts
        with ``entry_id``, ``content_preview``, ``similarity_score``,
        ``conflict_prompt``), and ``message`` (str).

    Raises:
        Exception: Propagates any exception from the store or conflict checker.
    """
    from distillery.classification.conflict import _DEFAULT_CONFLICT_LIMIT, ConflictChecker

    checker = ConflictChecker(store=store, threshold=threshold)

    # Call check with no LLM responses to find similar entries.
    await checker.check(content, llm_responses=None)

    # Retrieve similar entries to build prompts for the caller.
    similar = await store.find_similar(
        content=content,
        threshold=threshold,
        limit=_DEFAULT_CONFLICT_LIMIT,
    )

    if not similar:
        return {
            "has_conflicts": False,
            "conflicts": [],
            "conflict_candidates": [],
            "message": "No similar entries found above the conflict threshold.",
        }

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

    return {
        "has_conflicts": False,
        "conflicts": [],
        "conflict_candidates": candidates,
        "message": (
            f"Found {len(candidates)} conflict "
            f"{'candidate' if len(candidates) == 1 else 'candidates'}. "
            "Evaluate each conflict_prompt with an LLM and call "
            "distillery_find_similar(conflict_check=true, llm_responses=...) to confirm."
        ),
    }


# ---------------------------------------------------------------------------
# Standalone helper: conflict evaluation (second pass)
# ---------------------------------------------------------------------------


async def run_conflict_evaluation(
    store: Any,
    threshold: float,
    content: str,
    llm_responses: dict[str, tuple[bool, str]],
) -> dict[str, Any]:
    """Evaluate conflict candidates using LLM responses and return results.

    This is the second pass of the two-pass conflict workflow.  It takes
    pre-parsed LLM responses and returns which entries are confirmed
    conflicts.

    Args:
        store: Initialised store with a ``find_similar`` method.
        threshold: Minimum cosine similarity used for conflict detection.
        content: The text content that was checked for conflicts.
        llm_responses: Mapping from entry ID to ``(is_conflict, reasoning)``
            tuple as parsed from LLM output.

    Returns:
        A dict with keys ``has_conflicts`` (bool) and ``conflicts``
        (list of dicts with ``entry_id``, ``content_preview``,
        ``similarity_score``, ``conflict_reasoning``).

    Raises:
        Exception: Propagates any exception from the store or conflict checker.
    """
    from distillery.classification.conflict import ConflictChecker

    checker = ConflictChecker(store=store, threshold=threshold)
    result = await checker.check(content, llm_responses=llm_responses)

    conflicts_serialised = [
        {
            "entry_id": conflict.entry_id,
            "content_preview": conflict.content_preview,
            "similarity_score": round(conflict.similarity_score, 4),
            "conflict_reasoning": conflict.conflict_reasoning,
        }
        for conflict in result.conflicts
    ]

    return {
        "has_conflicts": result.has_conflicts,
        "conflicts": conflicts_serialised,
    }


__all__ = [
    "run_dedup_check",
    "run_conflict_discovery",
    "run_conflict_evaluation",
]
