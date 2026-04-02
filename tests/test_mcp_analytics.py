"""Tests for the Distillery MCP analytics tool handlers (T04.2).

Tests cover all 6 analytics handlers via direct handler calls with a mock
store, deterministic embedding provider, and minimal config:

  - _handle_tag_tree
  - _handle_type_schemas
  - _handle_metrics
  - _handle_quality
  - _handle_stale
  - _handle_interests

The test harness exercises the handlers directly without requiring a running
transport.  All handlers are async functions that accept a store object and
an arguments dict -- this is the natural unit-test seam.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from distillery.config import DefaultsConfig, DistilleryConfig, StorageConfig
from distillery.mcp.tools.analytics import (
    _handle_interests,
    _handle_metrics,
    _handle_quality,
    _handle_stale,
    _handle_tag_tree,
    _handle_type_schemas,
)
from distillery.models import EntryStatus, EntryType
from distillery.store.duckdb import DuckDBStore
from tests.conftest import DeterministicEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider(deterministic_embedding_provider):
    """Alias for deterministic_embedding_provider."""
    return deterministic_embedding_provider


@pytest.fixture
async def store(embedding_provider) -> DuckDBStore:  # type: ignore[return]
    """Initialised in-memory DuckDBStore using the deterministic provider."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    """Minimal config for analytics handlers."""
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        defaults=DefaultsConfig(stale_days=30),
    )


# ---------------------------------------------------------------------------
# _handle_tag_tree tests
# ---------------------------------------------------------------------------


class TestTagTree:
    async def test_tag_tree_empty_store(self, store: DuckDBStore) -> None:
        response = await _handle_tag_tree(store, {})
        data = parse_mcp_response(response)
        assert "tree" in data
        assert data["tree"]["count"] == 0
        assert data["tree"]["children"] == {}
        assert data["prefix"] is None

    async def test_tag_tree_single_tag(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Single tag", tags=["python"])
        await store.store(entry)
        response = await _handle_tag_tree(store, {})
        data = parse_mcp_response(response)
        tree = data["tree"]
        assert "python" in tree["children"]
        assert tree["children"]["python"]["count"] == 1

    async def test_tag_tree_nested_tags(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Nested tag", tags=["lang/python", "lang/rust"])
        await store.store(entry)
        response = await _handle_tag_tree(store, {})
        data = parse_mcp_response(response)
        tree = data["tree"]
        assert "lang" in tree["children"]
        lang_node = tree["children"]["lang"]
        assert "python" in lang_node["children"]
        assert "rust" in lang_node["children"]

    async def test_tag_tree_with_prefix(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Prefixed", tags=["lang/python", "lang/rust", "topic/ml"])
        await store.store(entry)
        response = await _handle_tag_tree(store, {"prefix": "lang"})
        data = parse_mcp_response(response)
        assert data["prefix"] == "lang"
        tree = data["tree"]
        # Under the prefix, we should see python and rust (not topic/ml)
        assert "python" in tree["children"]
        assert "rust" in tree["children"]
        assert "topic" not in tree["children"]

    async def test_tag_tree_counts_distinct_entries(self, store: DuckDBStore) -> None:
        """Two entries sharing the same tag should each count once."""
        await store.store(make_entry(content="Entry A", tags=["shared"]))
        await store.store(make_entry(content="Entry B", tags=["shared"]))
        response = await _handle_tag_tree(store, {})
        data = parse_mcp_response(response)
        assert data["tree"]["children"]["shared"]["count"] == 2

    async def test_tag_tree_excludes_archived(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Archived", tags=["old"], status=EntryStatus.ARCHIVED)
        await store.store(entry)
        response = await _handle_tag_tree(store, {})
        data = parse_mcp_response(response)
        assert data["tree"]["children"] == {}


# ---------------------------------------------------------------------------
# _handle_type_schemas tests
# ---------------------------------------------------------------------------


class TestTypeSchemas:
    async def test_type_schemas_returns_all_types(self) -> None:
        response = await _handle_type_schemas()
        data = parse_mcp_response(response)
        assert "schemas" in data
        schemas = data["schemas"]
        # Every EntryType should be present
        for et in EntryType:
            assert et.value in schemas, f"Missing schema for {et.value}"

    async def test_type_schemas_structured_type_has_required(self) -> None:
        """The 'person' type has a structured schema with required fields."""
        response = await _handle_type_schemas()
        data = parse_mcp_response(response)
        person = data["schemas"]["person"]
        assert "required" in person
        assert "optional" in person
        # 'person' requires 'expertise'
        assert "expertise" in person["required"]

    async def test_type_schemas_legacy_type_has_empty_dicts(self) -> None:
        """Legacy types without structured schemas have empty required/optional."""
        response = await _handle_type_schemas()
        data = parse_mcp_response(response)
        # 'inbox' is a legacy type with no schema
        inbox = data["schemas"]["inbox"]
        assert inbox["required"] == {}
        assert inbox["optional"] == {}


# ---------------------------------------------------------------------------
# _handle_metrics tests
# ---------------------------------------------------------------------------


class TestMetrics:
    async def test_metrics_empty_store(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        response = await _handle_metrics(store, config, embedding_provider, {})
        data = parse_mcp_response(response)
        assert "entries" in data
        assert "activity" in data
        assert "search" in data
        assert "quality" in data
        assert "staleness" in data
        assert "storage" in data
        assert data["entries"]["total"] == 0

    async def test_metrics_with_entries(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        await store.store(make_entry(content="Metrics entry", entry_type=EntryType.IDEA))
        response = await _handle_metrics(store, config, embedding_provider, {})
        data = parse_mcp_response(response)
        assert data["entries"]["total"] == 1
        assert "idea" in data["entries"]["by_type"]

    async def test_metrics_custom_period_days(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        await store.store(make_entry(content="Period test"))
        response = await _handle_metrics(
            store, config, embedding_provider, {"period_days": 7}
        )
        data = parse_mcp_response(response)
        # Custom period key should appear in activity
        assert "created_7d" in data["activity"]
        assert "updated_7d" in data["activity"]

    async def test_metrics_invalid_period_days_type(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        response = await _handle_metrics(
            store, config, embedding_provider, {"period_days": "not-int"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_metrics_period_days_zero(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        response = await _handle_metrics(
            store, config, embedding_provider, {"period_days": 0}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_metrics_storage_section(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        response = await _handle_metrics(store, config, embedding_provider, {})
        data = parse_mcp_response(response)
        storage = data["storage"]
        assert storage["embedding_model"] == "deterministic-4d"
        assert storage["embedding_dimensions"] == 4

    async def test_metrics_by_status(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        await store.store(make_entry(content="Active entry"))
        await store.store(make_entry(content="Archived entry", status=EntryStatus.ARCHIVED))
        response = await _handle_metrics(store, config, embedding_provider, {})
        data = parse_mcp_response(response)
        # Active entries total should be 1 (archived excluded)
        assert data["entries"]["total"] == 1
        # But by_status should show both
        assert "active" in data["entries"]["by_status"]
        assert "archived" in data["entries"]["by_status"]


# ---------------------------------------------------------------------------
# _handle_quality tests
# ---------------------------------------------------------------------------


class TestQuality:
    async def test_quality_empty_store(self, store: DuckDBStore) -> None:
        response = await _handle_quality(store, {})
        data = parse_mcp_response(response)
        assert data["total_searches"] == 0
        assert data["total_feedback"] == 0
        assert data["positive_rate"] == 0.0
        assert data["avg_result_count"] == 0.0
        assert data["per_type_breakdown"] == {}

    async def test_quality_with_entry_type_filter(self, store: DuckDBStore) -> None:
        response = await _handle_quality(store, {"entry_type": "idea"})
        data = parse_mcp_response(response)
        # Should still succeed with empty tables
        assert "total_searches" in data
        assert "per_type_breakdown" in data

    async def test_quality_no_error_on_missing_tables(self, store: DuckDBStore) -> None:
        """Quality should return zeroes when search_log/feedback_log don't exist."""
        response = await _handle_quality(store, {})
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["total_searches"] == 0


# ---------------------------------------------------------------------------
# _handle_stale tests
# ---------------------------------------------------------------------------


class TestStale:
    async def test_stale_empty_store(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {})
        data = parse_mcp_response(response)
        assert data["stale_count"] == 0
        assert data["entries"] == []
        assert data["days_threshold"] == 30  # default from config

    async def test_stale_with_old_entry(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """An entry updated long ago should appear in stale results."""
        entry = make_entry(content="Old stale entry")
        await store.store(entry)
        # Manually set updated_at to be old
        old_date = datetime.now(UTC) - timedelta(days=60)
        store.connection.execute(
            "UPDATE entries SET updated_at = ? WHERE id = ?",
            [old_date, entry.id],
        )
        response = await _handle_stale(store, config, {"days": 30})
        data = parse_mcp_response(response)
        assert data["stale_count"] >= 1
        assert any(e["id"] == entry.id for e in data["entries"])

    async def test_stale_with_recent_entry(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """A recently updated entry should NOT appear in stale results."""
        entry = make_entry(content="Fresh entry")
        await store.store(entry)
        response = await _handle_stale(store, config, {"days": 30})
        data = parse_mcp_response(response)
        assert data["stale_count"] == 0

    async def test_stale_custom_days(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"days": 7})
        data = parse_mcp_response(response)
        assert data["days_threshold"] == 7

    async def test_stale_invalid_days_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"days": "not-int"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_stale_days_zero(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"days": 0})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_stale_invalid_limit_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"limit": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_stale_limit_zero(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"limit": 0})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_stale_respects_limit(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        old_date = datetime.now(UTC) - timedelta(days=60)
        for i in range(5):
            entry = make_entry(content=f"Old entry {i}")
            await store.store(entry)
            store.connection.execute(
                "UPDATE entries SET updated_at = ? WHERE id = ?",
                [old_date, entry.id],
            )
        response = await _handle_stale(store, config, {"days": 30, "limit": 2})
        data = parse_mcp_response(response)
        assert len(data["entries"]) <= 2

    async def test_stale_filters_by_entry_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        old_date = datetime.now(UTC) - timedelta(days=60)
        idea = make_entry(content="Old idea", entry_type=EntryType.IDEA)
        inbox = make_entry(content="Old inbox", entry_type=EntryType.INBOX)
        await store.store(idea)
        await store.store(inbox)
        store.connection.execute(
            "UPDATE entries SET updated_at = ? WHERE id IN (?, ?)",
            [old_date, idea.id, inbox.id],
        )
        response = await _handle_stale(
            store, config, {"days": 30, "entry_type": "idea"}
        )
        data = parse_mcp_response(response)
        for e in data["entries"]:
            assert e["entry_type"] == "idea"

    async def test_stale_entry_fields(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Stale entries should have the expected summary fields."""
        entry = make_entry(
            content="Stale content preview test",
            entry_type=EntryType.SESSION,
            author="alice",
            project="my-proj",
        )
        await store.store(entry)
        old_date = datetime.now(UTC) - timedelta(days=60)
        store.connection.execute(
            "UPDATE entries SET updated_at = ? WHERE id = ?",
            [old_date, entry.id],
        )
        response = await _handle_stale(store, config, {"days": 30})
        data = parse_mcp_response(response)
        assert data["stale_count"] == 1
        stale = data["entries"][0]
        assert stale["id"] == entry.id
        assert "content_preview" in stale
        assert stale["entry_type"] == "session"
        assert stale["author"] == "alice"
        assert stale["project"] == "my-proj"
        assert "last_accessed" in stale
        assert "days_since_access" in stale

    async def test_stale_invalid_entry_type_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"entry_type": 123})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# _handle_interests tests
# ---------------------------------------------------------------------------


class TestInterests:
    async def test_interests_success(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Interests handler should return profile data on success."""
        mock_profile = self._make_mock_profile()

        with patch(
            "distillery.feeds.interests.InterestExtractor"
        ) as mock_extractor_cls:
            instance = mock_extractor_cls.return_value
            instance.extract = AsyncMock(return_value=mock_profile)

            response = await _handle_interests(store, config, {})
            data = parse_mcp_response(response)

        assert "error" not in data
        assert "top_tags" in data
        assert "bookmark_domains" in data
        assert "tracked_repos" in data
        assert "expertise_areas" in data
        assert "entry_count" in data
        assert data["entry_count"] == 42

    async def test_interests_custom_recency_days(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        mock_profile = self._make_mock_profile()

        with patch(
            "distillery.feeds.interests.InterestExtractor"
        ) as mock_extractor_cls:
            instance = mock_extractor_cls.return_value
            instance.extract = AsyncMock(return_value=mock_profile)

            response = await _handle_interests(
                store, config, {"recency_days": 14}
            )
            data = parse_mcp_response(response)

        assert "error" not in data
        mock_extractor_cls.assert_called_once_with(
            store=store, recency_days=14, top_n=20
        )

    async def test_interests_custom_top_n(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        mock_profile = self._make_mock_profile()

        with patch(
            "distillery.feeds.interests.InterestExtractor"
        ) as mock_extractor_cls:
            instance = mock_extractor_cls.return_value
            instance.extract = AsyncMock(return_value=mock_profile)

            response = await _handle_interests(store, config, {"top_n": 5})
            data = parse_mcp_response(response)

        assert "error" not in data
        mock_extractor_cls.assert_called_once_with(
            store=store, recency_days=90, top_n=5
        )

    async def test_interests_invalid_recency_days(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(
            store, config, {"recency_days": "bad"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_FIELD"

    async def test_interests_negative_recency_days(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(
            store, config, {"recency_days": -1}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_FIELD"

    async def test_interests_invalid_top_n(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(store, config, {"top_n": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_FIELD"

    async def test_interests_zero_top_n(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(store, config, {"top_n": 0})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_FIELD"

    async def test_interests_extraction_error(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        with patch(
            "distillery.feeds.interests.InterestExtractor"
        ) as mock_extractor_cls:
            instance = mock_extractor_cls.return_value
            instance.extract = AsyncMock(
                side_effect=RuntimeError("extraction boom")
            )

            response = await _handle_interests(store, config, {})
            data = parse_mcp_response(response)

        assert data["error"] is True
        assert data["code"] == "EXTRACTION_ERROR"

    @staticmethod
    def _make_mock_profile():
        """Create a mock InterestProfile for testing."""
        from distillery.feeds.interests import InterestProfile

        return InterestProfile(
            top_tags=[("python", 1.0), ("ml", 0.8)],
            bookmark_domains=["github.com", "arxiv.org"],
            tracked_repos=["owner/repo"],
            expertise_areas=["machine learning"],
            watched_sources=["https://example.com/feed"],
            suggestion_context="User is interested in ML and Python.",
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            entry_count=42,
        )
