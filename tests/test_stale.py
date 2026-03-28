"""Tests for the distillery_stale MCP tool (T02.2).

Covers all requirements:
  - Staleness detection: entries older than threshold appear in results
  - accessed_at updates via get(): entry no longer appears stale
  - accessed_at updates via search(): entry no longer appears stale
  - Day threshold filtering: custom ``days`` parameter works
  - Fallback to updated_at: entries without accessed_at use updated_at
  - entry_type filter: only matching types returned
  - Limit parameter: respects max results
  - Empty database: returns empty list gracefully

For time-sensitive tests, timestamps are inserted via direct DuckDB queries so
the tests are deterministic regardless of when they run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.server import _handle_stale
from distillery.models import EntryType
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = UTC


def _ts(days_ago: float) -> str:
    """
    Produce a UTC timestamp string representing the time days_ago days before now.
    
    Parameters:
        days_ago (float): Number of days to subtract from the current UTC time; may be fractional.
    
    Returns:
        str: UTC timestamp formatted as "YYYY-MM-DD HH:MM:SS".
    """
    dt = datetime.now(_UTC) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _make_config(stale_days: int = 30) -> DistilleryConfig:
    """
    Create a DistilleryConfig preconfigured for in-memory testing.
    
    Parameters:
        stale_days (int): Number of days after which an entry is considered stale; used to set the classification stale_days threshold.
    
    Returns:
        DistilleryConfig: Configuration using in-memory storage, a mock embedding provider, and a classification config with confidence_threshold 0.6 and the specified stale_days.
    """
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="mock-hash-4d", dimensions=4),
        classification=ClassificationConfig(
            confidence_threshold=0.6,
            stale_days=stale_days,
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    """
    Provide a fresh MockEmbeddingProvider for tests.
    
    Returns:
        MockEmbeddingProvider: A new mock embedding provider instance.
    """
    return MockEmbeddingProvider()


@pytest.fixture
async def store(embedding_provider: MockEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    """
    Provide an initialized DuckDBStore backed by an in-memory database and ensure it is closed when the fixture is torn down.
    
    Parameters:
        embedding_provider (MockEmbeddingProvider): Embedding provider to attach to the store.
    
    Returns:
        DuckDBStore: An initialized store instance connected to an in-memory DuckDB and ready for use.
    """
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    """
    Create a DistilleryConfig using the test defaults.
    
    Returns:
        DistilleryConfig: Configuration with in-memory DuckDB storage, a mock embedding provider,
        classification confidence_threshold of 0.6, and the default stale_days (30).
    """
    return _make_config()


# ---------------------------------------------------------------------------
# Helper to call the stale tool and parse the result
# ---------------------------------------------------------------------------


async def _stale(
    store: DuckDBStore,
    config: DistilleryConfig,
    *,
    days: int | None = None,
    limit: int | None = None,
    entry_type: str | None = None,
) -> dict:
    """
    Request stale entries from the stale MCP handler and return the parsed response.
    
    Parameters:
    	days (int | None): Optional override for the staleness threshold in days.
    	limit (int | None): Optional maximum number of entries to return.
    	entry_type (str | None): Optional entry type filter (e.g., "reference", "idea").
    
    Returns:
    	dict: Parsed MCP response containing keys such as `stale_count`, `entries`, `days_threshold`, and any validation `error` information.
    """
    args: dict = {}
    if days is not None:
        args["days"] = days
    if limit is not None:
        args["limit"] = limit
    if entry_type is not None:
        args["entry_type"] = entry_type
    response = await _handle_stale(store, config, args)
    return parse_mcp_response(response)


def _force_timestamps(
    store: DuckDBStore,
    entry_id: str,
    *,
    updated_at: str | None = None,
    accessed_at: str | None = None,
    clear_accessed_at: bool = False,
) -> None:
    """
    Set an entry's `updated_at` and/or `accessed_at` timestamp fields directly in the database.
    
    This helper mutates the `entries` table using the store's raw connection. Provide ISO-like UTC timestamp strings formatted as "%Y-%m-%d %H:%M:%S" for `updated_at` and `accessed_at`. If `clear_accessed_at` is True, `accessed_at` will be set to NULL regardless of `accessed_at` value.
    
    Parameters:
        store (DuckDBStore): Store whose database connection will be used.
        entry_id (str): ID of the entry to update.
        updated_at (str | None): Timestamp to set for `updated_at`, or None to leave unchanged.
        accessed_at (str | None): Timestamp to set for `accessed_at`, or None to leave unchanged.
        clear_accessed_at (bool): If True, set `accessed_at` to NULL; takes precedence over `accessed_at`.
    """
    conn = store.connection
    if updated_at is not None:
        conn.execute(
            "UPDATE entries SET updated_at = ? WHERE id = ?",
            [updated_at, entry_id],
        )
    if clear_accessed_at:
        conn.execute("UPDATE entries SET accessed_at = NULL WHERE id = ?", [entry_id])
    elif accessed_at is not None:
        conn.execute(
            "UPDATE entries SET accessed_at = ? WHERE id = ?",
            [accessed_at, entry_id],
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyDatabase:
    """distillery_stale on an empty DB should return an empty list, not error."""

    async def test_empty_db_returns_empty_list(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        """
        Verify that requesting stale entries from an empty store returns no entries.
        
        Asserts the response contains no "error" key, `stale_count` is 0, and `entries` is an empty list.
        """
        data = await _stale(store, config)
        # No error key, successful response with stale_count == 0
        assert "error" not in data
        assert data["stale_count"] == 0
        assert data["entries"] == []

    async def test_empty_db_days_threshold_respected(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        data = await _stale(store, config, days=7)
        assert "error" not in data
        assert data["days_threshold"] == 7
        assert data["entries"] == []


class TestStalenessDetection:
    """Entries older than the threshold should appear; recent ones should not."""

    async def test_stale_entry_appears_in_results(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Old knowledge that hasn't been accessed")
        await store.store(entry)
        # Force accessed_at and updated_at to be far in the past.
        _force_timestamps(
            store,
            entry.id,
            updated_at=_ts(60),
            accessed_at=_ts(60),
        )

        data = await _stale(store, config, days=30)
        assert "error" not in data
        ids = [e["id"] for e in data["entries"]]
        assert entry.id in ids

    async def test_recent_entry_not_in_results(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Recently accessed entry")
        await store.store(entry)
        # Leave timestamps at current time (store sets them to now).

        data = await _stale(store, config, days=30)
        assert "error" not in data
        ids = [e["id"] for e in data["entries"]]
        assert entry.id not in ids

    async def test_stale_entry_content_preview_truncated_to_200(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        long_content = "A" * 500
        entry = make_entry(content=long_content)
        await store.store(entry)
        _force_timestamps(store, entry.id, updated_at=_ts(60), accessed_at=_ts(60))

        data = await _stale(store, config, days=30)
        entries = data["entries"]
        assert len(entries) == 1
        assert len(entries[0]["content_preview"]) <= 200

    async def test_result_fields_present(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Check field presence", author="alice", project="proj-1")
        await store.store(entry)
        _force_timestamps(store, entry.id, updated_at=_ts(60), accessed_at=_ts(60))

        data = await _stale(store, config, days=30)
        entries = data["entries"]
        assert len(entries) == 1
        e = entries[0]
        assert "id" in e
        assert "content_preview" in e
        assert "entry_type" in e
        assert "author" in e
        assert "project" in e
        assert "last_accessed" in e
        assert "days_since_access" in e
        assert e["author"] == "alice"
        assert e["project"] == "proj-1"

    async def test_archived_entries_excluded(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Archived old entry")
        await store.store(entry)
        _force_timestamps(store, entry.id, updated_at=_ts(60), accessed_at=_ts(60))
        # Archive the entry.
        store.connection.execute(
            "UPDATE entries SET status = 'archived' WHERE id = ?", [entry.id]
        )

        data = await _stale(store, config, days=30)
        ids = [e["id"] for e in data["entries"]]
        assert entry.id not in ids


class TestAccessedAtUpdates:
    """Entries accessed via get() or search() should no longer be stale."""

    async def test_get_removes_entry_from_stale_list(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Will be retrieved via get")
        await store.store(entry)
        _force_timestamps(store, entry.id, updated_at=_ts(60), accessed_at=_ts(60))

        # Confirm it appears stale.
        before = await _stale(store, config, days=30)
        ids_before = [e["id"] for e in before["entries"]]
        assert entry.id in ids_before

        # Access via get() — this should update accessed_at to now.
        retrieved = await store.get(entry.id)
        assert retrieved is not None

        # Should no longer appear stale.
        after = await _stale(store, config, days=30)
        ids_after = [e["id"] for e in after["entries"]]
        assert entry.id not in ids_after

    async def test_search_removes_entry_from_stale_list(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Unique stale search marker content xyz")
        await store.store(entry)
        _force_timestamps(store, entry.id, updated_at=_ts(60), accessed_at=_ts(60))

        # Confirm stale.
        before = await _stale(store, config, days=30)
        ids_before = [e["id"] for e in before["entries"]]
        assert entry.id in ids_before

        # Access via search().
        results = await store.search("stale search marker content xyz", None, limit=5)
        assert any(r.entry.id == entry.id for r in results)

        # Should no longer appear stale.
        after = await _stale(store, config, days=30)
        ids_after = [e["id"] for e in after["entries"]]
        assert entry.id not in ids_after


class TestDayThreshold:
    """Custom ``days`` parameter should control the staleness cutoff."""

    async def test_default_days_uses_config(
        self, store: DuckDBStore
    ) -> None:
        config = _make_config(stale_days=7)
        entry = make_entry(content="Entry just over 7 days old")
        await store.store(entry)
        _force_timestamps(store, entry.id, updated_at=_ts(10), accessed_at=_ts(10))

        data = await _stale(store, config)
        assert data["days_threshold"] == 7
        ids = [e["id"] for e in data["entries"]]
        assert entry.id in ids

    async def test_custom_days_filters_correctly(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        # Entry is 15 days old — stale for days=7, not stale for days=30.
        entry = make_entry(content="Entry 15 days since access")
        await store.store(entry)
        _force_timestamps(store, entry.id, updated_at=_ts(15), accessed_at=_ts(15))

        stale_7 = await _stale(store, config, days=7)
        stale_30 = await _stale(store, config, days=30)

        ids_7 = [e["id"] for e in stale_7["entries"]]
        ids_30 = [e["id"] for e in stale_30["entries"]]

        assert entry.id in ids_7
        assert entry.id not in ids_30

    async def test_days_threshold_reflected_in_response(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        data = await _stale(store, config, days=14)
        assert data["days_threshold"] == 14


class TestFallbackToUpdatedAt:
    """Entries without accessed_at should fall back to updated_at for staleness."""

    async def test_null_accessed_at_falls_back_to_updated_at(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Entry without accessed_at, stale updated_at")
        await store.store(entry)
        # Set updated_at far in the past and clear accessed_at.
        _force_timestamps(
            store,
            entry.id,
            updated_at=_ts(60),
            clear_accessed_at=True,
        )

        data = await _stale(store, config, days=30)
        ids = [e["id"] for e in data["entries"]]
        assert entry.id in ids

    async def test_null_accessed_at_recent_updated_at_not_stale(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entry = make_entry(content="Entry without accessed_at, fresh updated_at")
        await store.store(entry)
        # updated_at is current (just stored), accessed_at NULL.
        _force_timestamps(store, entry.id, clear_accessed_at=True)

        data = await _stale(store, config, days=30)
        ids = [e["id"] for e in data["entries"]]
        assert entry.id not in ids


class TestEntryTypeFilter:
    """entry_type parameter should restrict results to matching types only."""

    async def test_entry_type_filter_returns_only_matching(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        note = make_entry(
            content="Stale reference entry", entry_type=EntryType.REFERENCE
        )
        fact = make_entry(
            content="Stale idea entry", entry_type=EntryType.IDEA
        )
        await store.store(note)
        await store.store(fact)
        _force_timestamps(store, note.id, updated_at=_ts(60), accessed_at=_ts(60))
        _force_timestamps(store, fact.id, updated_at=_ts(60), accessed_at=_ts(60))

        data = await _stale(store, config, days=30, entry_type=EntryType.REFERENCE.value)
        ids = [e["id"] for e in data["entries"]]
        assert note.id in ids
        assert fact.id not in ids

    async def test_entry_type_filter_no_match_empty(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        note = make_entry(content="Stale reference entry", entry_type=EntryType.REFERENCE)
        await store.store(note)
        _force_timestamps(store, note.id, updated_at=_ts(60), accessed_at=_ts(60))

        data = await _stale(store, config, days=30, entry_type=EntryType.IDEA.value)
        assert data["stale_count"] == 0
        assert data["entries"] == []

    async def test_entry_type_filter_reflected_in_response(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        data = await _stale(store, config, days=30, entry_type="reference")
        assert data["entry_type_filter"] == "reference"

    async def test_no_entry_type_filter_returns_all_types(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        note = make_entry(content="Stale reference", entry_type=EntryType.REFERENCE)
        fact = make_entry(content="Stale idea", entry_type=EntryType.IDEA)
        await store.store(note)
        await store.store(fact)
        _force_timestamps(store, note.id, updated_at=_ts(60), accessed_at=_ts(60))
        _force_timestamps(store, fact.id, updated_at=_ts(60), accessed_at=_ts(60))

        data = await _stale(store, config, days=30)
        ids = [e["id"] for e in data["entries"]]
        assert note.id in ids
        assert fact.id in ids


class TestLimitParameter:
    """limit parameter should cap the number of results."""

    async def test_limit_caps_results(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        for i in range(5):
            entry = make_entry(content=f"Stale entry number {i}")
            await store.store(entry)
            _force_timestamps(store, entry.id, updated_at=_ts(60 + i), accessed_at=_ts(60 + i))

        data = await _stale(store, config, days=30, limit=3)
        assert len(data["entries"]) <= 3

    async def test_default_limit_is_20(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        # Insert 25 stale entries.
        for i in range(25):
            entry = make_entry(content=f"Stale limit test entry {i}")
            await store.store(entry)
            _force_timestamps(store, entry.id, updated_at=_ts(60 + i), accessed_at=_ts(60 + i))

        data = await _stale(store, config, days=30)
        assert len(data["entries"]) <= 20

    async def test_stalest_first_ordering(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        entries = []
        for days_ago in [35, 45, 40]:
            entry = make_entry(content=f"Entry accessed {days_ago} days ago")
            await store.store(entry)
            _force_timestamps(store, entry.id, updated_at=_ts(days_ago), accessed_at=_ts(days_ago))
            entries.append((days_ago, entry.id))

        data = await _stale(store, config, days=30)
        result_ids = [e["id"] for e in data["entries"]]
        # entries[1] is oldest (45 days), should come first.
        oldest_id = entries[1][1]  # 45 days ago
        assert result_ids.index(oldest_id) == 0


class TestValidation:
    """Validation errors should return error responses, not exceptions."""

    async def test_invalid_days_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"days": "not-an-int"})
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert "VALIDATION_ERROR" in data["code"]

    async def test_invalid_limit_type(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"limit": "not-an-int"})
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert "VALIDATION_ERROR" in data["code"]

    async def test_days_below_one_is_invalid(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"days": 0})
        data = parse_mcp_response(response)
        assert data.get("error") is True

    async def test_limit_below_one_is_invalid(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        response = await _handle_stale(store, config, {"limit": 0})
        data = parse_mcp_response(response)
        assert data.get("error") is True
