"""Relevance scorer for ambient feed items.

Scores an incoming :class:`~distillery.feeds.models.FeedItem` against the
knowledge base by embedding the item text and running a similarity search.
The score is the maximum cosine similarity found across all matching entries,
optionally boosted by alignment with the user's :class:`InterestProfile`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from distillery.feeds.interests import InterestProfile
    from distillery.store.protocol import DistilleryStore, SearchResult

logger = logging.getLogger(__name__)

# Default limit for find_similar calls during scoring.
_SCORE_LIMIT = 10

# Maximum boost applied when an item's matching tags overlap with top interests.
_INTEREST_BOOST_MAX = 0.15


class RelevanceScorer:
    """Score feed items against the Distillery knowledge base.

    Embeds the item text and calls
    :meth:`~distillery.store.protocol.DistilleryStore.find_similar` to find the
    most semantically similar entries already stored.  The final relevance
    score is the maximum cosine similarity returned (``0.0`` when no entries
    exist in the store), optionally boosted by interest profile alignment.

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
    interest_profile:
        An optional :class:`~distillery.feeds.interests.InterestProfile`.
        When provided, items whose matching entries share tags with the
        profile's top tags receive a relevance boost (up to
        ``_INTEREST_BOOST_MAX``).

    Example::

        from distillery.feeds.scorer import RelevanceScorer

        scorer = RelevanceScorer(store=my_store, interest_profile=profile)
        score = await scorer.score(item)
    """

    def __init__(
        self,
        store: DistilleryStore,
        *,
        min_score: float = 0.0,
        limit: int = _SCORE_LIMIT,
        interest_profile: InterestProfile | None = None,
    ) -> None:
        self._store = store
        self._min_score = min_score
        self._limit = limit
        self._interest_profile = interest_profile
        # Pre-compute interest tag set for fast lookup.
        self._interest_tags: set[str] = set()
        self._interest_weights: dict[str, float] = {}
        if interest_profile and interest_profile.top_tags:
            self._interest_tags = {tag for tag, _ in interest_profile.top_tags}
            self._interest_weights = dict(interest_profile.top_tags)

    async def score(self, text: str) -> float:
        """Score *text* against the knowledge base.

        Calls ``find_similar`` with *min_score* and returns the maximum
        similarity score found, plus an optional interest-profile boost.
        Returns ``0.0`` when no similar entries are found.

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
        except Exception:
            logger.exception("RelevanceScorer: find_similar failed for text %r", text[:80])
            raise

        if not results:
            return 0.0

        base_score = max(r.score for r in results)

        # Apply interest-profile boost when available.
        if self._interest_tags and results:
            boost = self._compute_interest_boost(results)
            return min(base_score + boost, 1.0)

        return base_score

    def _compute_interest_boost(
        self,
        results: Sequence[SearchResult],
    ) -> float:
        """Compute a boost based on how well matching entries align with interests.

        Examines the tags of the top matching entries and computes a weighted
        overlap with the user's interest profile.  The boost is capped at
        ``_INTEREST_BOOST_MAX``.

        Args:
            results: Similarity search results (each has ``.entry.tags``).

        Returns:
            A boost value in ``[0.0, _INTEREST_BOOST_MAX]``.
        """
        if not self._interest_tags:
            return 0.0

        total_weight = 0.0
        matched_tags = 0

        for result in results[:5]:
            entry_tags = set(result.entry.tags or [])
            overlapping = entry_tags & self._interest_tags
            for tag in overlapping:
                total_weight += self._interest_weights.get(tag, 0.0)
                matched_tags += 1

        if matched_tags == 0:
            return 0.0

        # Normalise: average weight of matched tags, scaled to boost range.
        avg_weight = total_weight / matched_tags
        return avg_weight * _INTEREST_BOOST_MAX
