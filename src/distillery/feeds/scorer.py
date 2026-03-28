"""Relevance scorer for ambient feed items.

Scores an incoming :class:`~distillery.feeds.models.FeedItem` against the
knowledge base by embedding the item text and running a similarity search.
The score is the maximum cosine similarity found across all matching entries.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from distillery.store.protocol import DistilleryStore

logger = logging.getLogger(__name__)

# Default limit for find_similar calls during scoring.
_SCORE_LIMIT = 10


class RelevanceScorer:
    """Score feed items against the Distillery knowledge base.

    Embeds the item text and calls
    :meth:`~distillery.store.protocol.DistilleryStore.find_similar` to find the
    most semantically similar entries already stored.  The final relevance
    score is the maximum cosine similarity returned (``0.0`` when no entries
    exist in the store).

    Parameters
    ----------
    store:
        An initialised :class:`~distillery.store.protocol.DistilleryStore`.
    min_score:
        Minimum similarity threshold passed to ``find_similar``.  Only
        entries at or above this value are considered.  Defaults to ``0.0``
        (return all results, let the caller decide).
    limit:
        Maximum number of similar entries to retrieve per scoring call.
        Defaults to ``10``.

    Example::

        from distillery.feeds.scorer import RelevanceScorer

        scorer = RelevanceScorer(store=my_store)
        score = await scorer.score(item)
    """

    def __init__(
        self,
        store: DistilleryStore,
        *,
        min_score: float = 0.0,
        limit: int = _SCORE_LIMIT,
    ) -> None:
        self._store = store
        self._min_score = min_score
        self._limit = limit

    async def score(self, text: str) -> float:
        """Score *text* against the knowledge base.

        Calls ``find_similar`` with *min_score* and returns the maximum
        similarity score found.  Returns ``0.0`` when no similar entries are
        found.

        Args:
            text: The raw text to score (title + content of a feed item, for
                example).

        Returns:
            A cosine similarity score in ``[0.0, 1.0]``.  Higher means the
            item is more relevant to the stored knowledge.
        """
        if not text.strip():
            return 0.0

        try:
            results = await self._store.find_similar(
                content=text,
                threshold=self._min_score,
                limit=self._limit,
            )
        except Exception:  # noqa: BLE001
            logger.exception("RelevanceScorer: find_similar failed for text %r", text[:80])
            return 0.0

        if not results:
            return 0.0

        return max(r.score for r in results)
