"""Deduplication checker for Distillery.

This module provides :class:`DeduplicationChecker`, which uses
:meth:`~distillery.store.protocol.DistilleryStore.find_similar` to detect
near-duplicate content before a new entry is stored.

The checker applies configurable similarity thresholds to recommend one of
four actions: ``skip`` (exact duplicate), ``merge`` (very similar),
``link`` (related), or ``create`` (novel content).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .models import DeduplicationAction, DeduplicationResult

if TYPE_CHECKING:
    from distillery.store.protocol import DistilleryStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default threshold constants
# ---------------------------------------------------------------------------

_DEFAULT_SKIP_THRESHOLD: float = 0.95
_DEFAULT_MERGE_THRESHOLD: float = 0.80
_DEFAULT_LINK_THRESHOLD: float = 0.60
_DEFAULT_DEDUP_LIMIT: int = 5


# ---------------------------------------------------------------------------
# DeduplicationChecker
# ---------------------------------------------------------------------------


class DeduplicationChecker:
    """Check whether new content duplicates existing entries.

    The checker queries the store for similar entries and maps the highest
    similarity score to one of four actions using configurable thresholds.

    Parameters
    ----------
    store:
        A :class:`~distillery.store.protocol.DistilleryStore` instance used
        to call :meth:`find_similar`.
    skip_threshold:
        Similarity score at or above which the content is considered a
        duplicate.  Default ``0.95``.
    merge_threshold:
        Similarity score at or above which (but below *skip_threshold*) the
        content should be merged with the most similar entry.  Default
        ``0.80``.
    link_threshold:
        Similarity score at or above which (but below *merge_threshold*) a
        new entry should be linked to similar entries.  Default ``0.60``.
    dedup_limit:
        Maximum number of similar entries to retrieve from the store.
        Default ``5``.

    Example::

        from distillery.classification import DeduplicationChecker

        checker = DeduplicationChecker(store=my_store)
        result = await checker.check("Explored the auth module")
        if result.action == DeduplicationAction.SKIP:
            return result.similar_entries[0].entry.id
    """

    def __init__(
        self,
        store: DistilleryStore,
        *,
        skip_threshold: float = _DEFAULT_SKIP_THRESHOLD,
        merge_threshold: float = _DEFAULT_MERGE_THRESHOLD,
        link_threshold: float = _DEFAULT_LINK_THRESHOLD,
        dedup_limit: int = _DEFAULT_DEDUP_LIMIT,
    ) -> None:
        self._store = store
        self._skip_threshold = skip_threshold
        self._merge_threshold = merge_threshold
        self._link_threshold = link_threshold
        self._dedup_limit = dedup_limit

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def check(self, content: str) -> DeduplicationResult:
        """Evaluate *content* for deduplication and return a recommended action.

        Calls :meth:`~distillery.store.protocol.DistilleryStore.find_similar`
        with *link_threshold* as the minimum score, so any entry above the
        lowest threshold is returned.  The highest-scoring result is used to
        select the action.

        Args:
            content: The raw text of the candidate new entry.

        Returns:
            A :class:`~distillery.classification.models.DeduplicationResult`
            with the recommended action and any similar entries found.
        """
        similar = await self._store.find_similar(
            content=content,
            threshold=self._link_threshold,
            limit=self._dedup_limit,
        )

        if not similar:
            return DeduplicationResult(
                action=DeduplicationAction.CREATE,
                similar_entries=[],
                highest_score=0.0,
                reasoning="No similar entries found above the link threshold. Create a new entry.",
            )

        # Results are sorted by descending score; first is highest.
        highest = similar[0]
        score = highest.score
        first_line = highest.entry.content.splitlines()[0][:80]

        action, reasoning = self._decide(score, first_line)

        return DeduplicationResult(
            action=action,
            similar_entries=similar,
            highest_score=score,
            reasoning=reasoning,
        )

    def check_sync(self, content: str) -> DeduplicationResult:
        """Synchronous wrapper around :meth:`check`.

        Runs the coroutine in a new event loop.  Do **not** call this from
        inside an already-running event loop; prefer :meth:`check` in that
        case.

        Args:
            content: The raw text of the candidate new entry.

        Returns:
            A :class:`~distillery.classification.models.DeduplicationResult`.
        """
        return asyncio.run(self.check(content))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _decide(self, score: float, first_line: str) -> tuple[DeduplicationAction, str]:
        """Map a similarity *score* to an action and reasoning string.

        Args:
            score: Cosine similarity score of the most similar entry.
            first_line: First line of the most similar entry's content (for
                the reasoning message).

        Returns:
            A ``(action, reasoning)`` tuple.
        """
        if score >= self._skip_threshold:
            return (
                DeduplicationAction.SKIP,
                f"Content is a near-duplicate (score={score:.3f}) of an existing entry: "
                f'"{first_line}". Recommend skipping to avoid duplication.',
            )

        if score >= self._merge_threshold:
            return (
                DeduplicationAction.MERGE,
                f"Content is very similar (score={score:.3f}) to an existing entry: "
                f'"{first_line}". Recommend merging new details into the existing entry.',
            )

        # score >= self._link_threshold (guaranteed by find_similar threshold)
        return (
            DeduplicationAction.LINK,
            f"Content is related (score={score:.3f}) to an existing entry: "
            f'"{first_line}". Recommend creating a new entry and linking it to the similar one.',
        )