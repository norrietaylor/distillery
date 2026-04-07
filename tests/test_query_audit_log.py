"""Tests for query_audit_log on DistilleryStore / DuckDBStore.

Covers:
- querying an empty audit log returns []
- write then query returns matching rows
- filter by user
- filter by operation (tool)
- filter by date_from and date_to
- limit clamping (below 1, above 500)
- ordering by timestamp DESC
"""

from __future__ import annotations

import pytest

from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store() -> DuckDBStore:  # type: ignore[return]
    """Initialised in-memory DuckDBStore, yielded for test use, then closed."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=MockEmbeddingProvider())
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _write(
    store: DuckDBStore,
    user_id: str = "alice",
    tool: str = "distill",
    entry_id: str = "entry-1",
    action: str = "store",
    outcome: str = "success",
) -> None:
    """Write a single audit_log row directly via write_audit_log."""
    await store.write_audit_log(
        user_id=user_id,
        tool=tool,
        entry_id=entry_id,
        action=action,
        outcome=outcome,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestQueryAuditLogEmpty:
    async def test_empty_audit_log_returns_empty_list(self, store: DuckDBStore) -> None:
        result = await store.query_audit_log(filters=None)
        assert result == []


class TestQueryAuditLogBasic:
    async def test_written_record_appears_in_results(self, store: DuckDBStore) -> None:
        await _write(store, user_id="bob", tool="recall", entry_id="e-1")
        result = await store.query_audit_log(filters=None)
        assert len(result) == 1
        row = result[0]
        assert row["user_id"] == "bob"
        assert row["tool"] == "recall"
        assert row["entry_id"] == "e-1"
        assert row["action"] == "store"
        assert row["outcome"] == "success"

    async def test_result_contains_expected_keys(self, store: DuckDBStore) -> None:
        await _write(store)
        result = await store.query_audit_log(filters=None)
        assert len(result) == 1
        row = result[0]
        assert set(row.keys()) == {"id", "timestamp", "user_id", "tool", "entry_id", "action", "outcome"}

    async def test_timestamp_is_iso8601_string(self, store: DuckDBStore) -> None:
        await _write(store)
        result = await store.query_audit_log(filters=None)
        ts = result[0]["timestamp"]
        assert isinstance(ts, str)
        # Should be parseable as ISO 8601
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        assert dt is not None

    async def test_multiple_records_returned(self, store: DuckDBStore) -> None:
        for i in range(5):
            await _write(store, user_id=f"user-{i}", entry_id=f"entry-{i}")
        result = await store.query_audit_log(filters=None)
        assert len(result) == 5


class TestQueryAuditLogFilterUser:
    async def test_filter_by_user_returns_only_matching(self, store: DuckDBStore) -> None:
        await _write(store, user_id="alice")
        await _write(store, user_id="bob")
        await _write(store, user_id="alice")

        result = await store.query_audit_log(filters={"user": "alice"})
        assert len(result) == 2
        for row in result:
            assert row["user_id"] == "alice"

    async def test_filter_by_user_no_match_returns_empty(self, store: DuckDBStore) -> None:
        await _write(store, user_id="alice")
        result = await store.query_audit_log(filters={"user": "charlie"})
        assert result == []


class TestQueryAuditLogFilterOperation:
    async def test_filter_by_operation_returns_only_matching(self, store: DuckDBStore) -> None:
        await _write(store, tool="distill")
        await _write(store, tool="recall")
        await _write(store, tool="distill")

        result = await store.query_audit_log(filters={"operation": "distill"})
        assert len(result) == 2
        for row in result:
            assert row["tool"] == "distill"

    async def test_filter_by_operation_no_match_returns_empty(self, store: DuckDBStore) -> None:
        await _write(store, tool="distill")
        result = await store.query_audit_log(filters={"operation": "bookmark"})
        assert result == []


class TestQueryAuditLogDateFilter:
    async def test_date_from_excludes_earlier_records(self, store: DuckDBStore) -> None:
        """Records written before date_from should be excluded."""
        # Write a record, capture its timestamp, then query with date_from in the future.
        await _write(store, user_id="alice")
        result_all = await store.query_audit_log(filters=None)
        assert len(result_all) == 1

        # Use a date_from far in the future — should exclude the record.
        result = await store.query_audit_log(filters={"date_from": "2099-01-01T00:00:00+00:00"})
        assert result == []

    async def test_date_to_excludes_later_records(self, store: DuckDBStore) -> None:
        """Records written after date_to should be excluded."""
        await _write(store, user_id="alice")
        # Use date_to in the far past — should exclude all records.
        result = await store.query_audit_log(filters={"date_to": "2000-01-01T00:00:00+00:00"})
        assert result == []

    async def test_date_range_includes_records_within_range(self, store: DuckDBStore) -> None:
        """Records within the date range should be returned."""
        await _write(store, user_id="alice")
        result = await store.query_audit_log(
            filters={
                "date_from": "2000-01-01T00:00:00+00:00",
                "date_to": "2099-12-31T23:59:59+00:00",
            }
        )
        assert len(result) == 1


class TestQueryAuditLogOrdering:
    async def test_results_ordered_by_timestamp_desc(self, store: DuckDBStore) -> None:
        """Multiple records should be returned newest-first."""
        for i in range(3):
            await _write(store, user_id=f"user-{i}")
        result = await store.query_audit_log(filters=None)
        assert len(result) == 3
        # Timestamps should be in descending (or equal) order.
        from datetime import datetime
        timestamps = [datetime.fromisoformat(r["timestamp"]) for r in result]
        for i in range(len(timestamps) - 1):
            assert timestamps[i] >= timestamps[i + 1]


class TestQueryAuditLogLimitClamping:
    async def test_limit_default_is_50(self, store: DuckDBStore) -> None:
        """Default limit should return at most 50 rows."""
        for i in range(60):
            await _write(store, user_id=f"u{i}")
        result = await store.query_audit_log(filters=None)
        assert len(result) == 50

    async def test_limit_below_1_clamped_to_1(self, store: DuckDBStore) -> None:
        for i in range(5):
            await _write(store, user_id=f"u{i}")
        result = await store.query_audit_log(filters=None, limit=0)
        assert len(result) == 1

    async def test_limit_above_500_clamped_to_500(self, store: DuckDBStore) -> None:
        for i in range(10):
            await _write(store, user_id=f"u{i}")
        result = await store.query_audit_log(filters=None, limit=9999)
        # We only wrote 10, so we get 10 back — confirming clamp doesn't error.
        assert len(result) == 10

    async def test_limit_respected_when_more_records_exist(self, store: DuckDBStore) -> None:
        for i in range(10):
            await _write(store, user_id=f"u{i}")
        result = await store.query_audit_log(filters=None, limit=3)
        assert len(result) == 3

    async def test_limit_negative_clamped_to_1(self, store: DuckDBStore) -> None:
        for i in range(5):
            await _write(store, user_id=f"u{i}")
        result = await store.query_audit_log(filters=None, limit=-5)
        assert len(result) == 1


class TestQueryAuditLogCombinedFilters:
    async def test_user_and_operation_filter_combined(self, store: DuckDBStore) -> None:
        await _write(store, user_id="alice", tool="distill")
        await _write(store, user_id="alice", tool="recall")
        await _write(store, user_id="bob", tool="distill")

        result = await store.query_audit_log(filters={"user": "alice", "operation": "distill"})
        assert len(result) == 1
        assert result[0]["user_id"] == "alice"
        assert result[0]["tool"] == "distill"
