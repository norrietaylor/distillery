"""Background feed poller for Distillery ambient monitoring.

The :class:`FeedPoller` iterates over all configured feed sources, polls each
adapter in turn, scores items against the knowledge base using
:class:`~distillery.feeds.scorer.RelevanceScorer`, and stores items whose
relevance score meets the configured threshold.

Deduplication is handled via ``find_similar(0.95)`` — items whose ``item_id``
has been seen before (as ``metadata.external_id``) or whose text is a
near-duplicate of an existing entry are skipped.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from distillery.feeds.scorer import RelevanceScorer

if TYPE_CHECKING:
    from distillery.config import DistilleryConfig, FeedSourceConfig
    from distillery.feeds.models import FeedItem
    from distillery.store.protocol import DistilleryStore

logger = logging.getLogger(__name__)

# Deduplication threshold: items whose content is ≥ this similar to existing
# entries are treated as duplicates and skipped.
_DEDUP_THRESHOLD = 0.95

# Default minimum relevance threshold to store an item.
_DEFAULT_RELEVANCE_THRESHOLD = 0.0


@dataclass
class PollResult:
    """Summary of a single feed-poll execution.

    Attributes:
        source_url: The URL of the feed source polled.
        source_type: Adapter type (``'rss'``, ``'github'``, …).
        items_fetched: Total number of items fetched from the adapter.
        items_stored: Number of items that passed scoring and were stored.
        items_skipped_dedup: Number of items skipped because they were
            near-duplicates of existing entries.
        items_below_threshold: Number of items skipped because their
            relevance score was below the minimum threshold.
        errors: List of error messages encountered during this poll.
        polled_at: UTC timestamp when the poll ran.
    """

    source_url: str
    source_type: str
    items_fetched: int = 0
    items_stored: int = 0
    items_skipped_dedup: int = 0
    items_below_threshold: int = 0
    errors: list[str] = field(default_factory=list)
    polled_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass
class PollerSummary:
    """Aggregate summary of a full poll cycle across all sources.

    Attributes:
        results: Per-source :class:`PollResult` instances.
        total_fetched: Sum of ``items_fetched`` across all sources.
        total_stored: Sum of ``items_stored`` across all sources.
        total_skipped_dedup: Sum of ``items_skipped_dedup`` across all sources.
        total_below_threshold: Sum of ``items_below_threshold`` across all sources.
        sources_polled: Number of sources polled.
        sources_errored: Number of sources that produced at least one error.
        started_at: UTC timestamp when the poll cycle began.
        finished_at: UTC timestamp when the poll cycle completed.
    """

    results: list[PollResult] = field(default_factory=list)
    total_fetched: int = 0
    total_stored: int = 0
    total_skipped_dedup: int = 0
    total_below_threshold: int = 0
    sources_polled: int = 0
    sources_errored: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    finished_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


def _item_text(item: FeedItem) -> str:
    """Build a single text string from a feed item for embedding.

    Concatenates title and content with a newline separator, falling back to
    whichever field is available.

    Args:
        item: The feed item to convert.

    Returns:
        A non-empty text string, or an empty string if both fields are absent.
    """
    parts: list[str] = []
    if item.title:
        parts.append(item.title)
    if item.content:
        parts.append(item.content)
    return "\n".join(parts)


def _build_adapter(source: FeedSourceConfig) -> Any:
    """Instantiate the correct adapter for *source*.

    Args:
        source: The configured feed source.

    Returns:
        An adapter instance with a ``.fetch()`` method.

    Raises:
        ValueError: If ``source.source_type`` is not a supported adapter type.
    """
    if source.source_type == "github":
        from distillery.feeds.github import GitHubAdapter

        return GitHubAdapter(url=source.url)
    elif source.source_type == "rss":
        from distillery.feeds.rss import RSSAdapter

        return RSSAdapter(url=source.url)
    else:
        raise ValueError(
            f"Unsupported source_type {source.source_type!r} for url {source.url!r}. "
            "Supported types: 'github', 'rss'."
        )


def _item_to_entry_kwargs(item: FeedItem, relevance_score: float) -> dict[str, Any]:
    """Convert a :class:`~distillery.feeds.models.FeedItem` to Entry constructor kwargs.

    Args:
        item: The normalised feed item.
        relevance_score: The computed cosine similarity score.

    Returns:
        A dict of keyword arguments for :class:`~distillery.models.Entry`.
    """
    from distillery.models import EntrySource, EntryType

    text = _item_text(item)
    metadata: dict[str, Any] = {
        "source_url": item.source_url,
        "source_type": item.source_type,
        "external_id": item.item_id,
        "relevance_score": relevance_score,
    }
    if item.title:
        metadata["title"] = item.title
    if item.url:
        metadata["item_url"] = item.url
    if item.published_at:
        metadata["published_at"] = item.published_at.isoformat()

    return {
        "content": text or item.source_url,
        "entry_type": EntryType.FEED,
        "source": EntrySource.IMPORT,
        "author": "distillery-poller",
        "metadata": metadata,
    }


class FeedPoller:
    """Poll all configured feed sources and store relevant items.

    The poller iterates over the ``feeds.sources`` list in *config*, fetches
    new items from each source using the appropriate adapter, scores each item
    against the knowledge base, and stores items that pass both the dedup check
    and the relevance threshold.

    .. note::

       ``FeedSourceConfig.poll_interval_minutes`` is **not** consulted by this
       class.  Scheduling is the caller's responsibility (e.g. the MCP
       ``distillery_poll`` tool or an external cron job).  The field exists in
       configuration for documentation and future use by an external scheduler.

    Parameters
    ----------
    store:
        An initialised :class:`~distillery.store.protocol.DistilleryStore`.
    config:
        The :class:`~distillery.config.DistilleryConfig` containing feed
        sources and threshold settings.
    relevance_threshold:
        Minimum relevance score required to store an item.  When ``None``
        the value from ``config.feeds.thresholds.digest`` is used.

    Example::

        from distillery.feeds.poller import FeedPoller

        poller = FeedPoller(store=my_store, config=my_config)
        summary = await poller.poll()
    """

    def __init__(
        self,
        store: DistilleryStore,
        config: DistilleryConfig,
        *,
        relevance_threshold: float | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._threshold = (
            relevance_threshold
            if relevance_threshold is not None
            else config.feeds.thresholds.digest
        )

    async def poll(self, *, source_url: str | None = None) -> PollerSummary:
        """Execute a full poll cycle across configured sources.

        When *source_url* is given, only that single source is polled.
        Otherwise all persisted feed sources are polled.

        Returns:
            A :class:`PollerSummary` with per-source and aggregate statistics.
        """
        summary = PollerSummary(started_at=datetime.now(tz=UTC))

        from distillery.config import FeedSourceConfig

        db_sources = await self._store.list_feed_sources()
        if source_url is not None:
            db_sources = [s for s in db_sources if s["url"] == source_url]
        sources = [FeedSourceConfig(**s) for s in db_sources]
        if not sources:
            logger.debug("FeedPoller: no sources configured — skipping poll")
            summary.finished_at = datetime.now(tz=UTC)
            return summary

        # Build interest profile for relevance boosting.
        interest_profile = None
        try:
            from distillery.feeds.interests import InterestExtractor

            extractor = InterestExtractor(
                store=self._store,
            )
            interest_profile = await extractor.extract()
            logger.debug(
                "FeedPoller: built interest profile with %d entries, %d top tags",
                interest_profile.entry_count,
                len(interest_profile.top_tags),
            )
        except Exception:  # noqa: BLE001
            logger.debug("FeedPoller: interest profile extraction failed — scoring without boost")

        scorer = RelevanceScorer(
            store=self._store,
            min_score=0.0,
            interest_profile=interest_profile,
        )

        for source in sources:
            result = await self._poll_source(source, scorer)
            summary.results.append(result)
            summary.total_fetched += result.items_fetched
            summary.total_stored += result.items_stored
            summary.total_skipped_dedup += result.items_skipped_dedup
            summary.total_below_threshold += result.items_below_threshold
            summary.sources_polled += 1
            if result.errors:
                summary.sources_errored += 1

        summary.finished_at = datetime.now(tz=UTC)
        return summary

    async def _poll_source(
        self,
        source: FeedSourceConfig,
        scorer: RelevanceScorer,
    ) -> PollResult:
        """Poll a single source and return a :class:`PollResult`.

        Args:
            source: The configured feed source.
            scorer: The :class:`~distillery.feeds.scorer.RelevanceScorer` to use.

        Returns:
            A :class:`PollResult` summarising what happened.
        """
        result = PollResult(
            source_url=source.url,
            source_type=source.source_type,
        )

        # Build adapter
        try:
            adapter = _build_adapter(source)
        except ValueError as exc:
            result.errors.append(f"Failed to build adapter: {exc}")
            logger.warning("FeedPoller: %s", exc)
            return result

        # Fetch items (synchronous I/O — run in a thread)
        try:
            items: list[FeedItem] = await asyncio.to_thread(adapter.fetch)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"Adapter fetch failed: {exc}")
            logger.warning("FeedPoller: fetch failed for %s: %s", source.url, exc)
            return result

        result.items_fetched = len(items)
        logger.debug("FeedPoller: fetched %d items from %s", result.items_fetched, source.url)

        # Track entry IDs stored during this batch so we can exclude them
        # from semantic dedup — prevents same-batch items from blocking
        # each other.
        batch_entry_ids: set[str] = set()

        for item in items:
            text = _item_text(item)
            if not text.strip():
                result.items_below_threshold += 1
                continue

            # Fast dedup: check external_id before expensive semantic search
            if await self._has_external_id(item.item_id):
                result.items_skipped_dedup += 1
                continue

            # Semantic dedup: skip if a near-duplicate already exists
            if await self._is_duplicate(item, text, batch_entry_ids):
                result.items_skipped_dedup += 1
                continue

            # Score
            try:
                score = await scorer.score(text)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Scoring failed for item {item.item_id!r}: {exc}")
                logger.warning(
                    "FeedPoller: scoring failed for item %r from %s: %s",
                    item.item_id,
                    source.url,
                    exc,
                )
                continue
            adjusted_score = score * source.trust_weight

            if adjusted_score < self._threshold:
                result.items_below_threshold += 1
                logger.debug(
                    "FeedPoller: item %r score %.3f below threshold %.3f",
                    item.item_id,
                    adjusted_score,
                    self._threshold,
                )
                continue

            # Store
            try:
                from distillery.models import Entry

                kwargs = _item_to_entry_kwargs(item, adjusted_score)
                entry = Entry(**kwargs)
                await self._store.store(entry)
                batch_entry_ids.add(str(entry.id))
                result.items_stored += 1
                logger.debug(
                    "FeedPoller: stored item %r (score=%.3f)", item.item_id, adjusted_score
                )
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"Failed to store item {item.item_id!r}: {exc}")
                logger.warning(
                    "FeedPoller: failed to store item %r from %s: %s",
                    item.item_id,
                    source.url,
                    exc,
                )

        return result

    async def rescore(self, *, limit: int = 100) -> dict[str, Any]:
        """Re-score existing feed entries against the current store state.

        Uses the same scoring semantics as :meth:`poll` — builds an
        :class:`~distillery.feeds.interests.InterestProfile` for tag-weighted
        boosting and applies ``source.trust_weight`` when available.
        Self-matches (the entry matching itself via ``find_similar``) are
        filtered out so scores reflect relevance to *other* entries only.

        Args:
            limit: Maximum number of feed entries to re-score.

        Returns:
            A summary dict with ``rescored``, ``upgraded``, ``downgraded``,
            and ``errors`` counts.
        """
        # Build interest profile for consistent scoring with poll().
        interest_profile = None
        try:
            from distillery.feeds.interests import InterestExtractor

            extractor = InterestExtractor(
                store=self._store,
            )
            interest_profile = await extractor.extract()
        except Exception:  # noqa: BLE001
            logger.debug("FeedPoller.rescore: interest profile extraction failed")

        scorer = RelevanceScorer(
            store=self._store,
            min_score=0.0,
            interest_profile=interest_profile,
        )
        entries = await self._store.list_entries(
            filters={"entry_type": "feed"},
            limit=limit,
            offset=0,
        )

        # Build a source trust_weight lookup from DB.
        db_sources = await self._store.list_feed_sources()
        trust_weights: dict[str, float] = {s["url"]: s["trust_weight"] for s in db_sources}

        stats: dict[str, int] = {
            "rescored": 0,
            "upgraded": 0,
            "downgraded": 0,
            "archived": 0,
            "errors": 0,
        }

        for entry in entries:
            try:
                # Score against the store, then filter out self-match.
                results = await self._store.find_similar(
                    content=entry.content,
                    threshold=0.0,
                    limit=11,  # fetch one extra to allow self-exclusion
                )
                filtered = [r for r in results if str(r.entry.id) != str(entry.id)]
                new_score = max((r.score for r in filtered), default=0.0)

                # Apply interest-profile boost (consistent with scorer).
                if interest_profile and interest_profile.top_tags and filtered:
                    boost = scorer._compute_interest_boost(filtered)
                    new_score = min(new_score + boost, 1.0)

                # Apply source trust_weight if available.
                source_url = entry.metadata.get("source_url", "")
                trust = trust_weights.get(source_url, 1.0)
                new_score *= trust

                old_score = entry.metadata.get("relevance_score", 0.0)

                updated_metadata = dict(entry.metadata)
                updated_metadata["relevance_score"] = new_score
                updated_metadata["previous_score"] = old_score
                updated_metadata["rescored_at"] = datetime.now(tz=UTC).isoformat()

                await self._store.update(
                    entry_id=str(entry.id),
                    updates={"metadata": updated_metadata},
                )
                stats["rescored"] += 1

                if new_score > old_score:
                    stats["upgraded"] += 1
                elif new_score < old_score:
                    stats["downgraded"] += 1

                # Archive entries that dropped below threshold
                if new_score < self._threshold and old_score >= self._threshold:
                    await self._store.delete(str(entry.id))
                    stats["archived"] += 1

            except Exception:  # noqa: BLE001
                logger.warning("FeedPoller: rescore failed for entry %s", entry.id, exc_info=True)
                stats["errors"] += 1

        return stats

    async def _has_external_id(self, external_id: str) -> bool:
        """Return ``True`` if any stored entry already carries *external_id*.

        Uses ``list_entries`` with a metadata filter rather than a full
        similarity search, making this a cheap pre-check before scoring.

        Args:
            external_id: The feed-item identifier to look for.

        Returns:
            ``True`` if a matching entry exists.
        """
        try:
            results = await self._store.list_entries(
                filters={"metadata.external_id": external_id},
                limit=1,
                offset=0,
            )
            return bool(results)
        except Exception:  # noqa: BLE001
            logger.debug(
                "FeedPoller: external_id lookup failed for %r — falling through",
                external_id,
            )
            return False

    async def _is_duplicate(
        self,
        item: FeedItem,
        text: str,
        batch_entry_ids: set[str] | None = None,
    ) -> bool:
        """Return ``True`` if *item* is a near-duplicate of an existing entry.

        Checks whether any stored entry has ``metadata.external_id``
        equal to ``item.item_id`` or has near-exact text similarity
        (threshold 0.95).  Entries whose IDs appear in *batch_entry_ids*
        are ignored so that items stored earlier in the same poll batch
        do not block later items.

        Args:
            item: The feed item to check.
            text: Pre-computed text representation of *item*.
            batch_entry_ids: Entry IDs stored during the current poll
                batch — matches against these are not treated as
                duplicates.

        Returns:
            ``True`` if the item should be skipped as a duplicate.
        """
        _batch_ids = batch_entry_ids or set()

        try:
            results = await self._store.find_similar(
                content=text,
                threshold=_DEDUP_THRESHOLD,
                limit=5,
            )
        except Exception:  # noqa: BLE001
            logger.debug(
                "FeedPoller: dedup check failed for item %r — treating as non-duplicate",
                item.item_id,
            )
            return False

        if results:
            for result in results:
                # Skip matches from the current poll batch
                if str(result.entry.id) in _batch_ids:
                    continue
                # Exact external_id match — definite duplicate
                ext_id = result.entry.metadata.get("external_id")
                if ext_id == item.item_id:
                    return True
                # High similarity to a pre-existing entry — treat as duplicate
                return True

        return False