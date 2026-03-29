"""Tests for RelevanceScorer, FeedPoller, and the distillery_poll MCP handler.

Covers:
  - RelevanceScorer.score: returns max similarity, handles empty text, handles errors
  - FeedPoller.poll: empty sources, items stored, dedup skipping, threshold filtering
  - FeedPoller._is_duplicate: similarity-based dedup
  - _handle_poll: MCP handler success path and error paths
  - distillery poll CLI subcommand
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from distillery.config import (
    DistilleryConfig,
    FeedsConfig,
    FeedSourceConfig,
    FeedsThresholdsConfig,
)
from distillery.feeds.models import FeedItem
from distillery.feeds.poller import FeedPoller, _item_text
from distillery.feeds.scorer import RelevanceScorer
from distillery.store.protocol import SearchResult

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_feed_item(
    item_id: str = "item-1",
    source_url: str = "https://example.com/rss",
    source_type: str = "rss",
    title: str | None = "Test Item",
    content: str | None = "Test content",
) -> FeedItem:
    return FeedItem(
        source_url=source_url,
        source_type=source_type,
        item_id=item_id,
        title=title,
        content=content,
    )


def _make_search_result(score: float = 0.8, external_id: str = "") -> SearchResult:
    from distillery.models import Entry, EntrySource, EntryType

    entry = Entry(
        content="existing content",
        entry_type=EntryType.FEED,
        source=EntrySource.IMPORT,
        author="poller",
        metadata={"external_id": external_id} if external_id else {},
    )
    return SearchResult(entry=entry, score=score)


def _make_store(
    find_similar_results: list[SearchResult] | None = None,
) -> AsyncMock:
    store = AsyncMock()
    store.find_similar.return_value = find_similar_results or []
    store.list_entries.return_value = []  # default: no external_id matches
    store.store.return_value = "new-entry-id"
    return store


def _make_config(
    sources: list[FeedSourceConfig] | None = None,
    digest_threshold: float = 0.0,
) -> DistilleryConfig:
    cfg = DistilleryConfig()
    cfg.feeds = FeedsConfig(
        sources=sources or [],
        thresholds=FeedsThresholdsConfig(alert=0.85, digest=digest_threshold),
    )
    return cfg


# ---------------------------------------------------------------------------
# RelevanceScorer
# ---------------------------------------------------------------------------


class TestRelevanceScorer:
    async def test_empty_text_returns_zero(self) -> None:
        store = _make_store()
        scorer = RelevanceScorer(store=store)
        score = await scorer.score("   ")
        assert score == 0.0
        store.find_similar.assert_not_called()

    async def test_returns_max_similarity(self) -> None:
        results = [
            _make_search_result(score=0.7),
            _make_search_result(score=0.9),
            _make_search_result(score=0.5),
        ]
        store = _make_store(find_similar_results=results)
        scorer = RelevanceScorer(store=store)
        score = await scorer.score("hello world")
        assert score == pytest.approx(0.9)

    async def test_no_results_returns_zero(self) -> None:
        store = _make_store(find_similar_results=[])
        scorer = RelevanceScorer(store=store)
        score = await scorer.score("hello world")
        assert score == 0.0

    async def test_passes_threshold_to_store(self) -> None:
        store = _make_store()
        scorer = RelevanceScorer(store=store, min_score=0.5)
        await scorer.score("test text")
        store.find_similar.assert_called_once()
        call_kwargs = store.find_similar.call_args.kwargs
        assert call_kwargs["threshold"] == 0.5

    async def test_exception_propagates(self) -> None:
        store = AsyncMock()
        store.find_similar.side_effect = RuntimeError("db error")
        scorer = RelevanceScorer(store=store)
        with pytest.raises(RuntimeError, match="db error"):
            await scorer.score("test text")

    async def test_single_result_returns_that_score(self) -> None:
        store = _make_store(find_similar_results=[_make_search_result(score=0.75)])
        scorer = RelevanceScorer(store=store)
        score = await scorer.score("test text")
        assert score == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# _item_text
# ---------------------------------------------------------------------------


class TestItemText:
    def test_title_and_content(self) -> None:
        item = _make_feed_item(title="Title", content="Content")
        assert _item_text(item) == "Title\nContent"

    def test_title_only(self) -> None:
        item = _make_feed_item(title="Title", content=None)
        assert _item_text(item) == "Title"

    def test_content_only(self) -> None:
        item = _make_feed_item(title=None, content="Content")
        assert _item_text(item) == "Content"

    def test_both_none(self) -> None:
        item = _make_feed_item(title=None, content=None)
        assert _item_text(item) == ""


# ---------------------------------------------------------------------------
# FeedPoller.poll — empty sources
# ---------------------------------------------------------------------------


class TestFeedPollerEmptySources:
    async def test_empty_sources_returns_empty_summary(self) -> None:
        store = _make_store()
        cfg = _make_config(sources=[])
        poller = FeedPoller(store=store, config=cfg)
        summary = await poller.poll()
        assert summary.sources_polled == 0
        assert summary.total_fetched == 0
        assert summary.total_stored == 0
        assert summary.results == []


# ---------------------------------------------------------------------------
# FeedPoller.poll — with RSS adapter mocked
# ---------------------------------------------------------------------------


class TestFeedPollerRSS:
    def _rss_source(self) -> FeedSourceConfig:
        return FeedSourceConfig(
            url="https://example.com/rss",
            source_type="rss",
            trust_weight=1.0,
        )

    async def test_items_above_threshold_are_stored(self) -> None:
        items = [_make_feed_item(item_id="id1", title="Python news", content="Details")]
        store = _make_store(find_similar_results=[_make_search_result(score=0.9)])
        cfg = _make_config(sources=[self._rss_source()], digest_threshold=0.5)

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.return_value = items
            mock_build.return_value = mock_adapter

            poller = FeedPoller(store=store, config=cfg)
            # Override find_similar to return no dedup match on first call, then score
            call_count = 0

            async def _find_similar(content: str, threshold: float, limit: int) -> list:
                nonlocal call_count
                call_count += 1
                if threshold == 0.95:
                    return []  # no dedup match
                return [_make_search_result(score=0.9)]  # high relevance

            store.find_similar.side_effect = _find_similar
            summary = await poller.poll()

        assert summary.total_stored == 1
        assert summary.total_fetched == 1
        assert summary.sources_polled == 1

    async def test_items_below_threshold_not_stored(self) -> None:
        items = [_make_feed_item(item_id="id1", title="Irrelevant item", content="Unrelated")]
        store = _make_store()
        cfg = _make_config(sources=[self._rss_source()], digest_threshold=0.8)

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.return_value = items
            mock_build.return_value = mock_adapter

            call_count = 0

            async def _find_similar(content: str, threshold: float, limit: int) -> list:
                nonlocal call_count
                call_count += 1
                if threshold == 0.95:
                    return []  # no dedup
                return [_make_search_result(score=0.3)]  # low relevance

            store.find_similar.side_effect = _find_similar
            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.total_stored == 0
        assert summary.total_below_threshold == 1

    async def test_duplicate_items_are_skipped(self) -> None:
        items = [_make_feed_item(item_id="id1", title="Dup title", content="Dup content")]
        store = _make_store()
        cfg = _make_config(sources=[self._rss_source()], digest_threshold=0.0)

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.return_value = items
            mock_build.return_value = mock_adapter

            async def _find_similar(content: str, threshold: float, limit: int) -> list:
                if threshold == 0.95:
                    # Return a match with the same external_id → dedup
                    return [_make_search_result(score=0.97, external_id="id1")]
                return []

            store.find_similar.side_effect = _find_similar
            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.total_skipped_dedup == 1
        assert summary.total_stored == 0
        store.store.assert_not_called()

    async def test_adapter_fetch_error_recorded(self) -> None:
        store = _make_store()
        cfg = _make_config(sources=[self._rss_source()])

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.side_effect = RuntimeError("network error")
            mock_build.return_value = mock_adapter

            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.sources_errored == 1
        assert len(summary.results[0].errors) == 1
        assert "network error" in summary.results[0].errors[0]

    async def test_unsupported_source_type_records_error(self) -> None:
        source = FeedSourceConfig(
            url="https://webhooks.example.com",
            source_type="hackernews",
        )
        store = _make_store()
        cfg = _make_config(sources=[source])
        poller = FeedPoller(store=store, config=cfg)
        summary = await poller.poll()
        assert summary.sources_errored == 1
        assert summary.results[0].errors

    async def test_trust_weight_applied_to_score(self) -> None:
        """trust_weight=0.5 should halve the score, potentially dropping below threshold."""
        source = FeedSourceConfig(
            url="https://example.com/rss",
            source_type="rss",
            trust_weight=0.5,
        )
        items = [_make_feed_item(item_id="id1")]
        store = _make_store()
        cfg = _make_config(sources=[source], digest_threshold=0.8)

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.return_value = items
            mock_build.return_value = mock_adapter

            async def _find_similar(content: str, threshold: float, limit: int) -> list:
                if threshold == 0.95:
                    return []
                # Raw score 0.9 * trust_weight 0.5 = 0.45 — below 0.8 threshold
                return [_make_search_result(score=0.9)]

            store.find_similar.side_effect = _find_similar
            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.total_below_threshold == 1
        assert summary.total_stored == 0

    async def test_item_with_no_text_skipped(self) -> None:
        items = [_make_feed_item(title=None, content=None)]
        store = _make_store()
        cfg = _make_config(sources=[self._rss_source()], digest_threshold=0.0)

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.return_value = items
            mock_build.return_value = mock_adapter

            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.total_stored == 0
        assert summary.total_below_threshold == 1


# ---------------------------------------------------------------------------
# FeedPoller.poll — multiple sources
# ---------------------------------------------------------------------------


class TestFeedPollerMultipleSources:
    async def test_aggregates_across_sources(self) -> None:
        sources = [
            FeedSourceConfig(url="https://a.com/rss", source_type="rss"),
            FeedSourceConfig(url="https://b.com/rss", source_type="rss"),
        ]
        items_a = [_make_feed_item(item_id="a1", source_url="https://a.com/rss")]
        items_b = [
            _make_feed_item(item_id="b1", source_url="https://b.com/rss"),
            _make_feed_item(item_id="b2", source_url="https://b.com/rss"),
        ]

        store = AsyncMock()
        store.store.return_value = "eid"
        store.list_entries.return_value = []  # no external_id matches

        source_items_map = {
            "https://a.com/rss": items_a,
            "https://b.com/rss": items_b,
        }
        cfg = _make_config(sources=sources, digest_threshold=0.0)

        def _build_adapter_side_effect(source: FeedSourceConfig) -> MagicMock:
            mock = MagicMock()
            mock.fetch.return_value = source_items_map[source.url]
            return mock

        async def _find_similar(content: str, threshold: float, limit: int) -> list:
            if threshold == 0.95:
                return []
            return [_make_search_result(score=0.8)]

        store.find_similar.side_effect = _find_similar

        with patch(
            "distillery.feeds.poller._build_adapter", side_effect=_build_adapter_side_effect
        ):
            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.sources_polled == 2
        assert summary.total_fetched == 3
        assert summary.total_stored == 3
        assert len(summary.results) == 2


# ---------------------------------------------------------------------------
# _handle_poll
# ---------------------------------------------------------------------------


class TestHandlePoll:
    async def test_no_sources_returns_empty_summary(self) -> None:
        from distillery.mcp.server import _handle_poll

        store = _make_store()
        cfg = _make_config(sources=[])
        result = await _handle_poll(store=store, config=cfg, arguments={})
        data = json.loads(result[0].text)
        assert data["sources_polled"] == 0
        assert data["total_stored"] == 0

    async def test_source_url_filter_not_found_returns_error(self) -> None:
        from distillery.mcp.server import _handle_poll

        store = _make_store()
        cfg = _make_config(
            sources=[FeedSourceConfig(url="https://real.com/rss", source_type="rss")]
        )
        result = await _handle_poll(
            store=store, config=cfg, arguments={"source_url": "https://nonexistent.com/rss"}
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True
        assert data["code"] == "NOT_FOUND"

    async def test_source_url_filter_narrows_poll(self) -> None:
        from distillery.mcp.server import _handle_poll

        sources = [
            FeedSourceConfig(url="https://a.com/rss", source_type="rss"),
            FeedSourceConfig(url="https://b.com/rss", source_type="rss"),
        ]
        cfg = _make_config(sources=sources, digest_threshold=0.0)
        store = _make_store()

        items = [_make_feed_item(item_id="x1", source_url="https://a.com/rss")]

        async def _find_similar(content: str, threshold: float, limit: int) -> list:
            if threshold == 0.95:
                return []
            return [_make_search_result(score=0.9)]

        store.find_similar.side_effect = _find_similar

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.return_value = items
            mock_build.return_value = mock_adapter

            result = await _handle_poll(
                store=store, config=cfg, arguments={"source_url": "https://a.com/rss"}
            )

        data = json.loads(result[0].text)
        assert data["sources_polled"] == 1
        assert data["total_fetched"] == 1

    async def test_returns_all_expected_fields(self) -> None:
        from distillery.mcp.server import _handle_poll

        cfg = _make_config(sources=[])
        store = _make_store()
        result = await _handle_poll(store=store, config=cfg, arguments={})
        data = json.loads(result[0].text)
        for key in (
            "sources_polled",
            "sources_errored",
            "total_fetched",
            "total_stored",
            "total_skipped_dedup",
            "total_below_threshold",
            "results",
            "started_at",
            "finished_at",
        ):
            assert key in data, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# CLI poll subcommand
# ---------------------------------------------------------------------------


class TestCLIPollSubcommand:
    def test_no_sources_exits_zero(self) -> None:
        from distillery.cli import _cmd_poll

        with patch("distillery.cli.load_config") as mock_load:
            cfg = _make_config(sources=[])
            mock_load.return_value = cfg
            code = _cmd_poll(config_path=None, fmt="text", source_url=None)
            assert code == 0

    def test_source_not_found_exits_one(self) -> None:
        from distillery.cli import _cmd_poll

        with patch("distillery.cli.load_config") as mock_load:
            cfg = _make_config(
                sources=[FeedSourceConfig(url="https://real.com/rss", source_type="rss")]
            )
            mock_load.return_value = cfg
            code = _cmd_poll(config_path=None, fmt="text", source_url="https://nonexistent.com/rss")
            assert code == 1

    def test_poll_runs_and_exits_zero_on_no_errors(self) -> None:
        from distillery.cli import main

        with patch("distillery.cli._cmd_poll", return_value=0):
            with pytest.raises(SystemExit) as exc_info:
                main(["poll"])
            assert exc_info.value.code == 0

    def test_poll_json_format_accepted(self) -> None:
        from distillery.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["poll", "--format", "json"])
        assert args.format == "json"
        assert args.command == "poll"

    def test_poll_source_flag(self) -> None:
        from distillery.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["poll", "--source", "https://example.com/rss"])
        assert args.source == "https://example.com/rss"
