"""Tests for the distillery_watch MCP tool handler and feed entry type.

Covers:
  - _handle_watch: list, add, remove actions
  - EntryType.FEED enum value
  - feed metadata schema validation
  - FeedsConfig dataclass
"""

from __future__ import annotations

import json

import pytest

from distillery.config import DistilleryConfig, FeedSourceConfig
from distillery.models import TYPE_METADATA_SCHEMAS, EntryType, validate_metadata

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# EntryType.FEED
# ---------------------------------------------------------------------------


class TestFeedEntryType:
    def test_feed_enum_value(self) -> None:
        assert EntryType.FEED == "feed"

    def test_feed_in_entry_type_values(self) -> None:
        values = [e.value for e in EntryType]
        assert "feed" in values

    def test_feed_schema_registered(self) -> None:
        assert "feed" in TYPE_METADATA_SCHEMAS

    def test_feed_schema_has_required_fields(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["feed"]
        assert "source_url" in schema["required"]
        assert "source_type" in schema["required"]

    def test_feed_schema_has_optional_fields(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["feed"]
        for field in ("title", "item_url", "published_at", "relevance_score"):
            assert field in schema["optional"], f"{field!r} not in feed optional fields"

    def test_feed_schema_source_type_constraint(self) -> None:
        schema = TYPE_METADATA_SCHEMAS["feed"]
        constraints = schema.get("constraints", {})
        assert "source_type" in constraints
        assert set(constraints["source_type"]) == {"rss", "github", "hackernews", "webhook"}


class TestFeedMetadataValidation:
    def test_valid_rss_feed_metadata(self) -> None:
        validate_metadata("feed", {"source_url": "https://example.com/rss", "source_type": "rss"})

    def test_valid_github_feed_metadata(self) -> None:
        validate_metadata(
            "feed",
            {
                "source_url": "org/repo",
                "source_type": "github",
                "title": "New PR",
                "item_url": "https://github.com/org/repo/pull/1",
            },
        )

    def test_missing_source_url_raises(self) -> None:
        with pytest.raises(ValueError, match="source_url"):
            validate_metadata("feed", {"source_type": "rss"})

    def test_missing_source_type_raises(self) -> None:
        with pytest.raises(ValueError, match="source_type"):
            validate_metadata("feed", {"source_url": "https://example.com/rss"})

    def test_invalid_source_type_raises(self) -> None:
        with pytest.raises(ValueError, match="source_type"):
            validate_metadata(
                "feed",
                {"source_url": "https://example.com/rss", "source_type": "slack"},
            )

    def test_valid_with_all_optional_fields(self) -> None:
        validate_metadata(
            "feed",
            {
                "source_url": "https://example.com/rss",
                "source_type": "rss",
                "title": "Test Item",
                "item_url": "https://example.com/item/1",
                "published_at": "2026-01-01T00:00:00Z",
                "relevance_score": 0.87,
            },
        )


# ---------------------------------------------------------------------------
# _handle_watch: list action
# ---------------------------------------------------------------------------


class TestHandleWatchList:
    async def test_list_empty_sources(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(config=cfg, arguments={"action": "list"})
        assert len(result) == 1
        data = json.loads(result[0].text)
        assert data["sources"] == []
        assert data["count"] == 0

    async def test_list_with_preconfigured_sources(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        cfg.feeds.sources = [
            FeedSourceConfig(
                url="https://example.com/rss",
                source_type="rss",
                label="Example",
                poll_interval_minutes=60,
                trust_weight=1.0,
            )
        ]
        result = await _handle_watch(config=cfg, arguments={"action": "list"})
        data = json.loads(result[0].text)
        assert data["count"] == 1
        assert data["sources"][0]["url"] == "https://example.com/rss"

    async def test_list_source_fields(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        cfg.feeds.sources = [
            FeedSourceConfig(
                url="https://example.com/rss",
                source_type="rss",
                label="My Feed",
                poll_interval_minutes=30,
                trust_weight=0.8,
            )
        ]
        result = await _handle_watch(config=cfg, arguments={"action": "list"})
        data = json.loads(result[0].text)
        src = data["sources"][0]
        assert src["url"] == "https://example.com/rss"
        assert src["source_type"] == "rss"
        assert src["label"] == "My Feed"
        assert src["poll_interval_minutes"] == 30
        assert src["trust_weight"] == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# _handle_watch: add action
# ---------------------------------------------------------------------------


class TestHandleWatchAdd:
    async def test_add_rss_source(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={
                "action": "add",
                "url": "https://news.ycombinator.com/rss",
                "source_type": "rss",
                "label": "Hacker News",
            },
        )
        data = json.loads(result[0].text)
        assert "added" in data
        assert data["added"]["url"] == "https://news.ycombinator.com/rss"
        assert data["added"]["source_type"] == "rss"
        assert data["added"]["label"] == "Hacker News"
        # Source should be in config
        assert len(cfg.feeds.sources) == 1

    async def test_add_appends_to_existing_sources(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        cfg.feeds.sources = [FeedSourceConfig(url="https://existing.com/rss", source_type="rss")]
        await _handle_watch(
            config=cfg,
            arguments={
                "action": "add",
                "url": "https://new.com/rss",
                "source_type": "rss",
            },
        )
        assert len(cfg.feeds.sources) == 2

    async def test_add_default_poll_interval(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "add", "url": "https://example.com/rss", "source_type": "rss"},
        )
        data = json.loads(result[0].text)
        assert data["added"]["poll_interval_minutes"] == 60

    async def test_add_custom_poll_interval(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
                "poll_interval_minutes": 120,
            },
        )
        data = json.loads(result[0].text)
        assert data["added"]["poll_interval_minutes"] == 120

    async def test_add_custom_trust_weight(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
                "trust_weight": 0.7,
            },
        )
        data = json.loads(result[0].text)
        assert data["added"]["trust_weight"] == pytest.approx(0.7)

    async def test_add_github_source_type(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={
                "action": "add",
                "url": "org/repo",
                "source_type": "github",
            },
        )
        data = json.loads(result[0].text)
        assert data["added"]["source_type"] == "github"

    async def test_add_missing_url_returns_error(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "add", "source_type": "rss"},
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True
        assert data["code"] == "MISSING_FIELD"

    async def test_add_missing_source_type_returns_error(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "add", "url": "https://example.com/rss"},
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True
        assert data["code"] == "MISSING_FIELD"

    async def test_add_invalid_source_type_returns_error(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "slack",
            },
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True
        assert data["code"] == "INVALID_SOURCE_TYPE"

    async def test_add_trust_weight_out_of_range_returns_error(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
                "trust_weight": 2.0,
            },
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True

    async def test_add_negative_poll_interval_returns_error(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
                "poll_interval_minutes": 0,
            },
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True

    async def test_add_response_includes_note(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "add", "url": "https://example.com/rss", "source_type": "rss"},
        )
        data = json.loads(result[0].text)
        assert "note" in data
        assert "distillery.yaml" in data["note"].lower() or "persist" in data["note"].lower()


# ---------------------------------------------------------------------------
# _handle_watch: remove action
# ---------------------------------------------------------------------------


class TestHandleWatchRemove:
    async def test_remove_existing_source(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        cfg.feeds.sources = [
            FeedSourceConfig(url="https://example.com/rss", source_type="rss"),
        ]
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "remove", "url": "https://example.com/rss"},
        )
        data = json.loads(result[0].text)
        assert data["removed"] is True
        assert data["removed_url"] == "https://example.com/rss"
        assert len(cfg.feeds.sources) == 0

    async def test_remove_nonexistent_source_returns_removed_false(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "remove", "url": "https://not-registered.com/rss"},
        )
        data = json.loads(result[0].text)
        assert data["removed"] is False

    async def test_remove_only_matching_source(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        cfg.feeds.sources = [
            FeedSourceConfig(url="https://keep.com/rss", source_type="rss"),
            FeedSourceConfig(url="https://remove.com/rss", source_type="rss"),
        ]
        await _handle_watch(
            config=cfg,
            arguments={"action": "remove", "url": "https://remove.com/rss"},
        )
        assert len(cfg.feeds.sources) == 1
        assert cfg.feeds.sources[0].url == "https://keep.com/rss"

    async def test_remove_missing_url_returns_error(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "remove"},
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True
        assert data["code"] == "MISSING_FIELD"

    async def test_remove_response_includes_updated_sources(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        cfg.feeds.sources = [
            FeedSourceConfig(url="https://example.com/rss", source_type="rss"),
        ]
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "remove", "url": "https://example.com/rss"},
        )
        data = json.loads(result[0].text)
        assert "sources" in data
        assert data["sources"] == []


# ---------------------------------------------------------------------------
# _handle_watch: invalid action
# ---------------------------------------------------------------------------


class TestHandleWatchInvalidAction:
    async def test_invalid_action_returns_error(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={"action": "purge"},
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True
        assert data["code"] == "INVALID_ACTION"

    async def test_missing_action_returns_error(self) -> None:
        from distillery.mcp.server import _handle_watch

        cfg = DistilleryConfig()
        result = await _handle_watch(
            config=cfg,
            arguments={},
        )
        data = json.loads(result[0].text)
        assert data.get("error") is True
