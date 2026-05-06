"""Tests for the /radar published-at floor and first-poll backfill flag.

Issue #444: ``/radar`` was surfacing decade-old items as new intelligence
because:
  1. Newly registered feed sources backfill historical items on the first
     poll, but those items were not flagged.
  2. The candidate-set query bounded results by ``created_at`` (ingest time)
     instead of ``metadata.published_at`` (publication time), so an item
     published in 2009 but polled today fell inside any "last N days" window.

This module exercises the fix end-to-end:
  - ``_item_to_entry_kwargs(is_backfill=True)`` writes ``metadata.backfill``.
  - ``FeedPoller`` flags only the first batch per source as backfill, never
    subsequent polls.
  - The DuckDB store filters on ``published_after`` / ``published_before`` /
    ``exclude_backfill``.
  - The MCP filter builder attaches ``exclude_backfill`` automatically when
    ``published_after`` is set and ``include_evergreen`` is False, and skips
    it otherwise.
  - ``distillery_configure`` accepts the ``feeds.digest.window_days`` knob.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from distillery.config import (
    ClassificationConfig,
    DefaultsConfig,
    DigestConfig,
    DistilleryConfig,
    EmbeddingConfig,
    FeedsConfig,
    FeedSourceConfig,
    FeedsThresholdsConfig,
    StorageConfig,
)
from distillery.feeds.models import FeedItem
from distillery.feeds.poller import FeedPoller, _item_to_entry_kwargs
from distillery.mcp.tools.configure import _handle_configure
from distillery.mcp.tools.crud import _build_filters_from_arguments
from distillery.models import Entry, EntrySource, EntryType
from distillery.store.duckdb import DuckDBStore

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _item_to_entry_kwargs: backfill flag
# ---------------------------------------------------------------------------


class TestItemToEntryKwargsBackfillFlag:
    def _make_item(self) -> FeedItem:
        return FeedItem(
            source_url="https://example.com/rss",
            source_type="rss",
            item_id="item-1",
            title="Title",
            content="Body",
        )

    def test_default_no_backfill_flag(self) -> None:
        item = self._make_item()
        kwargs = _item_to_entry_kwargs(item, relevance_score=0.5)
        assert "backfill" not in kwargs["metadata"]

    def test_explicit_false_no_backfill_flag(self) -> None:
        item = self._make_item()
        kwargs = _item_to_entry_kwargs(item, relevance_score=0.5, is_backfill=False)
        assert "backfill" not in kwargs["metadata"]

    def test_is_backfill_true_sets_metadata(self) -> None:
        item = self._make_item()
        kwargs = _item_to_entry_kwargs(item, relevance_score=0.5, is_backfill=True)
        assert kwargs["metadata"]["backfill"] is True


# ---------------------------------------------------------------------------
# FeedPoller: first poll vs. subsequent polls
# ---------------------------------------------------------------------------


def _source_dict(
    url: str = "https://example.com/rss",
    *,
    last_polled_at: str | None = None,
) -> dict[str, Any]:
    return {
        "url": url,
        "source_type": "rss",
        "label": "",
        "poll_interval_minutes": 60,
        "trust_weight": 1.0,
        "last_polled_at": last_polled_at,
        "last_item_count": 0,
        "last_error": None,
        "next_poll_at": None,
    }


def _make_feed_item(item_id: str = "id1") -> FeedItem:
    return FeedItem(
        source_url="https://example.com/rss",
        source_type="rss",
        item_id=item_id,
        title="Title",
        content="Body",
    )


def _make_store_for_poller(
    feed_sources: list[dict[str, Any]],
    stored_entries: list[Entry] | None = None,
) -> AsyncMock:
    """Build a mock store that captures every Entry passed to ``store()``."""
    store = AsyncMock()
    captured: list[Entry] = stored_entries if stored_entries is not None else []

    async def _capture_store(entry: Entry) -> str:
        captured.append(entry)
        return str(entry.id)

    store.store.side_effect = _capture_store
    store.find_similar.return_value = []
    store.list_entries.return_value = []  # no external_id matches
    store.get_tag_vocabulary.return_value = {}
    store.list_feed_sources = AsyncMock(return_value=feed_sources)
    return store


def _make_poller_config() -> DistilleryConfig:
    cfg = DistilleryConfig()
    cfg.feeds = FeedsConfig(
        thresholds=FeedsThresholdsConfig(alert=0.85, digest=0.0),
    )
    return cfg


class TestPollerBackfillFlag:
    async def test_first_poll_marks_items_as_backfill(self) -> None:
        """Source with last_polled_at=None gets metadata.backfill=true."""
        items = [_make_feed_item("a1")]
        captured: list[Entry] = []
        store = _make_store_for_poller([_source_dict(last_polled_at=None)], stored_entries=captured)
        cfg = _make_poller_config()

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.return_value = items
            mock_build.return_value = mock_adapter

            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.total_stored == 1
        assert len(captured) == 1
        assert captured[0].metadata.get("backfill") is True

    async def test_subsequent_poll_does_not_mark_backfill(self) -> None:
        """Source with last_polled_at != None must NOT mark items as backfill."""
        items = [_make_feed_item("a2")]
        captured: list[Entry] = []
        store = _make_store_for_poller(
            [_source_dict(last_polled_at="2026-01-01T00:00:00+00:00")],
            stored_entries=captured,
        )
        cfg = _make_poller_config()

        with patch("distillery.feeds.poller._build_adapter") as mock_build:
            mock_adapter = MagicMock()
            mock_adapter.fetch.return_value = items
            mock_build.return_value = mock_adapter

            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.total_stored == 1
        assert len(captured) == 1
        assert "backfill" not in captured[0].metadata

    async def test_backfill_flag_is_per_source(self) -> None:
        """One never-polled source plus one previously-polled source: only first batch is flagged."""
        captured: list[Entry] = []
        sources = [
            _source_dict(url="https://new.com/rss", last_polled_at=None),
            _source_dict(url="https://old.com/rss", last_polled_at="2026-01-01T00:00:00+00:00"),
        ]
        store = _make_store_for_poller(sources, stored_entries=captured)
        cfg = _make_poller_config()

        items_by_url = {
            "https://new.com/rss": [
                FeedItem(
                    source_url="https://new.com/rss",
                    source_type="rss",
                    item_id="new1",
                    title="N",
                    content="C",
                )
            ],
            "https://old.com/rss": [
                FeedItem(
                    source_url="https://old.com/rss",
                    source_type="rss",
                    item_id="old1",
                    title="O",
                    content="C",
                )
            ],
        }

        def _build(source: FeedSourceConfig, **_kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.fetch.return_value = items_by_url[source.url]
            return mock

        with patch("distillery.feeds.poller._build_adapter", side_effect=_build):
            poller = FeedPoller(store=store, config=cfg)
            summary = await poller.poll()

        assert summary.total_stored == 2
        by_url = {e.metadata["source_url"]: e for e in captured}
        assert by_url["https://new.com/rss"].metadata.get("backfill") is True
        assert "backfill" not in by_url["https://old.com/rss"].metadata


# ---------------------------------------------------------------------------
# DuckDBStore: published_after / published_before / exclude_backfill filters
# ---------------------------------------------------------------------------


def _make_feed_entry(
    *,
    content: str,
    published_at: str | None,
    backfill: bool = False,
) -> Entry:
    metadata: dict[str, Any] = {
        "source_url": "https://example.com/rss",
        "source_type": "rss",
        "external_id": content,  # unique per entry
    }
    if published_at is not None:
        metadata["published_at"] = published_at
    if backfill:
        metadata["backfill"] = True
    return Entry(
        content=content,
        entry_type=EntryType.FEED,
        source=EntrySource.IMPORT,
        author="poller",
        metadata=metadata,
    )


class TestDuckDBPublishedAtFilters:
    async def test_published_after_excludes_old_items(self, store: DuckDBStore) -> None:
        old = _make_feed_entry(content="old", published_at="2009-01-01T00:00:00+00:00")
        new = _make_feed_entry(content="new", published_at="2026-05-01T00:00:00+00:00")
        await store.store(old)
        await store.store(new)

        results = await store.list_entries(
            filters={"published_after": "2026-04-01T00:00:00+00:00"},
            limit=10,
            offset=0,
        )
        contents = [e.content for e in results]
        assert "new" in contents
        assert "old" not in contents

    async def test_exclude_backfill_drops_flagged_items(self, store: DuckDBStore) -> None:
        bf = _make_feed_entry(content="bf", published_at="2026-04-30T00:00:00+00:00", backfill=True)
        live = _make_feed_entry(
            content="live", published_at="2026-04-30T00:00:00+00:00", backfill=False
        )
        await store.store(bf)
        await store.store(live)

        results = await store.list_entries(
            filters={"exclude_backfill": True},
            limit=10,
            offset=0,
        )
        contents = [e.content for e in results]
        assert "live" in contents
        assert "bf" not in contents

    async def test_exclude_backfill_keeps_unflagged_legacy_rows(self, store: DuckDBStore) -> None:
        """Existing rows without metadata.backfill must NOT be hidden."""
        legacy = _make_feed_entry(content="legacy", published_at="2026-04-30T00:00:00+00:00")
        await store.store(legacy)

        results = await store.list_entries(
            filters={"exclude_backfill": True},
            limit=10,
            offset=0,
        )
        contents = [e.content for e in results]
        assert "legacy" in contents

    async def test_combined_published_after_and_exclude_backfill(self, store: DuckDBStore) -> None:
        old_bf = _make_feed_entry(
            content="old_bf", published_at="2009-01-01T00:00:00+00:00", backfill=True
        )
        new_bf = _make_feed_entry(
            content="new_bf", published_at="2026-05-01T00:00:00+00:00", backfill=True
        )
        new_live = _make_feed_entry(
            content="new_live", published_at="2026-05-01T00:00:00+00:00", backfill=False
        )
        for e in (old_bf, new_bf, new_live):
            await store.store(e)

        results = await store.list_entries(
            filters={
                "published_after": "2026-04-01T00:00:00+00:00",
                "exclude_backfill": True,
            },
            limit=10,
            offset=0,
        )
        contents = [e.content for e in results]
        assert contents == ["new_live"]


# ---------------------------------------------------------------------------
# MCP filter builder: published_after + include_evergreen interaction
# ---------------------------------------------------------------------------


class TestBuildFiltersFromArguments:
    def test_published_after_attaches_exclude_backfill_by_default(self) -> None:
        args = {"published_after": "2026-04-26T00:00:00+00:00"}
        filters = _build_filters_from_arguments(args)
        assert filters is not None
        assert filters.get("published_after") == "2026-04-26T00:00:00+00:00"
        assert filters.get("exclude_backfill") is True

    def test_published_after_with_include_evergreen_skips_exclude_backfill(
        self,
    ) -> None:
        args = {
            "published_after": "2026-04-26T00:00:00+00:00",
            "include_evergreen": True,
        }
        filters = _build_filters_from_arguments(args)
        assert filters is not None
        assert "exclude_backfill" not in filters

    def test_no_published_window_skips_exclude_backfill(self) -> None:
        """Generic list/search calls without time-window semantics keep backfill rows."""
        args = {"entry_type": "feed"}
        filters = _build_filters_from_arguments(args)
        assert filters is not None
        assert "exclude_backfill" not in filters

    def test_include_evergreen_string_true_is_honoured(self) -> None:
        args = {
            "published_after": "2026-04-26T00:00:00+00:00",
            "include_evergreen": "true",
        }
        filters = _build_filters_from_arguments(args)
        assert filters is not None
        assert "exclude_backfill" not in filters


# ---------------------------------------------------------------------------
# distillery_configure: feeds.digest.window_days knob
# ---------------------------------------------------------------------------


def _make_configure_cfg(window_days: int = 7) -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        defaults=DefaultsConfig(),
        classification=ClassificationConfig(),
        feeds=FeedsConfig(digest=DigestConfig(window_days=window_days)),
    )


class TestConfigureDigestWindowDays:
    @pytest.mark.asyncio
    async def test_read_default_value(self) -> None:
        cfg = _make_configure_cfg(window_days=7)
        result = await _handle_configure(cfg, {"section": "feeds.digest", "key": "window_days"})
        data = json.loads(result[0].text)
        assert data.get("error") is not True
        assert data["value"] == 7

    @pytest.mark.asyncio
    async def test_set_new_value(self) -> None:
        cfg = _make_configure_cfg(window_days=7)
        result = await _handle_configure(
            cfg,
            {"section": "feeds.digest", "key": "window_days", "value": 14},
        )
        data = json.loads(result[0].text)
        assert data.get("error") is not True
        assert data["changed"] is True
        assert data["new_value"] == 14
        assert cfg.feeds.digest.window_days == 14

    @pytest.mark.asyncio
    async def test_reject_zero(self) -> None:
        cfg = _make_configure_cfg()
        result = await _handle_configure(
            cfg,
            {"section": "feeds.digest", "key": "window_days", "value": 0},
        )
        data = json.loads(result[0].text)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_reject_non_integer(self) -> None:
        cfg = _make_configure_cfg()
        result = await _handle_configure(
            cfg,
            {"section": "feeds.digest", "key": "window_days", "value": 3.5},
        )
        data = json.loads(result[0].text)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# distillery_configure: feeds.digest.candidate_limit knob (Issue #461)
# ---------------------------------------------------------------------------


class TestConfigureDigestCandidateLimit:
    @pytest.mark.asyncio
    async def test_read_default_value(self) -> None:
        cfg = _make_configure_cfg()
        # DigestConfig.candidate_limit defaults to 35.
        assert cfg.feeds.digest.candidate_limit == 35
        result = await _handle_configure(cfg, {"section": "feeds.digest", "key": "candidate_limit"})
        data = json.loads(result[0].text)
        assert data.get("error") is not True
        assert data["value"] == 35

    @pytest.mark.asyncio
    async def test_set_new_value(self) -> None:
        cfg = _make_configure_cfg()
        result = await _handle_configure(
            cfg,
            {"section": "feeds.digest", "key": "candidate_limit", "value": 50},
        )
        data = json.loads(result[0].text)
        assert data.get("error") is not True
        assert data["changed"] is True
        assert data["new_value"] == 50
        assert cfg.feeds.digest.candidate_limit == 50

    @pytest.mark.asyncio
    async def test_reject_zero(self) -> None:
        cfg = _make_configure_cfg()
        result = await _handle_configure(
            cfg,
            {"section": "feeds.digest", "key": "candidate_limit", "value": 0},
        )
        data = json.loads(result[0].text)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_reject_non_integer(self) -> None:
        cfg = _make_configure_cfg()
        result = await _handle_configure(
            cfg,
            {"section": "feeds.digest", "key": "candidate_limit", "value": 12.5},
        )
        data = json.loads(result[0].text)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# Integration: skill-shaped /radar candidate-set query
# ---------------------------------------------------------------------------


class TestRadarCandidateSetIntegration:
    """Exercise the full DB path the /radar skill uses to retrieve candidates."""

    async def test_default_query_excludes_old_published_and_backfill(
        self, store: DuckDBStore
    ) -> None:
        # An item published 30 days ago, freshly polled today (no backfill).
        published_recent_iso = (datetime.now(tz=UTC) - timedelta(days=2)).isoformat()
        published_old_iso = (datetime.now(tz=UTC) - timedelta(days=30)).isoformat()
        await store.store(_make_feed_entry(content="recent", published_at=published_recent_iso))
        await store.store(_make_feed_entry(content="old_live", published_at=published_old_iso))
        await store.store(
            _make_feed_entry(
                content="old_backfill",
                published_at=published_recent_iso,  # recent date but flagged
                backfill=True,
            )
        )

        window_floor = (datetime.now(tz=UTC) - timedelta(days=7)).isoformat()
        # Default candidate set: published_after + exclude_backfill (the
        # MCP layer attaches exclude_backfill automatically when
        # include_evergreen is False).
        results = await store.list_entries(
            filters={
                "published_after": window_floor,
                "exclude_backfill": True,
            },
            limit=10,
            offset=0,
        )
        contents = {e.content for e in results}
        assert contents == {"recent"}

    async def test_include_evergreen_restores_backfill_rows(self, store: DuckDBStore) -> None:
        published_recent_iso = (datetime.now(tz=UTC) - timedelta(days=2)).isoformat()
        await store.store(_make_feed_entry(content="recent", published_at=published_recent_iso))
        await store.store(
            _make_feed_entry(
                content="recent_backfill",
                published_at=published_recent_iso,
                backfill=True,
            )
        )

        window_floor = (datetime.now(tz=UTC) - timedelta(days=7)).isoformat()
        # include_evergreen=True at the MCP layer means exclude_backfill is
        # not attached — exercise the store with only the published_after
        # bound (the skill's --include-evergreen path).
        results = await store.list_entries(
            filters={"published_after": window_floor},
            limit=10,
            offset=0,
        )
        contents = {e.content for e in results}
        assert contents == {"recent", "recent_backfill"}
