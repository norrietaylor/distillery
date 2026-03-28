"""Tests for the InterestExtractor, InterestProfile, and MCP tools.

Covers:
  - InterestExtractor.extract() with various entry combinations
  - Recency weighting logic
  - Tag normalisation
  - Bookmark domain extraction
  - Repo extraction from github/feed entries
  - Expertise area extraction from person entries
  - _handle_interests tool handler
  - _handle_suggest_sources tool handler
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from distillery.config import DistilleryConfig, FeedsConfig, FeedSourceConfig
from distillery.feeds.interests import InterestExtractor, InterestProfile
from distillery.models import Entry, EntrySource, EntryType

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    entry_type: str = "inbox",
    tags: list[str] | None = None,
    metadata: dict | None = None,
    content: str = "Some content",
    created_at: datetime | None = None,
) -> Entry:
    return Entry(
        content=content,
        entry_type=EntryType(entry_type),
        source=EntrySource.MANUAL,
        author="tester",
        tags=tags or [],
        metadata=metadata or {},
        created_at=created_at or datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )


def _make_feeds_config(sources: list[FeedSourceConfig] | None = None) -> FeedsConfig:
    return FeedsConfig(sources=sources or [])


def _make_store(entries: list[Entry]) -> AsyncMock:
    """Return a mock DistilleryStore that yields *entries* from list_entries."""
    store = AsyncMock()

    async def _list_entries(
        filters: dict | None, limit: int, offset: int
    ) -> list[Entry]:
        batch = entries[offset : offset + limit]
        return batch

    store.list_entries.side_effect = _list_entries
    return store


# ---------------------------------------------------------------------------
# InterestProfile
# ---------------------------------------------------------------------------


class TestInterestProfile:
    def test_defaults(self) -> None:
        profile = InterestProfile()
        assert profile.top_tags == []
        assert profile.bookmark_domains == []
        assert profile.tracked_repos == []
        assert profile.expertise_areas == []
        assert profile.watched_sources == []
        assert profile.suggestion_context == ""  # populated by extract(), empty on direct construction

    def test_entry_count_default_zero(self) -> None:
        profile = InterestProfile()
        assert profile.entry_count == 0

    def test_generated_at_is_utc(self) -> None:
        profile = InterestProfile()
        assert profile.generated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# InterestExtractor._recency_weight
# ---------------------------------------------------------------------------


class TestRecencyWeight:
    def _extractor(self, recency_days: int = 90) -> InterestExtractor:
        return InterestExtractor(
            store=AsyncMock(),
            feeds_config=_make_feeds_config(),
            recency_days=recency_days,
        )

    def test_recent_entry_gets_full_weight(self) -> None:
        ext = self._extractor()
        now = datetime.now(tz=UTC)
        created = now - timedelta(days=5)
        assert ext._recency_weight(created, now) == pytest.approx(1.0)

    def test_old_entry_gets_min_weight(self) -> None:
        ext = self._extractor(recency_days=90)
        now = datetime.now(tz=UTC)
        created = now - timedelta(days=95)
        assert ext._recency_weight(created, now) == pytest.approx(0.1)

    def test_middle_entry_gets_intermediate_weight(self) -> None:
        ext = self._extractor(recency_days=90)
        now = datetime.now(tz=UTC)
        # Midpoint of the decay window (14 + 90) / 2 ≈ 52 days
        created = now - timedelta(days=52)
        w = ext._recency_weight(created, now)
        assert 0.1 < w < 1.0

    def test_exactly_at_recency_boundary(self) -> None:
        ext = self._extractor(recency_days=90)
        now = datetime.now(tz=UTC)
        created = now - timedelta(days=90)
        assert ext._recency_weight(created, now) == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# InterestExtractor._extract_domain
# ---------------------------------------------------------------------------


class TestExtractDomain:
    def _ext(self) -> InterestExtractor:
        return InterestExtractor(store=AsyncMock(), feeds_config=_make_feeds_config())

    def test_url_from_metadata(self) -> None:
        domain = self._ext()._extract_domain({"url": "https://example.com/path"}, "")
        assert domain == "example.com"

    def test_www_prefix_stripped(self) -> None:
        domain = self._ext()._extract_domain({"url": "https://www.example.com/"}, "")
        assert domain == "example.com"

    def test_url_from_content_fallback(self) -> None:
        domain = self._ext()._extract_domain({}, "Check out https://news.ycombinator.com/item?id=1")
        assert domain == "news.ycombinator.com"

    def test_no_url_returns_none(self) -> None:
        domain = self._ext()._extract_domain({}, "No URL here")
        assert domain is None

    def test_invalid_metadata_type(self) -> None:
        # metadata is not a dict — should not crash
        domain = self._ext()._extract_domain(None, "https://example.com")  # type: ignore[arg-type]
        assert domain == "example.com"


# ---------------------------------------------------------------------------
# InterestExtractor._extract_repos
# ---------------------------------------------------------------------------


class TestExtractRepos:
    def _ext(self) -> InterestExtractor:
        return InterestExtractor(store=AsyncMock(), feeds_config=_make_feeds_config())

    def _counter(self) -> defaultdict[str, int]:
        from collections import Counter

        return Counter()  # type: ignore[return-value]

    def test_github_entry_extracts_repo(self) -> None:
        from collections import Counter

        counts: Counter[str] = Counter()
        self._ext()._extract_repos("github", {"repo": "owner/repo"}, counts)
        assert counts["owner/repo"] == 1

    def test_feed_entry_slug_source_url(self) -> None:
        from collections import Counter

        counts: Counter[str] = Counter()
        self._ext()._extract_repos("feed", {"source_url": "myorg/myrepo"}, counts)
        assert counts["myorg/myrepo"] == 1

    def test_feed_entry_github_url(self) -> None:
        from collections import Counter

        counts: Counter[str] = Counter()
        self._ext()._extract_repos(
            "feed",
            {"source_url": "https://github.com/octocat/hello-world"},
            counts,
        )
        assert counts["octocat/hello-world"] == 1

    def test_non_github_entry_does_nothing(self) -> None:
        from collections import Counter

        counts: Counter[str] = Counter()
        self._ext()._extract_repos("session", {"repo": "owner/repo"}, counts)
        assert len(counts) == 0


# ---------------------------------------------------------------------------
# InterestExtractor._normalise_top_n
# ---------------------------------------------------------------------------


class TestNormaliseTopN:
    def test_empty_scores_returns_empty(self) -> None:
        scores: defaultdict[str, float] = defaultdict(float)
        assert InterestExtractor._normalise_top_n(scores, 10) == []

    def test_single_tag_gets_weight_one(self) -> None:
        scores: defaultdict[str, float] = defaultdict(float)
        scores["python"] = 5.0
        result = InterestExtractor._normalise_top_n(scores, 10)
        assert result == [("python", 1.0)]

    def test_relative_weights(self) -> None:
        scores: defaultdict[str, float] = defaultdict(float)
        scores["a"] = 10.0
        scores["b"] = 5.0
        scores["c"] = 2.5
        result = InterestExtractor._normalise_top_n(scores, 10)
        assert result[0] == ("a", 1.0)
        assert result[1][0] == "b"
        assert result[1][1] == pytest.approx(0.5)
        assert result[2][1] == pytest.approx(0.25)

    def test_top_n_limit(self) -> None:
        scores: defaultdict[str, float] = defaultdict(float)
        for i in range(30):
            scores[f"tag{i}"] = float(30 - i)
        result = InterestExtractor._normalise_top_n(scores, 5)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# InterestExtractor.extract — integration
# ---------------------------------------------------------------------------


class TestInterestExtractorExtract:
    async def test_empty_store_returns_empty_profile(self) -> None:
        store = _make_store([])
        ext = InterestExtractor(store=store, feeds_config=_make_feeds_config())
        profile = await ext.extract()
        assert profile.top_tags == []
        assert profile.entry_count == 0

    async def test_tags_accumulated(self) -> None:
        entries = [
            _make_entry(tags=["python", "testing"]),
            _make_entry(tags=["python", "fastapi"]),
        ]
        store = _make_store(entries)
        ext = InterestExtractor(store=store, feeds_config=_make_feeds_config())
        profile = await ext.extract()
        tag_names = [t for t, _ in profile.top_tags]
        assert "python" in tag_names
        assert "testing" in tag_names

    async def test_python_tag_has_highest_weight(self) -> None:
        entries = [
            _make_entry(tags=["python"]),
            _make_entry(tags=["python"]),
            _make_entry(tags=["rust"]),
        ]
        store = _make_store(entries)
        ext = InterestExtractor(store=store, feeds_config=_make_feeds_config())
        profile = await ext.extract()
        assert profile.top_tags[0] == ("python", 1.0)

    async def test_bookmark_domain_extracted(self) -> None:
        entries = [
            _make_entry(
                entry_type="bookmark",
                metadata={"url": "https://github.com/blog/post"},
            )
        ]
        store = _make_store(entries)
        ext = InterestExtractor(store=store, feeds_config=_make_feeds_config())
        profile = await ext.extract()
        assert "github.com" in profile.bookmark_domains

    async def test_github_entry_adds_repo(self) -> None:
        entries = [
            _make_entry(
                entry_type="github",
                metadata={"repo": "fastapi/fastapi", "ref_type": "pr", "ref_number": 1},
            )
        ]
        store = _make_store(entries)
        ext = InterestExtractor(store=store, feeds_config=_make_feeds_config())
        profile = await ext.extract()
        assert "fastapi/fastapi" in profile.tracked_repos

    async def test_person_entry_adds_expertise(self) -> None:
        entries = [
            _make_entry(
                entry_type="person",
                metadata={"expertise": ["Python", "Distributed Systems"]},
            )
        ]
        store = _make_store(entries)
        ext = InterestExtractor(store=store, feeds_config=_make_feeds_config())
        profile = await ext.extract()
        assert "python" in profile.expertise_areas
        assert "distributed systems" in profile.expertise_areas

    async def test_watched_sources_populated_from_config(self) -> None:
        source = FeedSourceConfig(
            url="https://example.com/rss",
            source_type="rss",
        )
        feeds = _make_feeds_config(sources=[source])
        store = _make_store([])
        ext = InterestExtractor(store=store, feeds_config=feeds)
        profile = await ext.extract()
        assert "https://example.com/rss" in profile.watched_sources

    async def test_entry_count_reflects_analysed_entries(self) -> None:
        entries = [_make_entry() for _ in range(5)]
        store = _make_store(entries)
        ext = InterestExtractor(store=store, feeds_config=_make_feeds_config())
        profile = await ext.extract()
        assert profile.entry_count == 5

    async def test_very_old_entries_excluded(self) -> None:
        # Entry older than recency_days * 3 should be skipped
        very_old = datetime.now(tz=UTC) - timedelta(days=400)
        entries = [
            _make_entry(tags=["ancient-topic"], created_at=very_old),
            _make_entry(tags=["current-topic"]),
        ]
        store = _make_store(entries)
        ext = InterestExtractor(
            store=store, feeds_config=_make_feeds_config(), recency_days=90
        )
        profile = await ext.extract()
        tag_names = [t for t, _ in profile.top_tags]
        assert "current-topic" in tag_names
        assert "ancient-topic" not in tag_names

    async def test_suggestion_context_contains_tags(self) -> None:
        entries = [_make_entry(tags=["python", "async"])]
        store = _make_store(entries)
        ext = InterestExtractor(store=store, feeds_config=_make_feeds_config())
        profile = await ext.extract()
        assert "python" in profile.suggestion_context

    async def test_suggestion_context_mentions_exclusion(self) -> None:
        source = FeedSourceConfig(url="https://myfeed.com/rss", source_type="rss")
        feeds = _make_feeds_config(sources=[source])
        store = _make_store([_make_entry(tags=["python"])])
        ext = InterestExtractor(store=store, feeds_config=feeds)
        profile = await ext.extract()
        assert "myfeed.com" in profile.suggestion_context


# ---------------------------------------------------------------------------
# _handle_interests
# ---------------------------------------------------------------------------


class TestHandleInterests:
    async def test_returns_profile_fields(self) -> None:
        from distillery.mcp.server import _handle_interests

        store = _make_store([_make_entry(tags=["python", "testing"])])
        cfg = DistilleryConfig()
        result = await _handle_interests(store=store, config=cfg, arguments={})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert "top_tags" in data
        assert "bookmark_domains" in data
        assert "tracked_repos" in data
        assert "expertise_areas" in data
        assert "watched_sources" in data
        assert "suggestion_context" in data
        assert "entry_count" in data
        assert "generated_at" in data

    async def test_invalid_recency_days_returns_error(self) -> None:
        from distillery.mcp.server import _handle_interests

        cfg = DistilleryConfig()
        result = await _handle_interests(
            store=AsyncMock(), config=cfg, arguments={"recency_days": 0}
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True

    async def test_invalid_top_n_returns_error(self) -> None:
        from distillery.mcp.server import _handle_interests

        cfg = DistilleryConfig()
        result = await _handle_interests(
            store=AsyncMock(), config=cfg, arguments={"top_n": -5}
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True

    async def test_top_tags_are_serialised_as_pairs(self) -> None:
        from distillery.mcp.server import _handle_interests

        store = _make_store([_make_entry(tags=["python"])])
        cfg = DistilleryConfig()
        result = await _handle_interests(store=store, config=cfg, arguments={})
        data = json.loads(result[0].text)
        for pair in data["top_tags"]:
            assert len(pair) == 2
            assert isinstance(pair[0], str)
            assert isinstance(pair[1], float)

    async def test_custom_recency_days(self) -> None:
        from distillery.mcp.server import _handle_interests

        store = _make_store([_make_entry(tags=["python"])])
        cfg = DistilleryConfig()
        result = await _handle_interests(
            store=store, config=cfg, arguments={"recency_days": 30}
        )
        data = json.loads(result[0].text)
        assert "error" not in data or not data.get("error")


# ---------------------------------------------------------------------------
# _handle_suggest_sources
# ---------------------------------------------------------------------------


class TestHandleSuggestSources:
    async def test_returns_suggestions_field(self) -> None:
        from distillery.mcp.server import _handle_suggest_sources

        store = _make_store(
            [
                _make_entry(
                    entry_type="github",
                    metadata={"repo": "tiangolo/fastapi", "ref_type": "pr", "ref_number": 1},
                )
            ]
        )
        cfg = DistilleryConfig()
        result = await _handle_suggest_sources(store=store, config=cfg, arguments={})
        data = json.loads(result[0].text)
        assert "suggestions" in data
        assert "suggestion_context" in data
        assert "watched_sources" in data
        assert "entry_count" in data

    async def test_suggestions_have_expected_fields(self) -> None:
        from distillery.mcp.server import _handle_suggest_sources

        store = _make_store(
            [
                _make_entry(
                    entry_type="github",
                    metadata={"repo": "tiangolo/fastapi", "ref_type": "pr", "ref_number": 1},
                )
            ]
        )
        cfg = DistilleryConfig()
        result = await _handle_suggest_sources(store=store, config=cfg, arguments={})
        data = json.loads(result[0].text)
        for suggestion in data["suggestions"]:
            assert "url" in suggestion
            assert "source_type" in suggestion
            assert "label" in suggestion
            assert "rationale" in suggestion

    async def test_invalid_max_suggestions_returns_error(self) -> None:
        from distillery.mcp.server import _handle_suggest_sources

        cfg = DistilleryConfig()
        result = await _handle_suggest_sources(
            store=AsyncMock(), config=cfg, arguments={"max_suggestions": 0}
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True

    async def test_invalid_source_type_filter_returns_error(self) -> None:
        from distillery.mcp.server import _handle_suggest_sources

        cfg = DistilleryConfig()
        result = await _handle_suggest_sources(
            store=AsyncMock(),
            config=cfg,
            arguments={"source_types": ["slack"]},
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True
        assert data["code"] == "INVALID_SOURCE_TYPE"

    async def test_watched_sources_excluded_from_suggestions(self) -> None:
        from distillery.mcp.server import _handle_suggest_sources

        store = _make_store(
            [
                _make_entry(
                    entry_type="github",
                    metadata={"repo": "tiangolo/fastapi", "ref_type": "pr", "ref_number": 1},
                )
            ]
        )
        cfg = DistilleryConfig()
        cfg.feeds.sources = [
            FeedSourceConfig(url="tiangolo/fastapi", source_type="github")
        ]
        result = await _handle_suggest_sources(store=store, config=cfg, arguments={})
        data = json.loads(result[0].text)
        suggestion_urls = [s["url"] for s in data["suggestions"]]
        assert "tiangolo/fastapi" not in suggestion_urls

    async def test_github_filter_only_returns_github_suggestions(self) -> None:
        from distillery.mcp.server import _handle_suggest_sources

        store = _make_store(
            [
                _make_entry(
                    entry_type="github",
                    metadata={"repo": "owner/repo", "ref_type": "issue", "ref_number": 1},
                ),
                _make_entry(
                    entry_type="bookmark",
                    metadata={"url": "https://blog.example.com/post"},
                ),
            ]
        )
        cfg = DistilleryConfig()
        result = await _handle_suggest_sources(
            store=store, config=cfg, arguments={"source_types": ["github"]}
        )
        data = json.loads(result[0].text)
        for suggestion in data["suggestions"]:
            assert suggestion["source_type"] == "github"

    async def test_max_suggestions_limits_results(self) -> None:
        from distillery.mcp.server import _handle_suggest_sources

        # Create many github entries to generate many potential suggestions
        store = _make_store(
            [
                _make_entry(
                    entry_type="github",
                    metadata={"repo": f"org/repo{i}", "ref_type": "pr", "ref_number": i},
                )
                for i in range(20)
            ]
        )
        cfg = DistilleryConfig()
        result = await _handle_suggest_sources(
            store=store, config=cfg, arguments={"max_suggestions": 3}
        )
        data = json.loads(result[0].text)
        assert len(data["suggestions"]) <= 3
