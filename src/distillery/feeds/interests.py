"""Interest extractor for Distillery ambient radar.

Mines the existing knowledge base to build an :class:`InterestProfile` that
captures the user's areas of focus.  The profile is used by the
``distillery_interests`` MCP tool and feeds into the
``distillery_suggest_sources`` recommendation tool.

The extractor does *not* make any external API calls.  All signals are derived
from entries already stored in the Distillery knowledge base.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from distillery.config import FeedsConfig
    from distillery.store.protocol import DistilleryStore

# ---------------------------------------------------------------------------
# InterestProfile
# ---------------------------------------------------------------------------

_DEFAULT_TOP_N = 20
_DEFAULT_MIN_WEIGHT = 0.1
_DEFAULT_RECENCY_DAYS = 90
_FULL_WEIGHT_DAYS = 14  # entries within this window get full weight (1.0)


@dataclass
class InterestProfile:
    """A snapshot of the user's knowledge interests extracted from the store.

    Attributes:
        top_tags: Ordered list of ``(tag, weight)`` pairs, descending by weight.
            Weights are recency-weighted frequency scores normalised to
            ``[0.0, 1.0]`` relative to the highest-scoring tag.
        bookmark_domains: Unique domains extracted from bookmark entry URLs,
            ordered by frequency descending.
        tracked_repos: GitHub repository identifiers (``owner/repo``) extracted
            from ``github`` and ``feed`` metadata, ordered by frequency.
        expertise_areas: Free-text topics inferred from ``person`` entry
            ``expertise`` lists and ``session`` / ``reference`` entry tags,
            ordered by frequency.
        watched_sources: URLs of sources currently in the feeds.sources
            registry.  These are excluded from new source suggestions.
        suggestion_context: A ready-to-use prose paragraph describing the
            user's interests, suitable for inclusion in an LLM prompt that
            recommends new sources to follow.
        generated_at: UTC timestamp when the profile was computed.
        entry_count: Total number of entries that were analysed.
    """

    top_tags: list[tuple[str, float]] = field(default_factory=list)
    bookmark_domains: list[str] = field(default_factory=list)
    tracked_repos: list[str] = field(default_factory=list)
    expertise_areas: list[str] = field(default_factory=list)
    watched_sources: list[str] = field(default_factory=list)
    suggestion_context: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    entry_count: int = 0


# ---------------------------------------------------------------------------
# InterestExtractor
# ---------------------------------------------------------------------------


class InterestExtractor:
    """Mine the knowledge base for interest signals.

    Parameters
    ----------
    store:
        An initialised :class:`~distillery.store.protocol.DistilleryStore`
        instance to query.
    feeds_config:
        The :class:`~distillery.config.FeedsConfig` section from
        :class:`~distillery.config.DistilleryConfig`, used to populate the
        ``watched_sources`` exclusion list.
    recency_days:
        Number of days back from *now* to consider for full recency weighting.
        Entries older than this receive a linearly reduced weight down to
        ``min_weight``.  Default ``90``.
    top_n:
        Maximum number of tags to include in :attr:`InterestProfile.top_tags`.
        Default ``20``.
    min_weight:
        Minimum recency weight applied to the oldest entries.  Default ``0.1``.
    page_size:
        Number of entries fetched per ``list_entries`` page.  Default ``200``.
    max_entries:
        Hard cap on total entries analysed to keep latency bounded.
        Default ``2000``.

    Example::

        from distillery.feeds.interests import InterestExtractor

        extractor = InterestExtractor(store=my_store, feeds_config=config.feeds)
        profile = await extractor.extract()
    """

    def __init__(
        self,
        store: DistilleryStore,
        feeds_config: FeedsConfig,
        *,
        recency_days: int = _DEFAULT_RECENCY_DAYS,
        top_n: int = _DEFAULT_TOP_N,
        min_weight: float = _DEFAULT_MIN_WEIGHT,
        page_size: int = 200,
        max_entries: int = 2000,
    ) -> None:
        self._store = store
        self._feeds_config = feeds_config
        self._recency_days = recency_days
        self._top_n = top_n
        self._min_weight = min_weight
        self._page_size = page_size
        self._max_entries = max_entries

    async def extract(self) -> InterestProfile:
        """Mine the store and return a fully populated :class:`InterestProfile`.

        The extraction pipeline:

        1. Iterate over all active entries (paginated ``list_entries``).
        2. For each entry compute a recency weight based on ``created_at``.
        3. Accumulate weighted tag counts, bookmark domains, tracked repos,
           and expertise areas.
        4. Normalise tag weights and take the top-*N*.
        5. Populate ``watched_sources`` from the feeds config.
        6. Build the ``suggestion_context`` prose paragraph.

        Returns:
            A populated :class:`InterestProfile`.
        """
        now = datetime.now(tz=UTC)
        cutoff_hard = now - timedelta(days=self._recency_days * 3)

        tag_scores: defaultdict[str, float] = defaultdict(float)
        domain_counts: Counter[str] = Counter()
        repo_counts: Counter[str] = Counter()
        expertise_counts: Counter[str] = Counter()
        total = 0

        offset = 0
        while total < self._max_entries:
            batch = await self._store.list_entries(
                filters={"status": "active"},
                limit=self._page_size,
                offset=offset,
            )
            if not batch:
                break

            all_past_cutoff = True
            for entry in batch:
                if total >= self._max_entries:
                    break

                # Apply hard age cutoff
                created = entry.created_at
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if created < cutoff_hard:
                    # Skip very old entries to keep computation bounded.
                    continue
                all_past_cutoff = False

                weight = self._recency_weight(created, now)

                # Tag frequencies
                for tag in entry.tags:
                    tag_scores[tag] += weight

                # Bookmark domains
                if entry.entry_type == "bookmark":
                    domain = self._extract_domain(entry.metadata, entry.content)
                    if domain:
                        domain_counts[domain] += 1

                # Tracked repos from github + feed entries
                self._extract_repos(entry.entry_type, entry.metadata, repo_counts)

                # Expertise from person entries
                if entry.entry_type == "person":
                    expertise = entry.metadata.get("expertise", [])
                    if isinstance(expertise, list):
                        for area in expertise:
                            if area and isinstance(area, str):
                                expertise_counts[area.lower().strip()] += 1

                total += 1

            offset += len(batch)
            # If every entry in this batch was older than the hard cutoff,
            # subsequent pages will only be older — stop paginating.
            if all_past_cutoff:
                break
            if len(batch) < self._page_size:
                break

        # Normalise tag scores
        top_tags = self._normalise_top_n(tag_scores, self._top_n)

        # Build top lists (by frequency, deduped, limited)
        bookmark_domains = [d for d, _ in domain_counts.most_common(20)]
        tracked_repos = [r for r, _ in repo_counts.most_common(20)]
        expertise_areas = [e for e, _ in expertise_counts.most_common(20)]

        watched_sources = [s.url for s in self._feeds_config.sources]

        suggestion_context = self._build_suggestion_context(
            top_tags=top_tags,
            bookmark_domains=bookmark_domains,
            tracked_repos=tracked_repos,
            expertise_areas=expertise_areas,
            watched_sources=watched_sources,
        )

        return InterestProfile(
            top_tags=top_tags,
            bookmark_domains=bookmark_domains,
            tracked_repos=tracked_repos,
            expertise_areas=expertise_areas,
            watched_sources=watched_sources,
            suggestion_context=suggestion_context,
            generated_at=now,
            entry_count=total,
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _recency_weight(self, created_at: datetime, now: datetime) -> float:
        """Return a weight in ``[min_weight, 1.0]`` based on entry age.

        Entries created within :attr:`_FULL_WEIGHT_DAYS` of *now* receive
        ``1.0``; older entries decay linearly to :attr:`min_weight` at
        ``recency_days`` days of age.

        Args:
            created_at: Entry creation timestamp (timezone-aware).
            now: The reference instant.

        Returns:
            A weight in ``[min_weight, 1.0]``.
        """
        age_days = (now - created_at).total_seconds() / 86400.0
        if age_days <= _FULL_WEIGHT_DAYS:
            return 1.0
        if age_days >= self._recency_days:
            return self._min_weight
        # Linear decay from 1.0 to min_weight between full_weight_days and recency_days
        span = self._recency_days - _FULL_WEIGHT_DAYS
        elapsed = age_days - _FULL_WEIGHT_DAYS
        decay = elapsed / span  # 0.0 → 1.0
        return 1.0 - decay * (1.0 - self._min_weight)

    def _extract_domain(self, metadata: dict[str, Any], content: str) -> str | None:
        """Extract the domain from a bookmark entry.

        Checks ``metadata['url']`` first, then falls back to the first URL
        found in *content*.

        Args:
            metadata: Entry metadata dict.
            content: Entry content string.

        Returns:
            Lowercase domain (without ``www.`` prefix) or ``None``.
        """
        url: str | None = metadata.get("url") if isinstance(metadata, dict) else None
        if not url:
            # Try to find a URL in the content text
            match = re.search(r"https?://[^\s\)\"']+", content)
            url = match.group(0) if match else None
        if not url:
            return None
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            # Strip www. prefix for normalisation
            if host.startswith("www."):
                host = host[4:]
            return host.lower() or None
        except Exception:  # noqa: BLE001
            return None

    def _extract_repos(
        self,
        entry_type: str,
        metadata: dict[str, Any],
        repo_counts: Counter[str],
    ) -> None:
        """Accumulate repo identifiers from *metadata* into *repo_counts*.

        Handles ``github`` entries (``metadata['repo']``) and ``feed`` entries
        where ``metadata['source_url']`` looks like ``owner/repo`` or a GitHub
        URL.

        Args:
            entry_type: String value of :class:`~distillery.models.EntryType`.
            metadata: Entry metadata dict.
            repo_counts: Counter to update in-place.
        """
        if not isinstance(metadata, dict):
            return
        if entry_type == "github":
            repo = metadata.get("repo")
            if repo and isinstance(repo, str):
                repo_counts[repo.strip()] += 1
        elif entry_type == "feed":
            source_url = metadata.get("source_url", "")
            if isinstance(source_url, str):
                # Match owner/repo slug (no slashes elsewhere)
                if re.match(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$", source_url.strip()):
                    repo_counts[source_url.strip()] += 1
                elif "github.com" in source_url:
                    # Extract owner/repo from https://github.com/owner/repo/...
                    match = re.search(r"github\.com/([a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+)", source_url)
                    if match:
                        repo_counts[match.group(1)] += 1

    @staticmethod
    def _normalise_top_n(
        scores: defaultdict[str, float], top_n: int
    ) -> list[tuple[str, float]]:
        """Return the top-*n* tags as ``(tag, normalised_weight)`` pairs.

        Weights are normalised so that the highest-scoring tag receives
        ``1.0``; all others are scaled proportionally.

        Args:
            scores: Accumulated recency-weighted frequency counts per tag.
            top_n: Maximum number of entries to return.

        Returns:
            List of ``(tag, weight)`` pairs sorted by descending weight,
            truncated to *top_n*.
        """
        if not scores:
            return []
        sorted_items = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top = sorted_items[:top_n]
        max_score = top[0][1] if top else 1.0
        if max_score == 0:
            return [(tag, 0.0) for tag, _ in top]
        return [(tag, round(score / max_score, 4)) for tag, score in top]

    @staticmethod
    def _build_suggestion_context(
        top_tags: list[tuple[str, float]],
        bookmark_domains: list[str],
        tracked_repos: list[str],
        expertise_areas: list[str],
        watched_sources: list[str],
    ) -> str:
        """Build a natural-language paragraph describing the user's interests.

        The paragraph is suitable for inclusion verbatim in an LLM prompt that
        asks for new feed source recommendations.

        Args:
            top_tags: Top tags from the profile.
            bookmark_domains: Top bookmark domains.
            tracked_repos: Top tracked repositories.
            expertise_areas: Top expertise areas.
            watched_sources: Currently watched source URLs.

        Returns:
            A prose string summarising the user's interests.
        """
        parts: list[str] = []

        if top_tags:
            tag_names = [t for t, _ in top_tags[:10]]
            parts.append(
                f"Their most frequent knowledge topics (by tag) are: {', '.join(tag_names)}."
            )

        if expertise_areas:
            parts.append(
                f"Their recorded expertise areas include: {', '.join(expertise_areas[:8])}."
            )

        if tracked_repos:
            parts.append(
                f"They actively track these GitHub repositories: {', '.join(tracked_repos[:8])}."
            )

        if bookmark_domains:
            parts.append(
                f"They frequently bookmark content from: {', '.join(bookmark_domains[:8])}."
            )

        if watched_sources:
            parts.append(
                f"They already follow these sources (do not suggest them again): "
                f"{', '.join(watched_sources)}."
            )

        if not parts:
            return (
                "The knowledge base is currently empty. "
                "Suggest a diverse set of high-quality technical and industry news feeds."
            )

        intro = "Based on the user's Distillery knowledge base: "
        return intro + " ".join(parts)
