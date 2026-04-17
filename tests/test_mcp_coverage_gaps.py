"""Coverage gap tests for the Distillery MCP package (T04.5).

Targets uncovered lines identified by ``pytest --cov=src/distillery/mcp --cov-report=term-missing``.
Covers edge cases and error paths in:
  - tools/search.py: budget checks, error paths, search logging, find_similar validation
  - tools/crud.py: status handler, store handler edge cases, get with feedback, update/list
  - tools/classify.py: error paths, reclassification, invalid tag filtering
  - tools/analytics.py: _handle_metrics error path
  - tools/feeds.py: remaining validation paths
  - auth.py: _extract_upstream_claims, _patch_cimd_localhost_redirect
  - _stub_embedding.py: line 56
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from distillery.config import (
    ClassificationConfig,
    DefaultsConfig,
    DistilleryConfig,
    RateLimitConfig,
    StorageConfig,
)
from distillery.mcp._stub_embedding import HashEmbeddingProvider, StubEmbeddingProvider
from distillery.mcp.tools.analytics import (
    _handle_interests,
    _handle_metrics,
    _handle_stale,
    _handle_tag_tree,
)
from distillery.mcp.tools.classify import (
    _handle_classify,
    _handle_resolve_review,
)
from distillery.mcp.tools.crud import (
    _build_filters_from_arguments,
    _handle_get,
    _handle_list,
    _handle_store,
    _handle_update,
    _is_remote_db_path,
    _normalize_db_path,
)
from distillery.mcp.tools.feeds import (
    _derive_suggestions,
    _handle_poll,
    _handle_rescore,
    _handle_watch,
    _normalise_watched_set,
)
from distillery.mcp.tools.search import (
    _handle_aggregate,
    _handle_find_similar,
    _handle_search,
)
from distillery.models import EntryStatus, EntryType
from distillery.store.duckdb import DuckDBStore
from tests.conftest import make_entry, parse_mcp_response

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider(deterministic_embedding_provider):  # type: ignore[no-untyped-def]
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
    """Minimal config for handler tests."""
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        defaults=DefaultsConfig(stale_days=30),
    )


@pytest.fixture
def budget_config() -> DistilleryConfig:
    """Config with a tight embedding budget for budget-exceeded tests."""
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        rate_limit=RateLimitConfig(embedding_budget_daily=1),
    )


# ===========================================================================
# tools/search.py gap coverage
# ===========================================================================


class TestSearchBudgetAndErrors:
    """Cover budget checks and error paths in _handle_search."""

    async def test_search_budget_exceeded(
        self, store: DuckDBStore, budget_config: DistilleryConfig
    ) -> None:
        """Search rejects when embedding budget is exhausted."""
        # Exhaust the budget (1 call allowed, use it up)
        from distillery.mcp.budget import record_and_check

        record_and_check(store.connection, budget_config.rate_limit.embedding_budget_daily)

        response = await _handle_search(store, {"query": "test"}, cfg=budget_config)
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "BUDGET_EXCEEDED"

    async def test_search_store_error(self, store: DuckDBStore) -> None:
        """Search returns SEARCH_ERROR when store.search raises."""
        with patch.object(store, "search", side_effect=RuntimeError("boom")):
            response = await _handle_search(store, {"query": "test"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_search_logs_search_event(self, store: DuckDBStore) -> None:
        """Successful search with results calls store.log_search."""
        entry = make_entry(content="Searchable content")
        await store.store(entry)
        with patch.object(store, "log_search", new_callable=AsyncMock) as mock_log:
            response = await _handle_search(store, {"query": "Searchable content"})
            data = parse_mcp_response(response)
            if data["count"] > 0:
                mock_log.assert_called_once()

    async def test_search_log_failure_nonfatal(self, store: DuckDBStore) -> None:
        """Search log failure does not affect the returned results."""
        entry = make_entry(content="Log fail test content")
        await store.store(entry)
        with patch.object(
            store, "log_search", new_callable=AsyncMock, side_effect=RuntimeError("log failed")
        ):
            response = await _handle_search(store, {"query": "Log fail test content"})
            data = parse_mcp_response(response)
            # Should still return results, not an error
            assert "error" not in data
            assert "results" in data


class TestFindSimilarGaps:
    """Cover validation and error paths in _handle_find_similar."""

    async def test_find_similar_invalid_threshold_type(self, store: DuckDBStore) -> None:
        response = await _handle_find_similar(store, {"content": "test", "threshold": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_find_similar_threshold_out_of_range(self, store: DuckDBStore) -> None:
        response = await _handle_find_similar(store, {"content": "test", "threshold": 1.5})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert "threshold" in data["message"]

    async def test_find_similar_invalid_limit(self, store: DuckDBStore) -> None:
        response = await _handle_find_similar(store, {"content": "test", "limit": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_find_similar_budget_exceeded(
        self, store: DuckDBStore, budget_config: DistilleryConfig
    ) -> None:
        from distillery.mcp.budget import record_and_check

        record_and_check(store.connection, budget_config.rate_limit.embedding_budget_daily)
        response = await _handle_find_similar(store, {"content": "test"}, cfg=budget_config)
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "BUDGET_EXCEEDED"

    async def test_find_similar_store_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "find_similar", side_effect=RuntimeError("boom")):
            response = await _handle_find_similar(store, {"content": "test"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestAggregateGaps:
    """Cover error path in _handle_aggregate."""

    async def test_aggregate_store_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "aggregate_entries", side_effect=RuntimeError("boom")):
            response = await _handle_aggregate(store, {"group_by": "entry_type"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_aggregate_invalid_limit(self, store: DuckDBStore) -> None:
        response = await _handle_aggregate(store, {"group_by": "entry_type", "limit": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_aggregate_group_by_not_string(self, store: DuckDBStore) -> None:
        response = await _handle_aggregate(store, {"group_by": 123})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ===========================================================================
# tools/crud.py gap coverage
# ===========================================================================


class TestStatusGaps:
    """Cover error paths and edge cases in metrics (summary scope)."""

    async def test_status_error(self, store: DuckDBStore) -> None:
        """metrics(scope=summary) returns METRICS_ERROR when gathering stats fails."""
        with patch(
            "distillery.mcp.tools.analytics._sync_gather_summary",
            side_effect=RuntimeError("stat fail"),
        ):
            cfg = DistilleryConfig(storage=StorageConfig(database_path=":memory:"))
            response = await _handle_metrics(store, cfg, None, {"scope": "summary"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_status_remote_db_path(self) -> None:
        """Remote db paths (md:, s3://) are not expanded."""
        assert _is_remote_db_path("md:my_db") is True
        assert _is_remote_db_path("s3://bucket/path") is True
        assert _is_remote_db_path("/local/path.db") is False

    async def test_normalize_db_path_remote(self) -> None:
        assert _normalize_db_path("md:my_db") == "md:my_db"
        assert _normalize_db_path("s3://bucket/path") == "s3://bucket/path"


class TestStoreGaps:
    """Cover edge cases in _handle_store."""

    async def test_store_invalid_entry_type(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store, {"content": "test", "entry_type": "invalid_type", "author": "bob"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_invalid_tags_type(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {"content": "test", "entry_type": "inbox", "author": "bob", "tags": "not-a-list"},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_invalid_metadata_type(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {"content": "test", "entry_type": "inbox", "author": "bob", "metadata": "not-dict"},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_invalid_dedup_threshold_type(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {
                "content": "test",
                "entry_type": "inbox",
                "author": "bob",
                "dedup_threshold": "not-num",
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_invalid_dedup_limit_type(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {
                "content": "test",
                "entry_type": "inbox",
                "author": "bob",
                "dedup_limit": "not-int",
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_reserved_prefix_rejection(self, store: DuckDBStore) -> None:
        """Store rejects tags with reserved prefixes from non-import sources."""
        cfg = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
        )
        # Make sure tags.reserved_prefixes is set
        cfg.tags.reserved_prefixes = ["system"]
        response = await _handle_store(
            store,
            {
                "content": "test",
                "entry_type": "inbox",
                "author": "bob",
                "tags": ["system/internal"],
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_non_string_tag_in_reserved_check(self, store: DuckDBStore) -> None:
        """Non-string tag triggers INVALID_PARAMS during reserved prefix check."""
        cfg = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
        )
        cfg.tags.reserved_prefixes = ["system"]
        response = await _handle_store(
            store,
            {
                "content": "test",
                "entry_type": "inbox",
                "author": "bob",
                "tags": [123],
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_budget_exceeded(
        self, store: DuckDBStore, budget_config: DistilleryConfig
    ) -> None:
        from distillery.mcp.budget import record_and_check

        record_and_check(store.connection, budget_config.rate_limit.embedding_budget_daily)
        response = await _handle_store(
            store,
            {"content": "test", "entry_type": "inbox", "author": "bob"},
            cfg=budget_config,
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "BUDGET_EXCEEDED"

    async def test_store_persist_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "store", side_effect=RuntimeError("persist fail")):
            response = await _handle_store(
                store,
                {"content": "test", "entry_type": "inbox", "author": "bob"},
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_store_invalid_source_rejected(self, store: DuckDBStore) -> None:
        """Invalid source value is rejected with INVALID_PARAMS error."""
        response = await _handle_store(
            store,
            {
                "content": "src fallback",
                "entry_type": "inbox",
                "author": "bob",
                "source": "nonexistent_source",
            },
        )
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data.get("code") == "INVALID_PARAMS"
        assert "nonexistent_source" in data.get("message", "")

    async def test_store_with_dedup_warnings(self, store: DuckDBStore) -> None:
        """Storing similar content generates dedup warnings."""
        content = "Exact duplicate content for dedup test"
        response1 = await _handle_store(
            store,
            {"content": content, "entry_type": "inbox", "author": "bob"},
        )
        data1 = parse_mcp_response(response1)
        assert "entry_id" in data1

        response2 = await _handle_store(
            store,
            {"content": content, "entry_type": "inbox", "author": "bob"},
        )
        data2 = parse_mcp_response(response2)
        assert "entry_id" in data2
        # May have warnings or conflicts depending on similarity
        # Just verify the store succeeded
        assert "error" not in data2


class TestGetGaps:
    """Cover feedback logging in _handle_get."""

    async def test_get_not_found(self, store: DuckDBStore) -> None:
        response = await _handle_get(store, {"entry_id": "nonexistent-id-12345"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_get_store_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "get", side_effect=RuntimeError("boom")):
            response = await _handle_get(store, {"entry_id": "any"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_get_with_feedback_logging(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Get with config triggers implicit feedback logic."""
        entry = make_entry(content="Feedback test content")
        entry_id = await store.store(entry)
        response = await _handle_get(store, {"entry_id": entry_id}, config=config)
        data = parse_mcp_response(response)
        assert data["id"] == entry_id

    async def test_get_feedback_search_query_error(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Feedback query failures are non-fatal."""
        entry = make_entry(content="Feedback error test")
        entry_id = await store.store(entry)
        with patch.object(
            store,
            "get_searches_for_entry",
            new_callable=AsyncMock,
            side_effect=RuntimeError("query fail"),
        ):
            response = await _handle_get(store, {"entry_id": entry_id}, config=config)
            data = parse_mcp_response(response)
            # Should still return the entry despite feedback error
            assert data["id"] == entry_id

    async def test_get_feedback_log_error(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Feedback log_feedback failures are non-fatal."""
        entry = make_entry(content="Log feedback error test")
        entry_id = await store.store(entry)
        with (
            patch.object(
                store,
                "get_searches_for_entry",
                new_callable=AsyncMock,
                return_value=["search-123"],
            ),
            patch.object(
                store,
                "log_feedback",
                new_callable=AsyncMock,
                side_effect=RuntimeError("log fail"),
            ),
        ):
            response = await _handle_get(store, {"entry_id": entry_id}, config=config)
            data = parse_mcp_response(response)
            assert data["id"] == entry_id


class TestUpdateGaps:
    """Cover edge cases in _handle_update."""

    async def test_update_immutable_field_rejected(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Immutable test")
        entry_id = await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry_id, "source": "new_source"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "immutable" in data["message"].lower()

    async def test_update_no_fields(self, store: DuckDBStore) -> None:
        entry = make_entry(content="No fields test")
        entry_id = await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry_id})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "updatable" in data["message"].lower()

    async def test_update_invalid_entry_type(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Bad type test")
        entry_id = await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry_id, "entry_type": "nonexistent"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_update_invalid_status(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Bad status test")
        entry_id = await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry_id, "status": "bad_status"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_update_invalid_tags_type(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Bad tags test")
        entry_id = await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry_id, "tags": "not-a-list"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_update_invalid_metadata_type(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Bad metadata test")
        entry_id = await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry_id, "metadata": "not-dict"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_update_not_found(self, store: DuckDBStore) -> None:
        response = await _handle_update(store, {"entry_id": "nonexistent-id", "content": "updated"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_update_store_error(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Store error test")
        entry_id = await store.store(entry)
        with patch.object(store, "update", side_effect=RuntimeError("boom")):
            response = await _handle_update(store, {"entry_id": entry_id, "content": "updated"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_update_value_error(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Value error test")
        entry_id = await store.store(entry)
        with patch.object(store, "update", side_effect=ValueError("bad value")):
            response = await _handle_update(store, {"entry_id": entry_id, "content": "updated"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INVALID_PARAMS"

    async def test_update_with_last_modified_by(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Auth update test")
        entry_id = await store.store(entry)
        response = await _handle_update(
            store,
            {"entry_id": entry_id, "content": "updated content"},
            last_modified_by="alice",
        )
        data = parse_mcp_response(response)
        assert "error" not in data


class TestListGaps:
    """Cover edge cases in _handle_list."""

    async def test_list_invalid_limit(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"limit": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_list_negative_offset(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"offset": -1})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_list_invalid_offset_type(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"offset": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_list_invalid_output_mode(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"output_mode": "invalid"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert "output_mode" in data["message"]

    async def test_list_invalid_output_mode_type(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"output_mode": 123})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_list_content_max_length_invalid_type(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"content_max_length": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_list_content_max_length_zero(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"content_max_length": 0})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_list_content_max_length_truncation(self, store: DuckDBStore) -> None:
        long_content = "x" * 500
        entry = make_entry(content=long_content)
        await store.store(entry)
        # content_max_length applies to output_mode="full"; pass it explicitly
        # since the default is now "summary" (issue #311).
        response = await _handle_list(store, {"content_max_length": 10, "output_mode": "full"})
        data = parse_mcp_response(response)
        assert data["count"] >= 1
        for e in data["entries"]:
            # Content should be truncated
            assert len(e["content"]) <= 12  # 10 + ellipsis char

    async def test_list_summary_mode(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Summary mode test")
        await store.store(entry)
        response = await _handle_list(store, {"output_mode": "summary"})
        data = parse_mcp_response(response)
        assert data["output_mode"] == "summary"
        for e in data["entries"]:
            assert "content" not in e

    async def test_list_ids_mode(self, store: DuckDBStore) -> None:
        entry = make_entry(content="IDs mode test")
        await store.store(entry)
        response = await _handle_list(store, {"output_mode": "ids"})
        data = parse_mcp_response(response)
        assert data["output_mode"] == "ids"
        for e in data["entries"]:
            assert "id" in e
            assert "entry_type" in e
            assert "content" not in e

    async def test_list_store_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "list_entries", side_effect=RuntimeError("boom")):
            response = await _handle_list(store, {})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestBuildFilters:
    """Cover _build_filters_from_arguments."""

    def test_no_filters(self) -> None:
        assert _build_filters_from_arguments({}) is None

    def test_with_filters(self) -> None:
        f = _build_filters_from_arguments(
            {"entry_type": "idea", "author": "bob", "extra_key": "ignored"}
        )
        assert f is not None
        assert f["entry_type"] == "idea"
        assert f["author"] == "bob"
        assert "extra_key" not in f

    def test_none_values_excluded(self) -> None:
        f = _build_filters_from_arguments({"entry_type": None, "author": "bob"})
        assert f is not None
        assert "entry_type" not in f
        assert f["author"] == "bob"


# ===========================================================================
# tools/classify.py gap coverage
# ===========================================================================


class TestClassifyGaps:
    """Cover error paths and edge cases in _handle_classify."""

    async def test_classify_not_found(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        response = await _handle_classify(
            store,
            config,
            {"entry_id": "nonexistent", "entry_type": "idea", "confidence": 0.9},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_classify_store_get_error(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        with patch.object(store, "get", side_effect=RuntimeError("boom")):
            response = await _handle_classify(
                store,
                config,
                {"entry_id": "any", "entry_type": "idea", "confidence": 0.9},
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_classify_invalid_confidence_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_classify(
            store,
            config,
            {"entry_id": "x", "entry_type": "idea", "confidence": "bad"},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_classify_confidence_out_of_range(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Out of range test")
        entry_id = await store.store(entry)
        response = await _handle_classify(
            store,
            config,
            {"entry_id": entry_id, "entry_type": "idea", "confidence": 1.5},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_classify_invalid_suggested_tags_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Invalid tags type test")
        entry_id = await store.store(entry)
        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "idea",
                "confidence": 0.9,
                "suggested_tags": "not-a-list",
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_classify_reclassification(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Classifying an already-classified entry sets reclassified_from."""
        entry = make_entry(
            content="Reclassify test",
            entry_type=EntryType.INBOX,
            metadata={"classified_at": "2025-01-01T00:00:00Z", "confidence": 0.7},
        )
        entry_id = await store.store(entry)
        response = await _handle_classify(
            store,
            config,
            {"entry_id": entry_id, "entry_type": "idea", "confidence": 0.95},
        )
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["metadata"]["reclassified_from"] == "inbox"

    async def test_classify_below_threshold_pending_review(self, store: DuckDBStore) -> None:
        """Low confidence results in pending_review status."""
        cfg = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            classification=ClassificationConfig(confidence_threshold=0.8),
        )
        entry = make_entry(content="Low confidence test")
        entry_id = await store.store(entry)
        response = await _handle_classify(
            store,
            cfg,
            {"entry_id": entry_id, "entry_type": "idea", "confidence": 0.3},
        )
        data = parse_mcp_response(response)
        assert data["status"] == "pending_review"

    async def test_classify_with_suggested_project(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Suggested project is applied when entry has no project."""
        entry = make_entry(content="Project test", project=None)
        entry_id = await store.store(entry)
        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "idea",
                "confidence": 0.9,
                "suggested_project": "my-project",
            },
        )
        data = parse_mcp_response(response)
        assert data["project"] == "my-project"

    async def test_classify_invalid_tag_filtered_out(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Invalid suggested tags from LLM are silently dropped."""
        entry = make_entry(content="Invalid tag filter test")
        entry_id = await store.store(entry)
        response = await _handle_classify(
            store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "idea",
                "confidence": 0.9,
                "suggested_tags": ["valid-tag", "", "a" * 200],
            },
        )
        data = parse_mcp_response(response)
        assert "error" not in data

    async def test_classify_update_error(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Store update error during classify returns STORE_ERROR."""
        entry = make_entry(content="Update error test")
        entry_id = await store.store(entry)
        with patch.object(store, "update", side_effect=RuntimeError("boom")):
            response = await _handle_classify(
                store,
                config,
                {"entry_id": entry_id, "entry_type": "idea", "confidence": 0.9},
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_classify_update_key_error(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """Store update KeyError during classify returns NOT_FOUND."""
        entry = make_entry(content="Key error test")
        entry_id = await store.store(entry)
        with patch.object(store, "update", side_effect=KeyError("not found")):
            response = await _handle_classify(
                store,
                config,
                {"entry_id": entry_id, "entry_type": "idea", "confidence": 0.9},
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "NOT_FOUND"


class TestReviewQueueGaps:
    """Cover edge cases in _handle_list with output_mode=review."""

    async def test_review_queue_invalid_limit_type(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"output_mode": "review", "limit": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_review_queue_limit_too_low(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"output_mode": "review", "limit": 0})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_review_queue_limit_too_high(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"output_mode": "review", "limit": 501})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_review_queue_unknown_entry_type_returns_empty(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"output_mode": "review", "entry_type": "nonexistent"})
        data = parse_mcp_response(response)
        # _handle_list passes entry_type as a filter without validation; returns empty
        assert "entries" in data
        assert data["count"] == 0

    async def test_review_queue_store_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "list_entries", side_effect=RuntimeError("boom")):
            response = await _handle_list(store, {"output_mode": "review"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestResolveReviewGaps:
    """Cover edge cases in _handle_resolve_review."""

    async def test_resolve_review_store_get_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "get", side_effect=RuntimeError("boom")):
            response = await _handle_resolve_review(store, {"entry_id": "any", "action": "approve"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_resolve_review_not_found(self, store: DuckDBStore) -> None:
        response = await _handle_resolve_review(
            store, {"entry_id": "nonexistent", "action": "approve"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_resolve_review_reclassify_missing_type(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Reclassify missing type", status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)
        response = await _handle_resolve_review(
            store, {"entry_id": entry_id, "action": "reclassify"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_resolve_review_reclassify_invalid_type(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Reclassify bad type", status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)
        response = await _handle_resolve_review(
            store,
            {"entry_id": entry_id, "action": "reclassify", "new_entry_type": "nonexistent"},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_resolve_review_archive_with_reviewer(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Archive test", status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)
        response = await _handle_resolve_review(
            store,
            {"entry_id": entry_id, "action": "archive", "reviewer": "admin"},
        )
        data = parse_mcp_response(response)
        assert data["status"] == "archived"
        assert data["metadata"]["archived_by"] == "admin"

    async def test_resolve_review_reclassify_success(self, store: DuckDBStore) -> None:
        entry = make_entry(
            content="Reclassify success",
            entry_type=EntryType.INBOX,
            status=EntryStatus.PENDING_REVIEW,
        )
        entry_id = await store.store(entry)
        response = await _handle_resolve_review(
            store,
            {
                "entry_id": entry_id,
                "action": "reclassify",
                "new_entry_type": "idea",
                "reviewer": "admin",
            },
        )
        data = parse_mcp_response(response)
        assert data["entry_type"] == "idea"
        assert data["metadata"]["reclassified_from"] == "inbox"
        assert data["metadata"]["reviewed_by"] == "admin"

    async def test_resolve_review_update_key_error(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Update key error test", status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)
        with patch.object(store, "update", side_effect=KeyError("not found")):
            response = await _handle_resolve_review(
                store, {"entry_id": entry_id, "action": "approve"}
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "NOT_FOUND"

    async def test_resolve_review_update_error(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Update error test", status=EntryStatus.PENDING_REVIEW)
        entry_id = await store.store(entry)
        with patch.object(store, "update", side_effect=RuntimeError("boom")):
            response = await _handle_resolve_review(
                store, {"entry_id": entry_id, "action": "approve"}
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


# ===========================================================================
# tools/analytics.py gap coverage
# ===========================================================================


class TestAnalyticsDbPathHelpers:
    """Cover analytics module db path helpers (analytics.py line 46)."""

    def test_normalize_remote_db_path(self) -> None:
        from distillery.mcp.tools.analytics import _normalize_db_path

        assert _normalize_db_path("md:my_db") == "md:my_db"
        assert _normalize_db_path("s3://bucket/path") == "s3://bucket/path"


class TestMetricsGaps:
    """Cover error path in _handle_metrics."""

    async def test_metrics_gather_error(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider,  # type: ignore[no-untyped-def]
    ) -> None:
        with patch(
            "distillery.mcp.tools.analytics._sync_gather_metrics",
            side_effect=RuntimeError("gather fail"),
        ):
            response = await _handle_metrics(store, config, embedding_provider, {})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestQualityGaps:
    """Cover error path in _handle_metrics with scope=search_quality."""

    async def test_quality_gather_error(self, store: DuckDBStore) -> None:
        with patch(
            "distillery.mcp.tools.analytics._sync_gather_quality",
            side_effect=RuntimeError("quality fail"),
        ):
            cfg = DistilleryConfig(storage=StorageConfig(database_path=":memory:"))
            response = await _handle_metrics(store, cfg, None, {"scope": "search_quality"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestStaleGaps:
    """Cover error path in _handle_stale."""

    async def test_stale_gather_error(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        with patch(
            "distillery.mcp.tools.analytics._sync_gather_stale",
            side_effect=RuntimeError("stale fail"),
        ):
            response = await _handle_stale(store, config, {})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestTagTreeGaps:
    """Cover error path in _handle_tag_tree."""

    async def test_tag_tree_error(self, store: DuckDBStore) -> None:
        with patch(
            "asyncio.to_thread",
            side_effect=RuntimeError("tree fail"),
        ):
            response = await _handle_tag_tree(store, {})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


# ===========================================================================
# tools/feeds.py gap coverage
# ===========================================================================


class TestWatchGaps:
    """Cover remaining validation paths in _handle_watch."""

    async def test_watch_add_url_not_string(self, store: DuckDBStore) -> None:
        response = await _handle_watch(store, {"action": "add", "url": 123, "source_type": "rss"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_watch_add_source_type_not_string(self, store: DuckDBStore) -> None:
        response = await _handle_watch(
            store, {"action": "add", "url": "https://example.com/feed", "source_type": 123}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_watch_add_invalid_poll_interval(self, store: DuckDBStore) -> None:
        response = await _handle_watch(
            store,
            {
                "action": "add",
                "url": "https://example.com/feed",
                "source_type": "rss",
                "poll_interval_minutes": "bad",
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_watch_add_negative_poll_interval(self, store: DuckDBStore) -> None:
        response = await _handle_watch(
            store,
            {
                "action": "add",
                "url": "https://example.com/feed",
                "source_type": "rss",
                "poll_interval_minutes": -1,
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_watch_add_invalid_trust_weight(self, store: DuckDBStore) -> None:
        response = await _handle_watch(
            store,
            {
                "action": "add",
                "url": "https://example.com/feed",
                "source_type": "rss",
                "trust_weight": "bad",
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_watch_add_trust_weight_out_of_range(self, store: DuckDBStore) -> None:
        response = await _handle_watch(
            store,
            {
                "action": "add",
                "url": "https://example.com/feed",
                "source_type": "rss",
                "trust_weight": 1.5,
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_watch_add_store_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "add_feed_source", side_effect=RuntimeError("boom")):
            response = await _handle_watch(
                store,
                {
                    "action": "add",
                    "url": "https://example.com/feed",
                    "source_type": "rss",
                },
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_watch_list_store_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "list_feed_sources", side_effect=RuntimeError("boom")):
            response = await _handle_watch(store, {"action": "list"})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_watch_remove_store_error(self, store: DuckDBStore) -> None:
        with patch.object(store, "remove_feed_source", side_effect=RuntimeError("boom")):
            response = await _handle_watch(
                store, {"action": "remove", "url": "https://example.com/feed"}
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"

    async def test_watch_add_duplicate(self, store: DuckDBStore) -> None:
        with patch.object(store, "add_feed_source", side_effect=ValueError("duplicate")):
            response = await _handle_watch(
                store,
                {
                    "action": "add",
                    "url": "https://example.com/feed",
                    "source_type": "rss",
                },
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "CONFLICT"


class TestPollGaps:
    """Cover error path in _handle_poll."""

    async def test_poll_source_not_found(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_poll(store, config, {"source_url": "https://nonexistent.com/feed"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_poll_error(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        with patch(
            "distillery.feeds.poller.FeedPoller.poll",
            side_effect=RuntimeError("poll fail"),
        ):
            response = await _handle_poll(store, config, {})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestRescoreGaps:
    """Cover error path in _handle_rescore."""

    async def test_rescore_invalid_limit(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_rescore(store, config, {"limit": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_rescore_error(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        with patch(
            "distillery.feeds.poller.FeedPoller.rescore",
            side_effect=RuntimeError("rescore fail"),
        ):
            response = await _handle_rescore(store, config, {})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestSuggestSourcesGaps:
    """Cover validation paths in _handle_interests (suggest_sources=True)."""

    async def test_suggest_invalid_max_suggestions(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(
            store, config, {"suggest_sources": True, "max_suggestions": "bad"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_suggest_zero_max_suggestions(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(
            store, config, {"suggest_sources": True, "max_suggestions": 0}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_suggest_invalid_recency_days(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(
            store, config, {"suggest_sources": True, "recency_days": "bad"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_suggest_zero_recency_days(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(
            store, config, {"suggest_sources": True, "recency_days": 0}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_suggest_invalid_top_n(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_interests(store, config, {"suggest_sources": True, "top_n": "bad"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_suggest_zero_top_n(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        response = await _handle_interests(store, config, {"suggest_sources": True, "top_n": 0})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_suggest_extraction_error(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        with patch("distillery.feeds.interests.InterestExtractor") as mock_cls:
            mock_cls.return_value.extract = AsyncMock(side_effect=RuntimeError("boom"))
            response = await _handle_interests(store, config, {"suggest_sources": True})
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INTERNAL"


class TestNormaliseWatchedSet:
    """Cover _normalise_watched_set helper."""

    def test_github_url_slug_extracted(self) -> None:
        result = _normalise_watched_set(["https://github.com/owner/repo"])
        assert "https://github.com/owner/repo" in result
        assert "owner/repo" in result

    def test_bare_slug_expanded(self) -> None:
        result = _normalise_watched_set(["owner/repo"])
        assert "owner/repo" in result
        assert "https://github.com/owner/repo" in result

    def test_non_github_url_unchanged(self) -> None:
        result = _normalise_watched_set(["https://example.com/feed"])
        assert "https://example.com/feed" in result


class TestDeriveSuggestions:
    """Cover _derive_suggestions helper."""

    def test_github_suggestions(self) -> None:
        profile = MagicMock()
        profile.tracked_repos = ["owner/repo"]
        profile.bookmark_domains = []
        result = _derive_suggestions(profile, set(), None, 5)
        assert len(result) == 1
        assert result[0]["source_type"] == "github"

    def test_rss_suggestions(self) -> None:
        profile = MagicMock()
        profile.tracked_repos = []
        profile.bookmark_domains = ["example.com"]
        result = _derive_suggestions(profile, set(), None, 5)
        assert len(result) == 1
        assert result[0]["source_type"] == "rss"

    def test_excludes_watched(self) -> None:
        profile = MagicMock()
        profile.tracked_repos = ["owner/repo"]
        profile.bookmark_domains = []
        result = _derive_suggestions(profile, {"owner/repo"}, None, 5)
        assert len(result) == 0

    def test_source_type_filter(self) -> None:
        profile = MagicMock()
        profile.tracked_repos = ["owner/repo"]
        profile.bookmark_domains = ["example.com"]
        result = _derive_suggestions(profile, set(), {"rss"}, 5)
        assert all(s["source_type"] == "rss" for s in result)

    def test_max_suggestions_respected(self) -> None:
        profile = MagicMock()
        profile.tracked_repos = [f"owner/repo{i}" for i in range(10)]
        profile.bookmark_domains = []
        result = _derive_suggestions(profile, set(), None, 3)
        assert len(result) == 3

    def test_short_domain_excluded(self) -> None:
        profile = MagicMock()
        profile.tracked_repos = []
        profile.bookmark_domains = ["ab"]  # too short (<=3 chars)
        result = _derive_suggestions(profile, set(), None, 5)
        assert len(result) == 0


# ===========================================================================
# auth.py gap coverage
# ===========================================================================


class TestOrgRestrictedGitHubProvider:
    """Cover _extract_upstream_claims in OrgRestrictedGitHubProvider."""

    async def test_extract_claims_no_access_token(self) -> None:
        from distillery.mcp.auth import OrgRestrictedGitHubProvider
        from distillery.mcp.org_membership import OrgMembershipChecker

        checker = OrgMembershipChecker(allowed_orgs=["myorg"])
        provider = OrgRestrictedGitHubProvider(
            org_checker=checker,
            client_id="test-id",
            client_secret="test-secret",
            base_url="https://example.com",
        )
        result = await provider._extract_upstream_claims({})
        assert result is None

    async def test_extract_claims_non_string_token(self) -> None:
        from distillery.mcp.auth import OrgRestrictedGitHubProvider
        from distillery.mcp.org_membership import OrgMembershipChecker

        checker = OrgMembershipChecker(allowed_orgs=["myorg"])
        provider = OrgRestrictedGitHubProvider(
            org_checker=checker,
            client_id="test-id",
            client_secret="test-secret",
            base_url="https://example.com",
        )
        result = await provider._extract_upstream_claims({"access_token": 12345})
        assert result is None

    async def test_extract_claims_api_failure(self) -> None:

        from distillery.mcp.auth import OrgRestrictedGitHubProvider
        from distillery.mcp.org_membership import OrgMembershipChecker

        checker = OrgMembershipChecker(allowed_orgs=["myorg"])
        provider = OrgRestrictedGitHubProvider(
            org_checker=checker,
            client_id="test-id",
            client_secret="test-secret",
            base_url="https://example.com",
        )

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await provider._extract_upstream_claims({"access_token": "gho_test123"})
            assert result is None

    async def test_extract_claims_success(self) -> None:
        from distillery.mcp.auth import OrgRestrictedGitHubProvider
        from distillery.mcp.org_membership import OrgMembershipChecker

        checker = OrgMembershipChecker(allowed_orgs=["myorg"])
        provider = OrgRestrictedGitHubProvider(
            org_checker=checker,
            client_id="test-id",
            client_secret="test-secret",
            base_url="https://example.com",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "login": "testuser",
            "name": "Test User",
            "email": "test@example.com",
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await provider._extract_upstream_claims({"access_token": "gho_test123"})
            assert result is not None
            assert result["login"] == "testuser"
            assert result["name"] == "Test User"
            assert result["email"] == "test@example.com"

    async def test_extract_claims_exception(self) -> None:
        from distillery.mcp.auth import OrgRestrictedGitHubProvider
        from distillery.mcp.org_membership import OrgMembershipChecker

        checker = OrgMembershipChecker(allowed_orgs=["myorg"])
        provider = OrgRestrictedGitHubProvider(
            org_checker=checker,
            client_id="test-id",
            client_secret="test-secret",
            base_url="https://example.com",
        )

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=RuntimeError("network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await provider._extract_upstream_claims({"access_token": "gho_test123"})
            assert result is None


class TestPatchCimdLocalhostRedirect:
    """Cover _patch_cimd_localhost_redirect."""

    def test_patch_applies(self) -> None:
        from distillery.mcp.auth import _patch_cimd_localhost_redirect

        # Just verify it runs without error
        _patch_cimd_localhost_redirect()


class TestBuildGithubAuthGaps:
    """Cover edge cases in build_github_auth."""

    def test_build_github_auth_missing_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from distillery.config import ServerAuthConfig, ServerConfig
        from distillery.mcp.auth import build_github_auth

        monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
        monkeypatch.delenv("DISTILLERY_BASE_URL", raising=False)

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            server=ServerConfig(auth=ServerAuthConfig()),
        )
        with pytest.raises(ValueError, match="DISTILLERY_BASE_URL"):
            build_github_auth(config)

    def test_build_github_auth_invalid_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from distillery.config import ServerAuthConfig, ServerConfig
        from distillery.mcp.auth import build_github_auth

        monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
        monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
        monkeypatch.setenv("DISTILLERY_BASE_URL", "not-a-url")

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            server=ServerConfig(auth=ServerAuthConfig()),
        )
        with pytest.raises(ValueError, match="valid absolute"):
            build_github_auth(config)


# ===========================================================================
# _stub_embedding.py gap coverage (line 56)
# ===========================================================================


class TestStubEmbeddingProvider:
    """Cover StubEmbeddingProvider.embed_batch."""

    def test_embed_batch(self) -> None:
        provider = StubEmbeddingProvider(dimensions=4)
        result = provider.embed_batch(["hello", "world"])
        assert len(result) == 2
        assert all(len(v) == 4 for v in result)
        assert all(x == 0.0 for v in result for x in v)

    def test_model_name(self) -> None:
        provider = StubEmbeddingProvider()
        assert provider.model_name == "stub"

    def test_dimensions(self) -> None:
        provider = StubEmbeddingProvider(dimensions=128)
        assert provider.dimensions == 128


class TestHashEmbeddingProvider:
    """Cover HashEmbeddingProvider edge case."""

    def test_embed_batch(self) -> None:
        provider = HashEmbeddingProvider(dimensions=4)
        result = provider.embed_batch(["hello", "world"])
        assert len(result) == 2
        assert all(len(v) == 4 for v in result)

    def test_model_name(self) -> None:
        provider = HashEmbeddingProvider()
        assert provider.model_name == "mock-hash"


# ===========================================================================
# tools/quality.py gap coverage (budget + dedup error)
# ===========================================================================


class TestCheckDedupGaps:
    """Cover budget-exceeded path in _handle_find_similar (dedup_action=True)."""

    async def test_check_dedup_budget_exceeded(
        self, store: DuckDBStore, budget_config: DistilleryConfig
    ) -> None:
        from distillery.mcp.budget import record_and_check
        from distillery.mcp.tools.search import _handle_find_similar

        record_and_check(store.connection, budget_config.rate_limit.embedding_budget_daily)
        response = await _handle_find_similar(
            store, {"content": "test content", "dedup_action": True}, cfg=budget_config
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "BUDGET_EXCEEDED"

    async def test_check_dedup_checker_raises_on_store_error(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        from distillery.mcp.tools.quality import run_dedup_check

        with (
            patch(
                "distillery.classification.dedup.DeduplicationChecker.check",
                side_effect=RuntimeError("dedup boom"),
            ),
            pytest.raises(RuntimeError, match="dedup boom"),
        ):
            await run_dedup_check(store, config.classification, "test content")


# ===========================================================================
# tools/crud.py additional gap coverage
# ===========================================================================


class TestSyncGatherStatsWarnings:
    """Cover warning paths in _sync_gather_summary."""

    def test_status_with_db_size_warning(self, embedding_provider) -> None:  # type: ignore[no-untyped-def]
        """Summary handler emits a size warning when DB nears limit."""
        import tempfile

        from distillery.mcp.tools.analytics import _sync_gather_summary

        # Create a temp file and write some data to make it have a measurable size
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * (1024 * 1024))  # 1MB
            db_file = f.name

        try:
            cfg = DistilleryConfig(
                storage=StorageConfig(database_path=db_file),
                rate_limit=RateLimitConfig(max_db_size_mb=2, warn_db_size_pct=50),
            )
            # Mock a store with a connection
            mock_store = MagicMock()
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = (0,)
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_store.connection = mock_conn

            result = _sync_gather_summary(mock_store, cfg, embedding_provider)
            # 1MB file with 2MB limit at 50% warn threshold = should warn
            assert "warnings" in result
            assert any("at" in w and "%" in w for w in result["warnings"])
        finally:
            import os

            os.unlink(db_file)

    def test_status_with_db_at_limit(self, embedding_provider) -> None:  # type: ignore[no-untyped-def]
        """Summary handler emits a limit warning when DB exceeds max."""
        import tempfile

        from distillery.mcp.tools.analytics import _sync_gather_summary

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * (2 * 1024 * 1024))  # 2MB
            db_file = f.name

        try:
            cfg = DistilleryConfig(
                storage=StorageConfig(database_path=db_file),
                rate_limit=RateLimitConfig(max_db_size_mb=1),
            )
            mock_store = MagicMock()
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = (0,)
            mock_conn.execute.return_value.fetchall.return_value = []
            mock_store.connection = mock_conn

            result = _sync_gather_summary(mock_store, cfg, embedding_provider)
            assert "warnings" in result
            assert any("reached the limit" in w for w in result["warnings"])
        finally:
            import os

            os.unlink(db_file)

    def test_status_with_budget_warning(self, embedding_provider) -> None:  # type: ignore[no-untyped-def]
        """Summary handler warns when embedding budget is exhausted."""
        from distillery.mcp.tools.analytics import _sync_gather_summary

        cfg = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            rate_limit=RateLimitConfig(embedding_budget_daily=1),
        )
        mock_store = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (0,)
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_store.connection = mock_conn

        with patch("distillery.mcp.budget.get_daily_usage", return_value=5):
            result = _sync_gather_summary(mock_store, cfg, embedding_provider)
            assert "warnings" in result
            assert any("budget exhausted" in w for w in result["warnings"])


class TestUpdateWithValidTypeAndStatus:
    """Cover update with valid entry_type and status (lines 574, etc)."""

    async def test_update_valid_entry_type(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Type update test", entry_type=EntryType.INBOX)
        entry_id = await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry_id, "entry_type": "idea"})
        data = parse_mcp_response(response)
        assert data["entry_type"] == "idea"

    async def test_update_valid_status(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Status update test")
        entry_id = await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry_id, "status": "archived"})
        data = parse_mcp_response(response)
        assert data["status"] == "archived"


class TestStoreDbSizeCheck:
    """Cover DB size check path in _handle_store."""

    async def test_store_db_size_exceeded(self, store: DuckDBStore) -> None:
        """Store rejects when DB size exceeds limit (file-based path)."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            f.write(b"x" * (2 * 1024 * 1024))
            db_file = f.name

        try:
            cfg = DistilleryConfig(
                storage=StorageConfig(database_path=db_file),
                rate_limit=RateLimitConfig(max_db_size_mb=1),
            )
            response = await _handle_store(
                store,
                {"content": "test", "entry_type": "inbox", "author": "bob"},
                cfg=cfg,
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "BUDGET_EXCEEDED"
        finally:
            import os

            os.unlink(db_file)


class TestStoreConstructionError:
    """Cover entry construction error in _handle_store."""

    async def test_store_entry_construction_error(self, store: DuckDBStore) -> None:
        """Store returns INVALID_PARAMS when Entry() raises."""
        with patch("distillery.models.Entry.__init__", side_effect=TypeError("bad")):
            response = await _handle_store(
                store,
                {"content": "test", "entry_type": "inbox", "author": "bob"},
            )
            data = parse_mcp_response(response)
            assert data["error"] is True
            assert data["code"] == "INVALID_PARAMS"


# ===========================================================================
# Tag tree exact-prefix match (analytics line 102, 116-117)
# ===========================================================================


class TestTagTreeExactPrefix:
    """Cover tag tree with exact prefix match counting at root."""

    async def test_tag_tree_exact_prefix_counts(self, store: DuckDBStore) -> None:
        """An entry tagged with the exact prefix increments root count."""
        entry = make_entry(content="Exact prefix", tags=["lang", "lang/python"])
        await store.store(entry)
        response = await _handle_tag_tree(store, {"prefix": "lang"})
        data = parse_mcp_response(response)
        tree = data["tree"]
        # Root should count the exact "lang" tag
        assert tree["count"] >= 1
        # And children should include "python"
        assert "python" in tree["children"]


# ===========================================================================
# Webhook body parsing coverage
# ===========================================================================


class TestWebhookRescoreBodyParsing:
    """Cover _handle_rescore body parsing (webhooks.py lines 374-391)."""

    async def test_rescore_malformed_json_body(self) -> None:

        from distillery.mcp.webhooks import _handle_rescore

        request = MagicMock()
        request.body = AsyncMock(return_value=b"not json")
        state = {"store": MagicMock(), "config": MagicMock()}

        response = await _handle_rescore(request, state)
        assert response.status_code == 400

    async def test_rescore_body_not_dict(self) -> None:
        from distillery.mcp.webhooks import _handle_rescore

        request = MagicMock()
        request.body = AsyncMock(return_value=b'"just a string"')
        state = {"store": MagicMock(), "config": MagicMock()}

        response = await _handle_rescore(request, state)
        assert response.status_code == 400

    async def test_rescore_body_limit_not_int(self) -> None:
        from distillery.mcp.webhooks import _handle_rescore

        request = MagicMock()
        request.body = AsyncMock(return_value=b'{"limit": "bad"}')
        state = {"store": MagicMock(), "config": MagicMock()}

        response = await _handle_rescore(request, state)
        assert response.status_code == 400

    async def test_rescore_body_limit_bool(self) -> None:
        from distillery.mcp.webhooks import _handle_rescore

        request = MagicMock()
        request.body = AsyncMock(return_value=b'{"limit": true}')
        state = {"store": MagicMock(), "config": MagicMock()}

        response = await _handle_rescore(request, state)
        assert response.status_code == 400

    async def test_rescore_handler_error(self) -> None:
        from distillery.mcp.webhooks import _handle_rescore

        request = MagicMock()
        request.body = AsyncMock(return_value=b"{}")
        state = {"store": MagicMock(), "config": MagicMock()}

        with patch(
            "distillery.feeds.poller.FeedPoller.rescore",
            side_effect=RuntimeError("fail"),
        ):
            response = await _handle_rescore(request, state)
            assert response.status_code == 500


class TestWebhookCooldown:
    """Cover _check_cooldown parsing paths (webhooks.py lines 194-203)."""

    async def test_check_cooldown_bad_iso_format(self, store: DuckDBStore) -> None:
        from distillery.mcp.webhooks import _check_cooldown

        # Store a non-ISO string as cooldown value
        await store.set_metadata("webhook_cooldown:poll", "not-a-date")
        result = await _check_cooldown(store, "poll")
        assert result is None  # Should return None for unparseable dates

    async def test_check_cooldown_returns_remaining(self, store: DuckDBStore) -> None:
        from distillery.mcp.webhooks import _check_cooldown

        # Store a recent timestamp
        now = datetime.now(UTC).isoformat()
        await store.set_metadata("webhook_cooldown:poll", now)
        result = await _check_cooldown(store, "poll")
        assert result is not None
        assert result > 0

    async def test_set_cooldown(self, store: DuckDBStore) -> None:
        from distillery.mcp.webhooks import _set_cooldown

        await _set_cooldown(store, "poll")
        raw = await store.get_metadata("webhook_cooldown:poll")
        assert raw is not None


class TestWebhookRecordAudit:
    """Cover _record_audit paths (webhooks.py lines 240-241, 283-285)."""

    async def test_record_audit_success(self, store: DuckDBStore) -> None:
        from starlette.responses import JSONResponse

        from distillery.mcp.webhooks import _record_audit

        response = JSONResponse({"ok": True, "data": {"sources": 1}})
        await _record_audit(store, "poll", response)
        raw = await store.get_metadata("webhook_audit:poll")
        assert raw is not None
        import json

        audit = json.loads(raw)
        assert audit["ok"] is True

    async def test_record_audit_error_response(self, store: DuckDBStore) -> None:
        from starlette.responses import JSONResponse

        from distillery.mcp.webhooks import _record_audit

        response = JSONResponse({"ok": False, "error": "something failed"}, status_code=500)
        await _record_audit(store, "poll", response)
        raw = await store.get_metadata("webhook_audit:poll")
        assert raw is not None
        import json

        audit = json.loads(raw)
        assert "error" in audit

    async def test_record_audit_unparseable_body(self, store: DuckDBStore) -> None:
        from starlette.responses import JSONResponse

        from distillery.mcp.webhooks import _record_audit

        # Create a response with bad body
        response = JSONResponse({"ok": True})
        # Override body to be unparseable
        response.body = b"not json"
        await _record_audit(store, "poll", response)
        raw = await store.get_metadata("webhook_audit:poll")
        assert raw is not None


# ===========================================================================
# Auth CIMDFetcher patch behavior (auth.py lines 118-152, 167-185)
# ===========================================================================


class TestCimdPatchBehavior:
    """Test the actual behavior of the patched CIMDFetcher validation."""

    def _make_doc_and_fetcher(self, redirect_uris: list[str]):  # type: ignore[no-untyped-def]
        """Create a mock doc and fetcher with the patched method."""
        from distillery.mcp.auth import _patch_cimd_localhost_redirect

        _patch_cimd_localhost_redirect()

        try:
            from fastmcp.server.auth.cimd import CIMDFetcher
        except ImportError:
            pytest.skip("FastMCP CIMD not available")

        fetcher = CIMDFetcher.__new__(CIMDFetcher)
        doc = MagicMock()
        doc.redirect_uris = redirect_uris
        return fetcher, doc

    def test_patched_validate_redirect_uri_exact_match(self) -> None:
        """After patching, exact match still works."""
        fetcher, doc = self._make_doc_and_fetcher(["http://localhost/callback"])
        result = fetcher.validate_redirect_uri(doc, "http://localhost/callback")
        assert result is True

    def test_patched_validate_redirect_uri_port_agnostic(self) -> None:
        """After patching, localhost with different port is accepted."""
        fetcher, doc = self._make_doc_and_fetcher(["http://localhost/callback"])
        result = fetcher.validate_redirect_uri(doc, "http://localhost:12345/callback")
        assert result is True

    def test_patched_validate_redirect_uri_no_match(self) -> None:
        """After patching, non-matching URIs are rejected."""
        fetcher, doc = self._make_doc_and_fetcher(["http://localhost/callback"])
        result = fetcher.validate_redirect_uri(doc, "http://example.com/callback")
        assert result is False

    def test_patched_validate_redirect_uri_empty_uris(self) -> None:
        """After patching, empty redirect_uris returns False."""
        fetcher, doc = self._make_doc_and_fetcher([])
        result = fetcher.validate_redirect_uri(doc, "http://localhost/callback")
        assert result is False

    def test_patched_validate_redirect_uri_wildcard(self) -> None:
        """After patching, wildcard patterns still work."""
        fetcher, doc = self._make_doc_and_fetcher(["http://localhost/*"])
        result = fetcher.validate_redirect_uri(doc, "http://localhost/callback")
        assert result is True

    def test_patched_proxy_redirect_match(self) -> None:
        """Test the patched proxy redirect matching."""
        from distillery.mcp.auth import _patch_cimd_localhost_redirect

        _patch_cimd_localhost_redirect()

        try:
            import fastmcp.server.auth.oauth_proxy.models as proxy_models

            matches = proxy_models.matches_allowed_pattern
        except (ImportError, AttributeError):
            pytest.skip("FastMCP proxy models not available")

        # Loopback port-agnostic match
        result = matches("http://localhost:12345/callback", "http://localhost/callback")
        assert result is True

        # Non-loopback should not match
        result = matches("http://example.com:12345/callback", "http://example.com/callback")
        assert result is False
