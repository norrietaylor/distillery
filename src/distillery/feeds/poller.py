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
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from distillery.feeds.scorer import RelevanceScorer
from distillery.feeds.truncation import truncate_content

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

# Source types whose ``item_id`` is authoritative (globally unique and stable).
# When an item from one of these source types passes the fast ``_has_external_id``
# check (not found), the expensive semantic dedup pass via ``_is_duplicate`` is
# skipped entirely — the external_id guarantee is sufficient.
_AUTHORITATIVE_EXTERNAL_ID_TYPES: frozenset[str] = frozenset({"github", "rss"})


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


def _item_text(item: FeedItem, *, apply_truncation: bool = True) -> str:
    """Build a single text string from a feed item for embedding.

    Concatenates title and content with a newline separator, falling back to
    whichever field is available.  When *apply_truncation* is ``True``
    (the default) the result is pre-truncated to stay within the Jina
    embedding model's token limit.

    Args:
        item: The feed item to convert.
        apply_truncation: Whether to truncate the result to
            :data:`~distillery.feeds.truncation.MAX_CONTENT_CHARS`.

    Returns:
        A non-empty text string, or an empty string if both fields are absent.
    """
    parts: list[str] = []
    if item.title:
        parts.append(item.title)
    if item.content:
        parts.append(item.content)
    text = "\n".join(parts)
    if apply_truncation:
        text = truncate_content(text)
    return text


def _build_adapter(source: FeedSourceConfig) -> Any:
    """Instantiate the correct adapter for *source*.

    For GitHub sources the ``GITHUB_TOKEN`` environment variable is read and
    forwarded to :class:`~distillery.feeds.github.GitHubAdapter` so that
    private-repository polling works without storing credentials anywhere.

    Args:
        source: The configured feed source.

    Returns:
        An adapter instance with a ``.fetch()`` method.

    Raises:
        ValueError: If ``source.source_type`` is not a supported adapter type.
    """
    if source.source_type == "github":
        import os

        from distillery.feeds.github import GitHubAdapter

        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            logger.debug(
                "_build_adapter: GitHub adapter using authenticated token for %s", source.url
            )
        else:
            logger.debug(
                "_build_adapter: GitHub adapter using unauthenticated mode for %s", source.url
            )
        return GitHubAdapter(url=source.url, token=token or None)
    elif source.source_type == "rss":
        from distillery.feeds.rss import RSSAdapter

        return RSSAdapter(url=source.url)
    else:
        raise ValueError(
            f"Unsupported source_type {source.source_type!r} for url {source.url!r}. "
            "Supported types: 'github', 'rss'."
        )


def _derive_source_tags(item: FeedItem, source_type: str) -> list[str]:
    """Derive hierarchical source tags from feed item metadata.

    Tag derivation rules:

    - All feeds: ``source/{source_type}`` (e.g. ``source/rss``, ``source/github``).
    - Reddit: parse subreddit from URL → ``source/reddit/{subreddit}``.
    - GitHub: parse owner/repo from URL → ``source/github/{owner}/{repo}``.
    - Other RSS: parse domain from URL → ``source/{domain}`` (lowercase,
      ``www.`` prefix stripped).

    Each candidate tag is validated via :func:`~distillery.models.validate_tag`.
    Invalid tags are silently dropped with a DEBUG-level log message.

    Args:
        item: The normalised feed item.
        source_type: The adapter type string (e.g. ``'rss'``, ``'github'``).

    Returns:
        A list of validated tag strings; never raises.
    """
    from distillery.models import validate_tag

    candidates: list[str] = []

    # All feeds: source/{source_type}
    candidates.append(f"source/{source_type}")

    url = item.source_url or ""

    if source_type == "github":
        # GitHub: source/github/{owner}/{repo}
        try:
            from distillery.feeds.github import _parse_github_url

            owner, repo = _parse_github_url(url)
            candidates.append(f"source/github/{owner}/{repo}")
        except Exception:
            logger.debug("_derive_source_tags: could not parse GitHub URL %r", url)
    elif source_type == "rss":
        # Reddit: source/reddit/{subreddit}
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host == "reddit.com" or host.endswith(".reddit.com"):
            # URL pattern: https://www.reddit.com/r/{subreddit}/...
            path_parts = [p for p in parsed.path.split("/") if p]
            if len(path_parts) >= 2 and path_parts[0] == "r":
                subreddit = path_parts[1].lower()
                candidates.append(f"source/reddit/{subreddit}")
        else:
            # Generic RSS: source/{domain} (strip www. prefix, replace dots with hyphens
            # so the resulting tag segment is valid per validate_tag())
            if host.startswith("www."):
                host = host[4:]
            # Replace dots with hyphens to produce a valid tag segment
            domain_slug = host.replace(".", "-")
            if domain_slug:
                candidates.append(f"source/{domain_slug}")

    # Validate all candidates; drop invalid ones silently
    tags: list[str] = []
    for tag in candidates:
        try:
            validate_tag(tag)
            tags.append(tag)
        except ValueError:
            logger.debug("_derive_source_tags: dropping invalid tag %r", tag)

    return tags


def build_keyword_map(vocabulary: dict[str, int]) -> dict[str, str]:
    """Build a keyword-to-tag-path map from a tag vocabulary.

    For each tag in *vocabulary*:

    - Extracts the leaf segment (the last ``/``-separated part).
    - Maps the leaf directly to the full tag path.
    - Splits hyphenated leaves into individual words and maps each word longer
      than 3 characters to the full tag path.

    When two tags produce the same keyword, the one with the higher occurrence
    count (or alphabetically first on tie) wins.

    Args:
        vocabulary: Mapping of full tag path → occurrence count, as returned
            by :meth:`~distillery.store.protocol.DistilleryStore.get_tag_vocabulary`.

    Returns:
        A dict mapping lowercase keyword strings to full tag paths.

    Example::

        vocab = {"domain/authentication": 5, "supply-chain-security": 2}
        kw_map = build_keyword_map(vocab)
        # kw_map["authentication"]    == "domain/authentication"
        # kw_map["supply"]            == "supply-chain-security"
        # kw_map["chain"]             == "supply-chain-security"
        # kw_map["security"]          == "supply-chain-security"
    """
    # keyword -> (full_tag_path, occurrence_count)
    best: dict[str, tuple[str, int]] = {}

    for tag, count in vocabulary.items():
        # Skip Tier-1 source tags — they're applied via _derive_source_tags
        if tag.startswith("source/"):
            continue
        leaf = tag.rsplit("/", 1)[-1]
        keywords: list[str] = [leaf]
        # Split hyphenated leaf and keep words longer than 3 chars
        for word in leaf.split("-"):
            if len(word) > 3:
                keywords.append(word)

        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower not in best:
                best[kw_lower] = (tag, count)
            else:
                existing_tag, existing_count = best[kw_lower]
                # Higher count wins; alphabetical ordering breaks ties
                if count > existing_count or (count == existing_count and tag < existing_tag):
                    best[kw_lower] = (tag, count)

    return {kw: tag for kw, (tag, _) in best.items()}


def match_topic_tags(text: str, keyword_map: dict[str, str]) -> list[str]:
    """Match feed item text against a keyword map to derive topic tags.

    Tokenises *text* into lowercase words (splitting on any non-alphanumeric
    character) and looks each token up in *keyword_map*.  Duplicate tag paths
    are collapsed so the returned list contains at most one entry per tag.

    Args:
        text: The combined title + content text of a feed item.
        keyword_map: A mapping of lowercase keyword → full tag path, as
            produced by :func:`build_keyword_map`.

    Returns:
        A deduplicated list of matched full tag paths; empty if nothing matched.
    """
    seen: set[str] = set()
    matched: list[str] = []
    for token in re.split(r"[^a-z0-9]+", text.lower()):
        if not token:
            continue
        full_tag = keyword_map.get(token)
        if full_tag is not None and full_tag not in seen:
            seen.add(full_tag)
            matched.append(full_tag)

    return matched


def derive_all_tags(
    item: FeedItem,
    source_type: str,
    keyword_map: dict[str, str],
) -> list[str]:
    """Derive the complete tag list for a feed item.

    Combines Tier-1 source tags (from :func:`_derive_source_tags`) with
    Tier-2 topic tags (from :func:`match_topic_tags`) and deduplicates.

    Args:
        item: The normalised feed item.
        source_type: The adapter type string (e.g. ``'rss'``, ``'github'``).
        keyword_map: A mapping of lowercase keyword → full tag path as
            produced by :func:`build_keyword_map`.

    Returns:
        A deduplicated list of validated tag paths; Tier-1 tags appear first.
    """
    source_tags = _derive_source_tags(item, source_type)

    text = _item_text(item)
    topic_tags = match_topic_tags(text, keyword_map)

    # Deduplicate preserving order (source tags first)
    seen: set[str] = set(source_tags)
    combined = list(source_tags)
    for tag in topic_tags:
        if tag not in seen:
            seen.add(tag)
            combined.append(tag)

    return combined


def _item_to_entry_kwargs(
    item: FeedItem,
    relevance_score: float,
    keyword_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Convert a :class:`~distillery.feeds.models.FeedItem` to Entry constructor kwargs.

    When *keyword_map* is provided, topic tags (Tier 2) are derived in addition
    to source tags (Tier 1) via :func:`derive_all_tags`.  When absent, only
    source tags are derived.

    Args:
        item: The normalised feed item.
        relevance_score: The computed cosine similarity score.
        keyword_map: Optional keyword-to-tag-path mapping produced by
            :func:`build_keyword_map` for the current poll cycle.  When
            ``None`` only Tier-1 source tags are applied.

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

    if keyword_map is not None:
        tags = derive_all_tags(item, item.source_type, keyword_map)
    else:
        tags = _derive_source_tags(item, item.source_type)

    return {
        "content": text or item.source_url,
        "entry_type": EntryType.FEED,
        "source": EntrySource.IMPORT,
        "author": "distillery-poller",
        "tags": tags,
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

        # Build keyword map once per poll cycle for Tier-2 topic tag matching.
        keyword_map: dict[str, str] = {}
        try:
            vocabulary = await self._store.get_tag_vocabulary()
            keyword_map = build_keyword_map(vocabulary)
            logger.debug(
                "FeedPoller: built keyword map with %d keywords from %d tags",
                len(keyword_map),
                len(vocabulary),
            )
        except Exception:  # noqa: BLE001
            logger.debug("FeedPoller: keyword map build failed — topic tagging disabled")

        # Poll all sources concurrently — each _poll_source is independent.
        results = await asyncio.gather(
            *(self._poll_source(source, scorer, keyword_map=keyword_map) for source in sources),
            return_exceptions=True,
        )

        for idx, result in enumerate(results):
            if isinstance(result, BaseException):
                # Unexpected exception from _poll_source — record as errored.
                err_result = PollResult(
                    source_url=sources[idx].url,
                    source_type=sources[idx].source_type,
                    errors=[f"Unexpected error: {result}"],
                )
                summary.results.append(err_result)
                summary.sources_polled += 1
                summary.sources_errored += 1
                logger.warning(
                    "FeedPoller: unexpected error polling %s: %s",
                    sources[idx].url,
                    result,
                )
            else:
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
        *,
        keyword_map: dict[str, str] | None = None,
    ) -> PollResult:
        """Poll a single source and return a :class:`PollResult`.

        Args:
            source: The configured feed source.
            scorer: The :class:`~distillery.feeds.scorer.RelevanceScorer` to use.
            keyword_map: Optional keyword-to-tag-path mapping for Tier-2 topic
                tag matching, built once per poll cycle by the caller.

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

            # Semantic dedup: skip if a near-duplicate already exists.
            # For source types with authoritative external IDs (e.g. github,
            # rss), the _has_external_id check above is sufficient — skip the
            # expensive embedding-based similarity search entirely.
            if (
                source.source_type not in _AUTHORITATIVE_EXTERNAL_ID_TYPES
                and await self._is_duplicate(item, text, batch_entry_ids)
            ):
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

                kwargs = _item_to_entry_kwargs(item, adjusted_score, keyword_map)
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
