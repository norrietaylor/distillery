"""Tests for the distillery_metrics MCP tool (T04.2).

Covers all sections returned by _handle_metrics / _sync_gather_metrics:
  - Empty database: all sections return zeros/empty without error
  - Entry metrics: total, by_type, by_status, by_source counts
  - Activity metrics: created/updated 7d/30d/90d window counts
  - Search metrics: total_searches, recent counts, avg_results_per_search
  - Quality metrics: positive_rate, total_feedback, feedback_30d
  - Staleness metrics: stale_count and by_type breakdown
  - period_days parameter: affects recent window keys
  - Storage metrics: db_file_size, embedding_model, embedding_dimensions
  - Top-level keys present: entries, activity, search, quality, staleness, storage

For time-sensitive tests, timestamps are inserted via direct DuckDB queries so
the tests are deterministic regardless of when they run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.tools.analytics import _handle_metrics
from distillery.models import EntrySource, EntryStatus, EntryType
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = UTC


def _ts(days_ago: float) -> str:
    """
    Generate a UTC timestamp string for the current time minus the given number of days.

    Parameters:
        days_ago (float): Number of days to subtract from the current UTC time. Use fractional values for partial days.

    Returns:
        str: Timestamp formatted as "YYYY-MM-DD HH:MM:SS" in UTC.
    """
    dt = datetime.now(_UTC) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _make_config(db_path: str = ":memory:") -> DistilleryConfig:
    """
    Builds a DistilleryConfig prepopulated for tests with a mock embedding and configurable database path.

    Parameters:
        db_path (str): Path to the database file; use ":memory:" (default) for an in-memory database.

    Returns:
        DistilleryConfig: Configuration with storage.database_path set to `db_path`, embedding.provider set to an empty string, embedding.model set to "mock-hash-4d", embedding.dimensions set to 4, and classification.confidence_threshold set to 0.6.
    """
    return DistilleryConfig(
        storage=StorageConfig(database_path=db_path),
        embedding=EmbeddingConfig(provider="", model="mock-hash-4d", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    """
    Provide a mock embedding provider for tests.

    Returns:
        MockEmbeddingProvider: A new MockEmbeddingProvider instance configured for use in test cases.
    """
    return MockEmbeddingProvider()


@pytest.fixture
async def store(embedding_provider: MockEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    """
    Provide an initialized in-memory DuckDBStore configured with the given embedding provider.

    Parameters:
        embedding_provider (MockEmbeddingProvider): Embedding provider used to configure the store.

    Returns:
        DuckDBStore: An initialized in-memory DuckDBStore instance. The store is closed by the fixture after the caller finishes using it.
    """
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    """
    Builds a DistilleryConfig populated with the default test settings.

    Defaults: storage.database_path=":memory:", embedding.model="mock-hash-4d", embedding.dimensions=4, embedding.provider="", classification.confidence_threshold=0.6.

    Returns:
        DistilleryConfig: Configuration configured for tests using an in-memory database and mock embedding settings.
    """
    return _make_config()


# ---------------------------------------------------------------------------
# Helper to call the metrics tool and parse the result
# ---------------------------------------------------------------------------


async def _metrics(
    store: DuckDBStore,
    config: DistilleryConfig,
    embedding_provider: MockEmbeddingProvider,
    *,
    period_days: int = 30,
) -> dict:
    """
    Retrieve metrics for the given store using the specified recent-period window and return the parsed MCP response.

    Parameters:
        period_days (int): Number of days used as the "recent" window for metrics (e.g., created_{n}d, searches_{n}d). Defaults to 30.

    Returns:
        dict: Parsed MCP response containing top-level sections such as `entries`, `activity`, `search`, `quality`, `staleness`, and `storage`.
    """
    response = await _handle_metrics(
        store, config, embedding_provider, {"period_days": period_days}
    )
    return parse_mcp_response(response)


# ---------------------------------------------------------------------------
# 1. All top-level keys present
# ---------------------------------------------------------------------------


class TestTopLevelKeys:
    async def test_all_keys_present(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """The response must contain all 6 top-level sections."""
        data = await _metrics(store, config, embedding_provider)
        assert set(data.keys()) >= {
            "entries",
            "activity",
            "search",
            "quality",
            "staleness",
            "storage",
        }


# ---------------------------------------------------------------------------
# 2. Empty database
# ---------------------------------------------------------------------------


class TestEmptyDatabase:
    async def test_entries_zeros(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        data = await _metrics(store, config, embedding_provider)
        entries = data["entries"]
        assert entries["total"] == 0
        assert entries["by_type"] == {}
        assert entries["by_source"] == {}

    async def test_activity_zeros(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """
        Verify activity metrics are zero when the database contains no entries.

        Asserts that `created_7d`, `created_30d`, `created_90d`, and `updated_7d` are all 0.
        """
        data = await _metrics(store, config, embedding_provider)
        activity = data["activity"]
        assert activity["created_7d"] == 0
        assert activity["created_30d"] == 0
        assert activity["created_90d"] == 0
        assert activity["updated_7d"] == 0

    async def test_search_zeros(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """
        Verify search metrics return zeroed values when the database contains no search logs.

        Asserts that `total_searches` is 0, `searches_7d` is 0, and `avg_results_per_search` is 0.0.
        """
        data = await _metrics(store, config, embedding_provider)
        search = data["search"]
        assert search["total_searches"] == 0
        assert search["searches_7d"] == 0
        assert search["avg_results_per_search"] == 0.0

    async def test_quality_zeros(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        data = await _metrics(store, config, embedding_provider)
        quality = data["quality"]
        assert quality["total_feedback"] == 0
        assert quality["feedback_30d"] == 0
        assert quality["positive_rate"] == 0.0

    async def test_staleness_zeros(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        data = await _metrics(store, config, embedding_provider)
        assert data["staleness"]["stale_count"] == 0
        assert data["staleness"]["by_type"] == {}

    async def test_storage_model_info(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        data = await _metrics(store, config, embedding_provider)
        storage = data["storage"]
        # in-memory DB has no file size
        assert storage["db_file_size"] is None
        assert storage["embedding_model"] == "mock-hash-4d"
        assert storage["embedding_dimensions"] == 4


# ---------------------------------------------------------------------------
# 3. Entry metrics
# ---------------------------------------------------------------------------


class TestEntryMetrics:
    async def test_counts_by_type_status_source(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """Store entries with different types/statuses/sources; verify counts."""
        entries = [
            make_entry(
                content="Session A", entry_type=EntryType.SESSION, source=EntrySource.CLAUDE_CODE
            ),
            make_entry(
                content="Session B", entry_type=EntryType.SESSION, source=EntrySource.CLAUDE_CODE
            ),
            make_entry(
                content="Bookmark A", entry_type=EntryType.BOOKMARK, source=EntrySource.MANUAL
            ),
            make_entry(content="Idea A", entry_type=EntryType.IDEA, source=EntrySource.IMPORT),
        ]
        for e in entries:
            await store.store(e)

        data = await _metrics(store, config, embedding_provider)
        ent = data["entries"]

        assert ent["total"] == 4
        assert ent["by_type"]["session"] == 2
        assert ent["by_type"]["bookmark"] == 1
        assert ent["by_type"]["idea"] == 1
        assert ent["by_source"]["claude-code"] == 2
        assert ent["by_source"]["manual"] == 1
        assert ent["by_source"]["import"] == 1

    async def test_archived_entries_excluded_from_total(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """Archived entries must not count toward total."""
        await store.store(make_entry(content="Keep me", entry_type=EntryType.INBOX))
        archived_id = await store.store(
            make_entry(content="Archive me", entry_type=EntryType.INBOX)
        )
        await store.update(archived_id, {"status": EntryStatus.ARCHIVED})

        data = await _metrics(store, config, embedding_provider)
        assert data["entries"]["total"] == 1

    async def test_by_status_includes_archived(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """by_status counts ALL entries including archived."""
        await store.store(make_entry(content="Active"))
        arch_id = await store.store(make_entry(content="Archived"))
        await store.update(arch_id, {"status": EntryStatus.ARCHIVED})

        data = await _metrics(store, config, embedding_provider)
        by_status = data["entries"]["by_status"]
        assert by_status.get("active", 0) == 1
        assert by_status.get("archived", 0) == 1


# ---------------------------------------------------------------------------
# 4. Activity metrics
# ---------------------------------------------------------------------------


class TestActivityMetrics:
    async def test_recent_entries_counted(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """Entries created/updated recently must appear in 7d and 30d buckets."""
        # Store an entry; it gets a current created_at/updated_at by default.
        await store.store(make_entry(content="Fresh entry"))

        data = await _metrics(store, config, embedding_provider)
        act = data["activity"]
        assert act["created_7d"] >= 1
        assert act["created_30d"] >= 1
        assert act["created_90d"] >= 1
        assert act["updated_7d"] >= 1

    async def test_old_entries_excluded_from_7d(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """Entries with old timestamps must not appear in the 7d bucket."""
        # Insert directly with an old timestamp (10 days ago).
        entry = make_entry(content="Old entry")
        await store.store(entry)
        old_ts = _ts(10)
        store.connection.execute(
            "UPDATE entries SET created_at = ?, updated_at = ? WHERE content = 'Old entry'",
            [old_ts, old_ts],
        )

        data = await _metrics(store, config, embedding_provider)
        assert data["activity"]["created_7d"] == 0
        assert data["activity"]["created_30d"] == 1  # within 30d window
        assert data["activity"]["created_90d"] == 1


# ---------------------------------------------------------------------------
# 5. Search metrics
# ---------------------------------------------------------------------------


class TestSearchMetrics:
    def _insert_search(
        self,
        store: DuckDBStore,
        *,
        query: str = "test query",
        result_ids: list[str] | None = None,
        days_ago: float = 0.0,
    ) -> str:
        """
        Insert a search record into the store's search_log and return the new record id.

        Parameters:
            store (DuckDBStore): Database store to insert into.
            query (str): Search query text to record.
            result_ids (list[str] | None): List of result entry IDs to store; empty list if None.
            days_ago (float): Age of the timestamp in days relative to now.

        Returns:
            row_id (str): UUID string of the inserted search record.
        """
        row_id = str(uuid.uuid4())
        ts = _ts(days_ago)
        ids_array = result_ids or []
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            [row_id, query, ids_array, [], ts],
        )
        return row_id

    async def test_total_searches_counted(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        self._insert_search(store)
        self._insert_search(store)
        data = await _metrics(store, config, embedding_provider)
        assert data["search"]["total_searches"] == 2

    async def test_searches_7d_only_recent(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        self._insert_search(store, days_ago=1)  # recent
        self._insert_search(store, days_ago=10)  # > 7 days
        data = await _metrics(store, config, embedding_provider)
        assert data["search"]["searches_7d"] == 1
        assert data["search"]["total_searches"] == 2

    async def test_avg_results_per_search(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        e1_id = str(uuid.uuid4())
        e2_id = str(uuid.uuid4())
        self._insert_search(store, result_ids=[e1_id, e2_id])  # 2 results
        self._insert_search(store, result_ids=[e1_id])  # 1 result
        # avg = (2 + 1) / 2 = 1.5
        data = await _metrics(store, config, embedding_provider)
        avg = data["search"]["avg_results_per_search"]
        assert abs(avg - 1.5) < 0.01


# ---------------------------------------------------------------------------
# 6. Quality metrics
# ---------------------------------------------------------------------------


class TestQualityMetrics:
    def _insert_search(self, store: DuckDBStore) -> str:
        """
        Insert a row into `search_log` with query `'q'`, empty result arrays, and the current timestamp.

        Parameters:
            store (DuckDBStore): Database store whose connection will be used to perform the insert.

        Returns:
            row_id (str): UUID string of the newly inserted search row.
        """
        row_id = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', [], [], CURRENT_TIMESTAMP)",
            [row_id],
        )
        return row_id

    def _insert_feedback(
        self,
        store: DuckDBStore,
        *,
        search_id: str,
        entry_id: str,
        signal: str = "positive",
        days_ago: float = 0.0,
    ) -> None:
        """
        Insert a feedback record into the store's feedback_log table.

        Parameters:
            store (DuckDBStore): Target database store where the feedback row will be inserted.
            search_id (str): Identifier of the related search.
            entry_id (str): Identifier of the related entry.
            signal (str): Feedback signal value (e.g., "positive" or "negative"). Defaults to "positive".
            days_ago (float): Age of the inserted timestamp in days relative to now; 0.0 sets the current timestamp.
        """
        row_id = str(uuid.uuid4())
        ts = _ts(days_ago)
        store.connection.execute(
            "INSERT INTO feedback_log (id, search_id, entry_id, signal, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            [row_id, search_id, entry_id, signal, ts],
        )

    async def test_positive_rate_calculation(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """positive_rate = positives / total across all feedback."""
        sid = self._insert_search(store)
        eid = str(uuid.uuid4())
        self._insert_feedback(store, search_id=sid, entry_id=eid, signal="positive")
        self._insert_feedback(store, search_id=sid, entry_id=eid, signal="positive")
        self._insert_feedback(store, search_id=sid, entry_id=eid, signal="negative")
        # 2 positive out of 3 total -> 0.6667
        data = await _metrics(store, config, embedding_provider)
        quality = data["quality"]
        assert quality["total_feedback"] == 3
        assert abs(quality["positive_rate"] - round(2 / 3, 4)) < 0.001

    async def test_feedback_30d_window(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        sid = self._insert_search(store)
        eid = str(uuid.uuid4())
        self._insert_feedback(store, search_id=sid, entry_id=eid, days_ago=5)  # recent
        self._insert_feedback(store, search_id=sid, entry_id=eid, days_ago=40)  # old
        data = await _metrics(store, config, embedding_provider)
        assert data["quality"]["total_feedback"] == 2
        assert data["quality"]["feedback_30d"] == 1


# ---------------------------------------------------------------------------
# 7. Staleness metrics
# ---------------------------------------------------------------------------


class TestStalenessMetrics:
    async def test_stale_count_uses_updated_at(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """Entries last updated > 30 days ago count as stale."""
        await store.store(make_entry(content="Fresh entry"))
        await store.store(make_entry(content="Stale entry", entry_type=EntryType.SESSION))

        # Force the second entry's updated_at far into the past.
        old_ts = _ts(35)
        store.connection.execute(
            "UPDATE entries SET updated_at = ? WHERE content = 'Stale entry'",
            [old_ts],
        )

        data = await _metrics(store, config, embedding_provider)
        staleness = data["staleness"]
        assert staleness["stale_count"] == 1
        assert staleness["stale_days"] == 30
        assert staleness["by_type"].get("session", 0) == 1

    async def test_archived_excluded_from_stale(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """Archived entries are not counted in stale_count."""
        arch_id = await store.store(make_entry(content="Old archived"))
        await store.update(arch_id, {"status": EntryStatus.ARCHIVED})
        old_ts = _ts(60)
        store.connection.execute(
            "UPDATE entries SET updated_at = ? WHERE content = 'Old archived'",
            [old_ts],
        )

        data = await _metrics(store, config, embedding_provider)
        assert data["staleness"]["stale_count"] == 0

    async def test_stale_by_type_groups(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """by_type in staleness section groups stale entries by type."""
        await store.store(make_entry(content="Old session", entry_type=EntryType.SESSION))
        await store.store(make_entry(content="Old idea", entry_type=EntryType.IDEA))
        await store.store(make_entry(content="Fresh session", entry_type=EntryType.SESSION))

        old_ts = _ts(35)
        for content in ("Old session", "Old idea"):
            store.connection.execute(
                "UPDATE entries SET updated_at = ? WHERE content = ?",
                [old_ts, content],
            )

        data = await _metrics(store, config, embedding_provider)
        by_type = data["staleness"]["by_type"]
        assert by_type.get("session", 0) == 1
        assert by_type.get("idea", 0) == 1


# ---------------------------------------------------------------------------
# 8. period_days parameter
# ---------------------------------------------------------------------------


class TestPeriodDaysParameter:
    def _insert_search(self, store: DuckDBStore, *, days_ago: float) -> None:
        """
        Insert a search record into the store's search_log with a timestamp offset by the given number of days.

        Parameters:
            store (DuckDBStore): Target database store where the search row will be inserted.
            days_ago (float): Number of days to subtract from now to set the search `timestamp`.
        """
        row_id = str(uuid.uuid4())
        ts = _ts(days_ago)
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', [], [], ?)",
            [row_id, ts],
        )

    async def test_custom_period_days_key_present(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """
        Verify that setting period_days=14 adds activity keys `created_14d` and `updated_14d` and the search key `searches_14d` to the metrics response.
        """
        data = await _metrics(store, config, embedding_provider, period_days=14)
        assert "created_14d" in data["activity"]
        assert "updated_14d" in data["activity"]
        assert "searches_14d" in data["search"]

    async def test_period_days_filters_searches(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """searches_{period_days}d only counts searches within that window."""
        self._insert_search(store, days_ago=3)  # within 7d
        self._insert_search(store, days_ago=10)  # within 14d but not 7d
        self._insert_search(store, days_ago=20)  # outside 14d

        data7 = await _metrics(store, config, embedding_provider, period_days=7)
        data14 = await _metrics(store, config, embedding_provider, period_days=14)
        assert data7["search"]["searches_7d"] == 1
        assert data14["search"]["searches_14d"] == 2

    async def test_period_days_affects_activity(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """created_{period_days}d counts only entries within that window."""
        await store.store(make_entry(content="Recent"))
        await store.store(make_entry(content="Old"))
        old_ts = _ts(20)
        store.connection.execute(
            "UPDATE entries SET created_at = ?, updated_at = ? WHERE content = 'Old'",
            [old_ts, old_ts],
        )

        data7 = await _metrics(store, config, embedding_provider, period_days=7)
        data30 = await _metrics(store, config, embedding_provider, period_days=30)
        assert data7["activity"]["created_7d"] == 1
        assert data30["activity"]["created_30d"] == 2

    async def test_invalid_period_days_returns_error(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """period_days < 1 must return a INVALID_PARAMS response."""
        response = await _handle_metrics(store, config, embedding_provider, {"period_days": 0})
        data = parse_mcp_response(response)
        assert data.get("error") is not None or data.get("code") == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# 9. Storage metrics
# ---------------------------------------------------------------------------


class TestStorageMetrics:
    async def test_in_memory_db_size_is_null(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        data = await _metrics(store, config, embedding_provider)
        assert data["storage"]["db_file_size"] is None

    async def test_embedding_model_and_dimensions(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        data = await _metrics(store, config, embedding_provider)
        storage = data["storage"]
        assert storage["embedding_model"] == embedding_provider.model_name
        assert storage["embedding_dimensions"] == embedding_provider.dimensions
