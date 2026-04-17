"""Tests for the feeds tool handlers in distillery.mcp.tools.feeds.

Covers the three handlers extracted from server.py:
  - _handle_watch: list, add, remove actions, validation errors, edge cases
  - _handle_poll: successful poll, single source filter, source not found, poll error
  - _handle_interests (suggest_sources=True): successful suggestions, empty store, custom params

All tests are @pytest.mark.unit and use the FakeSourceStore pattern from
test_watch.py so they run without a live database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.feeds.interests import InterestProfile
from distillery.feeds.poller import PollerSummary, PollResult
from distillery.mcp.tools.analytics import _handle_interests
from distillery.mcp.tools.feeds import (
    _handle_poll,
    _handle_watch,
)
from distillery.store.duckdb import _sanitise_last_error

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def parse(result: list) -> dict:  # type: ignore[type-arg]
    """Parse MCP TextContent list into a plain dict."""
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


def make_config() -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
    )


# ---------------------------------------------------------------------------
# Fake store for feed source operations
# ---------------------------------------------------------------------------


class FakeSourceStore:
    """In-memory fake that implements the feed-source methods used by feeds.py."""

    def __init__(self) -> None:
        self._sources: list[dict[str, Any]] = []

    async def list_feed_sources(self) -> list[dict[str, Any]]:
        # Deep-copy so callers mutating the returned dicts do not affect
        # subsequent lookups — mirrors DuckDBStore, which rebuilds the dicts
        # from the underlying rows on every call.
        return [dict(s) for s in self._sources]

    async def add_feed_source(
        self,
        url: str,
        source_type: str,
        label: str = "",
        poll_interval_minutes: int = 60,
        trust_weight: float = 1.0,
    ) -> dict[str, Any]:
        if any(s["url"] == url for s in self._sources):
            raise ValueError(f"Feed source with URL {url!r} already exists.")
        entry: dict[str, Any] = {
            "url": url,
            "source_type": source_type,
            "label": label,
            "poll_interval_minutes": poll_interval_minutes,
            "trust_weight": trust_weight,
            "last_polled_at": None,
            "last_item_count": 0,
            "last_error": None,
            "next_poll_at": None,
        }
        self._sources.append(entry)
        return entry

    async def remove_feed_source(self, url: str) -> bool:
        before = len(self._sources)
        self._sources = [s for s in self._sources if s["url"] != url]
        return len(self._sources) < before

    async def record_poll_status(
        self,
        url: str,
        *,
        polled_at: datetime,
        item_count: int,
        error: str | None,
    ) -> bool:
        from datetime import timedelta

        from distillery.store.duckdb import _sanitise_last_error

        for src in self._sources:
            if src["url"] != url:
                continue
            src["last_polled_at"] = polled_at.isoformat()
            src["last_item_count"] = int(item_count)
            src["last_error"] = _sanitise_last_error(error, 200)
            src["next_poll_at"] = (
                polled_at + timedelta(minutes=src["poll_interval_minutes"])
            ).isoformat()
            return True
        return False


class FailingSourceStore:
    """Store that raises RuntimeError on every operation."""

    async def list_feed_sources(self) -> list[dict[str, Any]]:
        raise RuntimeError("DB connection lost")

    async def add_feed_source(self, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("DB connection lost")

    async def remove_feed_source(self, url: str) -> bool:
        raise RuntimeError("DB connection lost")


# ---------------------------------------------------------------------------
# _handle_watch — list action
# ---------------------------------------------------------------------------


class TestHandleWatchList:
    async def test_list_empty_sources(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(store=store, arguments={"action": "list"})
        data = parse(result)
        assert data["sources"] == []
        assert data["count"] == 0

    async def test_list_returns_added_sources(self) -> None:
        store = FakeSourceStore()
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
            label="Example",
        )
        result = await _handle_watch(store=store, arguments={"action": "list"})
        data = parse(result)
        assert data["count"] == 1
        assert data["sources"][0]["url"] == "https://example.com/rss"

    async def test_list_source_fields(self) -> None:
        store = FakeSourceStore()
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
            label="My Feed",
            poll_interval_minutes=30,
            trust_weight=0.8,
        )
        result = await _handle_watch(store=store, arguments={"action": "list"})
        data = parse(result)
        src = data["sources"][0]
        assert src["source_type"] == "rss"
        assert src["label"] == "My Feed"
        assert src["poll_interval_minutes"] == 30
        assert src["trust_weight"] == pytest.approx(0.8)

    async def test_list_backend_error_returns_watch_error(self) -> None:
        store = FailingSourceStore()
        result = await _handle_watch(store=store, arguments={"action": "list"})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "WATCH_ERROR"

    async def test_list_includes_liveness_fields_for_never_polled_source(self) -> None:
        """Newly added sources expose liveness keys with null/zero defaults."""
        store = FakeSourceStore()
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
            poll_interval_minutes=60,
        )
        result = await _handle_watch(store=store, arguments={"action": "list"})
        data = parse(result)
        src = data["sources"][0]
        # New liveness fields must be present in the payload.
        assert "last_polled_at" in src
        assert "last_item_count" in src
        assert "last_error" in src
        assert "next_poll_at" in src
        # Defaults for an unpolled source.
        assert src["last_polled_at"] is None
        assert src["last_item_count"] == 0
        assert src["last_error"] is None
        assert src["next_poll_at"] is None

    async def test_list_surfaces_recorded_poll_success(self) -> None:
        """After a successful poll the liveness fields reflect the outcome."""
        store = FakeSourceStore()
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
            poll_interval_minutes=30,
        )
        polled_at = datetime(2026, 4, 16, 12, 0, tzinfo=UTC)
        assert await store.record_poll_status(
            "https://example.com/rss",
            polled_at=polled_at,
            item_count=7,
            error=None,
        )

        result = await _handle_watch(store=store, arguments={"action": "list"})
        src = parse(result)["sources"][0]
        assert src["last_polled_at"] == polled_at.isoformat()
        assert src["last_item_count"] == 7
        assert src["last_error"] is None
        # next_poll_at = last_polled_at + poll_interval_minutes
        assert src["next_poll_at"] == "2026-04-16T12:30:00+00:00"

    async def test_list_surfaces_last_error_when_poll_fails(self) -> None:
        """When a poll fails the error string is surfaced on the list payload."""
        store = FakeSourceStore()
        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
        )
        polled_at = datetime(2026, 4, 16, 12, 0, tzinfo=UTC)
        await store.record_poll_status(
            "https://example.com/rss",
            polled_at=polled_at,
            item_count=0,
            error="Connection refused: upstream 502",
        )

        result = await _handle_watch(store=store, arguments={"action": "list"})
        src = parse(result)["sources"][0]
        assert src["last_error"] == "Connection refused: upstream 502"
        assert src["last_item_count"] == 0
        assert src["last_polled_at"] == polled_at.isoformat()
        assert src["next_poll_at"] is not None


# ---------------------------------------------------------------------------
# _handle_watch — add action
# ---------------------------------------------------------------------------


class TestHandleWatchAdd:
    async def test_add_rss_source_success(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://news.ycombinator.com/rss",
                "source_type": "rss",
                "label": "Hacker News",
            },
        )
        data = parse(result)
        assert "error" not in data
        assert data["added"]["url"] == "https://news.ycombinator.com/rss"
        assert data["added"]["source_type"] == "rss"
        assert data["added"]["label"] == "Hacker News"

    async def test_add_github_source_success(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={"action": "add", "url": "owner/repo", "source_type": "github"},
        )
        data = parse(result)
        assert "error" not in data
        assert data["added"]["source_type"] == "github"

    async def test_add_default_poll_interval(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={"action": "add", "url": "https://example.com/rss", "source_type": "rss"},
        )
        data = parse(result)
        assert data["added"]["poll_interval_minutes"] == 60

    async def test_add_custom_poll_interval(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
                "poll_interval_minutes": 120,
            },
        )
        data = parse(result)
        assert data["added"]["poll_interval_minutes"] == 120

    async def test_add_custom_trust_weight(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
                "trust_weight": 0.7,
            },
        )
        data = parse(result)
        assert data["added"]["trust_weight"] == pytest.approx(0.7)

    async def test_add_missing_url_returns_missing_field(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={"action": "add", "source_type": "rss"},
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "MISSING_FIELD"

    async def test_add_missing_source_type_returns_missing_field(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={"action": "add", "url": "https://example.com/rss"},
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "MISSING_FIELD"

    async def test_add_invalid_source_type_returns_error(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "slack",
            },
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_SOURCE_TYPE"

    async def test_add_invalid_poll_interval_zero_returns_error(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
                "poll_interval_minutes": 0,
            },
        )
        data = parse(result)
        assert data["error"] is True

    async def test_add_trust_weight_out_of_range_returns_error(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
                "trust_weight": 2.0,
            },
        )
        data = parse(result)
        assert data["error"] is True

    async def test_add_duplicate_url_returns_duplicate_source_error(self) -> None:
        store = FakeSourceStore()
        # Add once successfully
        await _handle_watch(
            store=store,
            arguments={"action": "add", "url": "https://example.com/rss", "source_type": "rss"},
        )
        # Second add with same URL
        result = await _handle_watch(
            store=store,
            arguments={"action": "add", "url": "https://example.com/rss", "source_type": "rss"},
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "DUPLICATE_SOURCE"

    async def test_add_response_includes_updated_sources_list(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={"action": "add", "url": "https://example.com/rss", "source_type": "rss"},
        )
        data = parse(result)
        assert "sources" in data
        assert isinstance(data["sources"], list)


# ---------------------------------------------------------------------------
# _handle_watch — remove action
# ---------------------------------------------------------------------------


class TestHandleWatchRemove:
    async def test_remove_existing_source(self) -> None:
        store = FakeSourceStore()
        await store.add_feed_source(url="https://example.com/rss", source_type="rss")
        result = await _handle_watch(
            store=store,
            arguments={"action": "remove", "url": "https://example.com/rss"},
        )
        data = parse(result)
        assert data["removed"] is True
        assert data["removed_url"] == "https://example.com/rss"
        remaining = await store.list_feed_sources()
        assert len(remaining) == 0

    async def test_remove_nonexistent_source_returns_removed_false(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={"action": "remove", "url": "https://not-there.com/rss"},
        )
        data = parse(result)
        assert data["removed"] is False

    async def test_remove_missing_url_returns_missing_field(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(store=store, arguments={"action": "remove"})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "MISSING_FIELD"

    async def test_remove_only_removes_matching_source(self) -> None:
        store = FakeSourceStore()
        await store.add_feed_source(url="https://keep.com/rss", source_type="rss")
        await store.add_feed_source(url="https://remove.com/rss", source_type="rss")
        await _handle_watch(
            store=store,
            arguments={"action": "remove", "url": "https://remove.com/rss"},
        )
        remaining = await store.list_feed_sources()
        assert len(remaining) == 1
        assert remaining[0]["url"] == "https://keep.com/rss"

    async def test_remove_response_includes_updated_sources(self) -> None:
        store = FakeSourceStore()
        await store.add_feed_source(url="https://example.com/rss", source_type="rss")
        result = await _handle_watch(
            store=store,
            arguments={"action": "remove", "url": "https://example.com/rss"},
        )
        data = parse(result)
        assert "sources" in data
        assert data["sources"] == []


# ---------------------------------------------------------------------------
# _handle_watch — invalid action
# ---------------------------------------------------------------------------


class TestHandleWatchInvalidAction:
    async def test_invalid_action_returns_invalid_action_error(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(store=store, arguments={"action": "purge"})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_ACTION"

    async def test_missing_action_returns_error(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(store=store, arguments={})
        data = parse(result)
        assert data["error"] is True

    async def test_non_string_action_returns_error(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(store=store, arguments={"action": 42})
        data = parse(result)
        assert data["error"] is True


# ---------------------------------------------------------------------------
# _handle_poll
# ---------------------------------------------------------------------------


def _make_poll_summary(
    results: list[PollResult] | None = None,
) -> PollerSummary:
    results = results or []
    now = datetime.now(tz=UTC)
    return PollerSummary(
        results=results,
        total_fetched=sum(r.items_fetched for r in results),
        total_stored=sum(r.items_stored for r in results),
        total_skipped_dedup=sum(r.items_skipped_dedup for r in results),
        total_below_threshold=sum(r.items_below_threshold for r in results),
        sources_polled=len(results),
        sources_errored=sum(1 for r in results if r.errors),
        started_at=now,
        finished_at=now,
    )


class TestHandlePoll:
    async def test_poll_success_returns_summary(self) -> None:
        store = FakeSourceStore()
        config = make_config()
        result_item = PollResult(
            source_url="https://example.com/rss",
            source_type="rss",
            items_fetched=5,
            items_stored=3,
            items_skipped_dedup=1,
            items_below_threshold=1,
        )
        summary = _make_poll_summary([result_item])

        mock_poller = MagicMock()
        mock_poller.poll = AsyncMock(return_value=summary)

        with patch("distillery.feeds.poller.FeedPoller", return_value=mock_poller):
            result = await _handle_poll(store=store, config=config, arguments={})

        data = parse(result)
        assert "error" not in data
        assert data["sources_polled"] == 1
        assert data["total_fetched"] == 5
        assert data["total_stored"] == 3
        assert data["total_skipped_dedup"] == 1
        assert data["total_below_threshold"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["source_url"] == "https://example.com/rss"
        assert data["results"][0]["source_type"] == "rss"
        assert "started_at" in data
        assert "finished_at" in data

    async def test_poll_with_source_url_filter(self) -> None:
        """When source_url is given and it exists, poll is invoked with that URL."""
        store = FakeSourceStore()
        await store.add_feed_source(url="https://example.com/rss", source_type="rss")
        config = make_config()
        summary = _make_poll_summary()

        mock_poller = MagicMock()
        mock_poller.poll = AsyncMock(return_value=summary)

        with patch("distillery.feeds.poller.FeedPoller", return_value=mock_poller):
            result = await _handle_poll(
                store=store,
                config=config,
                arguments={"source_url": "https://example.com/rss"},
            )

        data = parse(result)
        assert "error" not in data
        mock_poller.poll.assert_called_once_with(source_url="https://example.com/rss")

    async def test_poll_unknown_source_url_returns_not_found(self) -> None:
        """source_url not in configured sources returns NOT_FOUND."""
        store = FakeSourceStore()
        config = make_config()

        result = await _handle_poll(
            store=store,
            config=config,
            arguments={"source_url": "https://not-configured.com/rss"},
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_poll_error_returns_poll_error(self) -> None:
        """FeedPoller.poll raising returns POLL_ERROR."""
        store = FakeSourceStore()
        config = make_config()

        mock_poller = MagicMock()
        mock_poller.poll = AsyncMock(side_effect=RuntimeError("network failure"))

        with patch("distillery.feeds.poller.FeedPoller", return_value=mock_poller):
            result = await _handle_poll(store=store, config=config, arguments={})

        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "POLL_ERROR"
        assert "network failure" in data["message"]

    async def test_poll_result_has_iso_polled_at(self) -> None:
        """polled_at in each result must be an ISO-formatted datetime string."""
        store = FakeSourceStore()
        config = make_config()
        result_item = PollResult(
            source_url="https://example.com/rss",
            source_type="rss",
        )
        summary = _make_poll_summary([result_item])

        mock_poller = MagicMock()
        mock_poller.poll = AsyncMock(return_value=summary)

        with patch("distillery.feeds.poller.FeedPoller", return_value=mock_poller):
            result = await _handle_poll(store=store, config=config, arguments={})

        data = parse(result)
        polled_at = data["results"][0]["polled_at"]
        # Should parse without error as ISO datetime
        datetime.fromisoformat(polled_at)

    async def test_poll_no_sources_returns_empty_summary(self) -> None:
        """Polling with no configured sources returns a valid empty summary."""
        store = FakeSourceStore()
        config = make_config()
        summary = _make_poll_summary()

        mock_poller = MagicMock()
        mock_poller.poll = AsyncMock(return_value=summary)

        with patch("distillery.feeds.poller.FeedPoller", return_value=mock_poller):
            result = await _handle_poll(store=store, config=config, arguments={})

        data = parse(result)
        assert "error" not in data
        assert data["sources_polled"] == 0
        assert data["results"] == []


# ---------------------------------------------------------------------------
# _handle_interests (suggest_sources=True)
# ---------------------------------------------------------------------------


def _make_profile(
    tracked_repos: list[str] | None = None,
    bookmark_domains: list[str] | None = None,
    watched_sources: list[str] | None = None,
    entry_count: int = 10,
) -> InterestProfile:
    return InterestProfile(
        tracked_repos=tracked_repos or [],
        bookmark_domains=bookmark_domains or [],
        watched_sources=watched_sources or [],
        suggestion_context="You are interested in Python and tooling.",
        entry_count=entry_count,
    )


class TestHandleSuggestSources:
    async def test_suggest_sources_returns_github_suggestions(self) -> None:
        store = FakeSourceStore()
        config = make_config()
        profile = _make_profile(tracked_repos=["owner/cool-repo"])

        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(return_value=profile)

        with patch("distillery.feeds.interests.InterestExtractor", return_value=mock_extractor):
            result = await _handle_interests(
                store=store, config=config, arguments={"suggest_sources": True}
            )

        data = parse(result)
        assert "error" not in data
        assert data["entry_count"] == 10
        assert data["suggestion_context"] == "You are interested in Python and tooling."
        suggestions = data["suggestions"]
        assert len(suggestions) >= 1
        types = {s["source_type"] for s in suggestions}
        assert "github" in types

    async def test_suggest_sources_returns_rss_suggestions(self) -> None:
        store = FakeSourceStore()
        config = make_config()
        profile = _make_profile(bookmark_domains=["example.com"])

        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(return_value=profile)

        with patch("distillery.feeds.interests.InterestExtractor", return_value=mock_extractor):
            result = await _handle_interests(
                store=store, config=config, arguments={"suggest_sources": True}
            )

        data = parse(result)
        assert "error" not in data
        suggestions = data["suggestions"]
        assert any(s["source_type"] == "rss" for s in suggestions)

    async def test_suggest_sources_empty_store_returns_no_suggestions(self) -> None:
        store = FakeSourceStore()
        config = make_config()
        profile = _make_profile(entry_count=0)

        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(return_value=profile)

        with patch("distillery.feeds.interests.InterestExtractor", return_value=mock_extractor):
            result = await _handle_interests(
                store=store, config=config, arguments={"suggest_sources": True}
            )

        data = parse(result)
        assert "error" not in data
        assert data["suggestions"] == []
        assert data["entry_count"] == 0

    async def test_suggest_sources_excludes_already_watched(self) -> None:
        """Repos already in watched_sources should not appear as suggestions."""
        store = FakeSourceStore()
        config = make_config()
        profile = _make_profile(
            tracked_repos=["owner/repo"],
            watched_sources=["owner/repo"],
        )

        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(return_value=profile)

        with patch("distillery.feeds.interests.InterestExtractor", return_value=mock_extractor):
            result = await _handle_interests(
                store=store, config=config, arguments={"suggest_sources": True}
            )

        data = parse(result)
        assert "error" not in data
        urls = [s["url"] for s in data["suggestions"]]
        assert "owner/repo" not in urls

    async def test_suggest_sources_custom_max_suggestions(self) -> None:
        store = FakeSourceStore()
        config = make_config()
        profile = _make_profile(
            tracked_repos=["a/b", "c/d", "e/f", "g/h"],
        )

        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(return_value=profile)

        with patch("distillery.feeds.interests.InterestExtractor", return_value=mock_extractor):
            result = await _handle_interests(
                store=store,
                config=config,
                arguments={"suggest_sources": True, "max_suggestions": 2},
            )

        data = parse(result)
        assert len(data["suggestions"]) <= 2

    async def test_suggest_sources_invalid_max_suggestions_zero_returns_error(self) -> None:
        store = FakeSourceStore()
        config = make_config()

        result = await _handle_interests(
            store=store,
            config=config,
            arguments={"suggest_sources": True, "max_suggestions": 0},
        )
        data = parse(result)
        assert data["error"] is True

    async def test_suggest_sources_invalid_recency_days_returns_error(self) -> None:
        store = FakeSourceStore()
        config = make_config()

        result = await _handle_interests(
            store=store,
            config=config,
            arguments={"suggest_sources": True, "recency_days": -1},
        )
        data = parse(result)
        assert data["error"] is True

    async def test_suggest_sources_extraction_error_returns_extraction_error(self) -> None:
        store = FakeSourceStore()
        config = make_config()

        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(side_effect=RuntimeError("store unavailable"))

        with patch("distillery.feeds.interests.InterestExtractor", return_value=mock_extractor):
            result = await _handle_interests(
                store=store, config=config, arguments={"suggest_sources": True}
            )

        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "EXTRACTION_ERROR"

    async def test_suggest_sources_response_shape(self) -> None:
        """Response always contains suggestions, suggestion_context, watched_sources, entry_count."""
        store = FakeSourceStore()
        config = make_config()
        profile = _make_profile()

        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(return_value=profile)

        with patch("distillery.feeds.interests.InterestExtractor", return_value=mock_extractor):
            result = await _handle_interests(
                store=store, config=config, arguments={"suggest_sources": True}
            )

        data = parse(result)
        assert "suggestions" in data
        assert "suggestion_context" in data
        assert "watched_sources" in data
        assert "entry_count" in data


# ---------------------------------------------------------------------------
# _sanitise_last_error — helper that truncates + sanitises poll error strings
# ---------------------------------------------------------------------------


class TestSanitiseLastError:
    def test_none_returns_none(self) -> None:
        assert _sanitise_last_error(None, 200) is None

    def test_empty_returns_none(self) -> None:
        # An all-whitespace input collapses to an empty string → None so
        # a successful poll clears any previous error.
        assert _sanitise_last_error("   \n\t", 200) is None

    def test_short_error_is_preserved(self) -> None:
        assert _sanitise_last_error("upstream 502", 200) == "upstream 502"

    def test_collapses_whitespace_and_newlines(self) -> None:
        raw = "Traceback:\n  File 'x'\n  ValueError: boom"
        assert _sanitise_last_error(raw, 200) == "Traceback: File 'x' ValueError: boom"

    def test_truncates_when_longer_than_max_len(self) -> None:
        raw = "x" * 500
        result = _sanitise_last_error(raw, 50)
        assert result is not None
        # Exactly max_len characters, including the ellipsis sentinel.
        assert len(result) == 50
        assert result.endswith("\u2026")
