"""Tests for implicit retrieval feedback and distillery_quality MCP tool (T01.4).

Covers:
  - Search logging: verify search_log row created after distillery_search
  - Implicit feedback: verify feedback_log row when distillery_get follows search within window
  - Time window expiry: verify NO feedback when get is outside the window
  - Quality metrics aggregation: verify distillery_quality returns correct counts and rates
  - Entry type filter: verify per_type_breakdown when entry_type argument is provided
  - Empty database: verify distillery_quality returns zeros gracefully

Time-sensitive tests manipulate the in-memory recent_searches list directly so
they remain deterministic without requiring freezegun or wall-clock sleeps.
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
from distillery.mcp.server import _handle_get, _handle_quality, _handle_search
from distillery.models import EntryType
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(feedback_window_minutes: int = 5) -> DistilleryConfig:
    """
    Builds a DistilleryConfig preconfigured for in-memory tests.

    Parameters:
        feedback_window_minutes (int): Maximum age, in minutes, for considering searches as recent for implicit feedback.

    Returns:
        DistilleryConfig: Configuration using in-memory DuckDB storage, a mock embedding provider (model "mock-hash-4d", 4 dimensions), and classification settings with a 0.6 confidence threshold and the provided feedback window.
    """
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="mock-hash-4d", dimensions=4),
        classification=ClassificationConfig(
            confidence_threshold=0.6,
            feedback_window_minutes=feedback_window_minutes,
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    """
    Create and return a new MockEmbeddingProvider instance for tests.

    Returns:
        MockEmbeddingProvider: a fresh mock embedding provider.
    """
    return MockEmbeddingProvider()


@pytest.fixture
async def store(embedding_provider: MockEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    """
    Provide an initialized in-memory DuckDBStore for tests and ensure it is closed after use.

    Parameters:
        embedding_provider (MockEmbeddingProvider): Embedding provider to attach to the store.

    Returns:
        DuckDBStore: An initialized DuckDBStore using an in-memory database (":memory:") configured with the given embedding provider.
    """
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    """
    Builds the default DistilleryConfig used by the tests.

    Returns:
        DistilleryConfig: Configuration using an in-memory DuckDB store (":memory:"), a mock embedding provider,
        and classification settings with `confidence_threshold=0.6` and the default feedback window (5 minutes).
    """
    return _make_config()


# ---------------------------------------------------------------------------
# Helper: call distillery_quality and parse response
# ---------------------------------------------------------------------------


async def _quality(
    store: DuckDBStore,
    *,
    entry_type: str | None = None,
) -> dict:
    """
    Compute aggregated quality metrics for searches and feedback, optionally filtered by entry type.

    Parameters:
        entry_type (str | None): If provided, restrict metrics to feedback/searches for the given entry type.

    Returns:
        dict: Aggregated metrics with the following keys:
            - total_searches (int): Total number of recorded searches.
            - total_feedback (int): Total number of recorded feedback events.
            - positive_rate (float): Fraction of feedback events with a positive signal (0.0 to 1.0).
            - avg_result_count (float): Average number of results returned per recorded search.
            - per_type_breakdown (dict): Mapping from entry type (str) to a dict of metrics for that type
              (each sub-dict contains `total_feedback` (int), `positive_count` (int), and `positive_rate` (float)).
    """
    args: dict = {}
    if entry_type is not None:
        args["entry_type"] = entry_type
    response = await _handle_quality(store, args)
    return parse_mcp_response(response)


# ---------------------------------------------------------------------------
# 1. Empty database - all zeros gracefully
# ---------------------------------------------------------------------------


class TestEmptyDatabase:
    async def test_quality_zeros(self, store: DuckDBStore) -> None:
        """distillery_quality returns sensible zeros for an empty store."""
        data = await _quality(store)
        assert data["total_searches"] == 0
        assert data["total_feedback"] == 0
        assert data["positive_rate"] == 0.0
        assert data["avg_result_count"] == 0.0
        assert data["per_type_breakdown"] == {}

    async def test_required_keys_present(self, store: DuckDBStore) -> None:
        """All expected top-level keys must be present in the response."""
        data = await _quality(store)
        expected_keys = {
            "total_searches",
            "total_feedback",
            "positive_rate",
            "avg_result_count",
            "per_type_breakdown",
        }
        assert expected_keys.issubset(data.keys())


# ---------------------------------------------------------------------------
# 2. Search logging
# ---------------------------------------------------------------------------


class TestSearchLogging:
    async def test_search_log_row_created(
        self,
        store: DuckDBStore,
    ) -> None:
        """A row must appear in search_log after distillery_search succeeds."""
        entry = make_entry(content="searchable knowledge")
        await store.store(entry)

        recent_searches: list[dict] = []
        await _handle_search(store, {"query": "searchable knowledge"}, recent_searches)

        row = store.connection.execute(
            "SELECT COUNT(*) FROM search_log"
        ).fetchone()
        assert row is not None
        assert row[0] == 1

    async def test_search_log_records_result_ids(
        self,
        store: DuckDBStore,
    ) -> None:
        """search_log row must store the entry IDs returned by the search."""
        entry = make_entry(content="unique knowledge fragment")
        entry_id = await store.store(entry)

        recent_searches: list[dict] = []
        await _handle_search(
            store, {"query": "unique knowledge fragment"}, recent_searches
        )

        row = store.connection.execute(
            "SELECT result_entry_ids FROM search_log LIMIT 1"
        ).fetchone()
        assert row is not None
        result_ids: list[str] = row[0]
        assert entry_id in result_ids

    async def test_quality_total_searches_increments(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
        embedding_provider: MockEmbeddingProvider,
    ) -> None:
        """distillery_quality.total_searches increments after each search."""
        entry = make_entry(content="query target")
        await store.store(entry)

        recent_searches: list[dict] = []
        await _handle_search(store, {"query": "query target"}, recent_searches)
        await _handle_search(store, {"query": "query target"}, recent_searches)

        data = await _quality(store)
        assert data["total_searches"] == 2

    async def test_search_without_results_not_logged(
        self,
        store: DuckDBStore,
    ) -> None:
        """If search returns no results, no search_log row is created."""
        recent_searches: list[dict] = []
        # Search against an empty store - no results expected.
        await _handle_search(store, {"query": "no match at all"}, recent_searches)

        row = store.connection.execute(
            "SELECT COUNT(*) FROM search_log"
        ).fetchone()
        assert row is not None
        assert row[0] == 0

    async def test_quality_avg_result_count(
        self,
        store: DuckDBStore,
    ) -> None:
        """avg_result_count reflects the average number of results per search."""
        # Insert two search_log rows with known result counts directly.
        id1, id2, id3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        sid1 = str(uuid.uuid4())
        sid2 = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q1', ?, [], CURRENT_TIMESTAMP)",
            [sid1, [id1, id2]],  # 2 results
        )
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q2', ?, [], CURRENT_TIMESTAMP)",
            [sid2, [id3]],  # 1 result
        )
        # avg = (2 + 1) / 2 = 1.5
        data = await _quality(store)
        assert abs(data["avg_result_count"] - 1.5) < 0.01


# ---------------------------------------------------------------------------
# 3. Implicit feedback within window
# ---------------------------------------------------------------------------


class TestImplicitFeedbackWithinWindow:
    async def test_feedback_log_created_after_get(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        """A feedback_log row must appear when get follows search within window."""
        entry = make_entry(content="feedback target")
        entry_id = await store.store(entry)

        # Build a recent_searches list that includes entry_id.
        search_id = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', ?, [], CURRENT_TIMESTAMP)",
            [search_id, [entry_id]],
        )
        recent_searches: list[dict] = [
            {
                "search_id": search_id,
                "entry_ids": {entry_id},
                "timestamp": datetime.now(UTC),  # within window
            }
        ]

        await _handle_get(store, {"entry_id": entry_id}, recent_searches, config)

        row = store.connection.execute(
            "SELECT COUNT(*), signal FROM feedback_log "
            "WHERE entry_id = ? GROUP BY signal",
            [entry_id],
        ).fetchone()
        assert row is not None
        count, signal = row
        assert count == 1
        assert signal == "positive"

    async def test_quality_feedback_counts_updated(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        """distillery_quality reflects feedback after a within-window get."""
        entry = make_entry(content="quality signal entry")
        entry_id = await store.store(entry)

        search_id = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', ?, [], CURRENT_TIMESTAMP)",
            [search_id, [entry_id]],
        )
        recent_searches: list[dict] = [
            {
                "search_id": search_id,
                "entry_ids": {entry_id},
                "timestamp": datetime.now(UTC),
            }
        ]
        await _handle_get(store, {"entry_id": entry_id}, recent_searches, config)

        data = await _quality(store)
        assert data["total_feedback"] == 1
        assert data["positive_rate"] == 1.0

    async def test_positive_rate_with_mixed_signals(
        self,
        store: DuckDBStore,
    ) -> None:
        """positive_rate = positive_count / total_feedback with mixed signals."""
        sid = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', [], [], CURRENT_TIMESTAMP)",
            [sid],
        )
        eid = str(uuid.uuid4())
        # Insert 2 positive + 1 negative = positive_rate 2/3 ~= 0.6667
        for signal in ("positive", "positive", "negative"):
            store.connection.execute(
                "INSERT INTO feedback_log (id, search_id, entry_id, signal, timestamp) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                [str(uuid.uuid4()), sid, eid, signal],
            )

        data = await _quality(store)
        assert data["total_feedback"] == 3
        assert abs(data["positive_rate"] - round(2 / 3, 4)) < 0.001


# ---------------------------------------------------------------------------
# 4. Time window expiry - NO feedback outside window
# ---------------------------------------------------------------------------


class TestImplicitFeedbackWindowExpiry:
    async def test_no_feedback_when_search_expired(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        """No feedback_log row if the search timestamp is outside the window."""
        entry = make_entry(content="late access entry")
        entry_id = await store.store(entry)

        search_id = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', ?, [], CURRENT_TIMESTAMP)",
            [search_id, [entry_id]],
        )

        # Simulate an expired search record: timestamp 10 minutes ago with 5 min window.
        expired_timestamp = datetime.now(UTC) - timedelta(minutes=10)
        recent_searches: list[dict] = [
            {
                "search_id": search_id,
                "entry_ids": {entry_id},
                "timestamp": expired_timestamp,
            }
        ]

        await _handle_get(store, {"entry_id": entry_id}, recent_searches, config)

        row = store.connection.execute(
            "SELECT COUNT(*) FROM feedback_log"
        ).fetchone()
        assert row is not None
        assert row[0] == 0

    async def test_expired_search_pruned_from_list(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        """Expired records must be removed from recent_searches after get()."""
        entry = make_entry(content="prune target")
        entry_id = await store.store(entry)

        search_id = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', ?, [], CURRENT_TIMESTAMP)",
            [search_id, [entry_id]],
        )

        expired_timestamp = datetime.now(UTC) - timedelta(minutes=10)
        recent_searches: list[dict] = [
            {
                "search_id": search_id,
                "entry_ids": {entry_id},
                "timestamp": expired_timestamp,
            }
        ]

        await _handle_get(store, {"entry_id": entry_id}, recent_searches, config)

        # Expired record must have been pruned from the list.
        assert len(recent_searches) == 0

    async def test_entry_not_in_search_results_no_feedback(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        """No feedback when entry_id was not in the recent search's results."""
        entry_a = make_entry(content="entry A")
        entry_b = make_entry(content="entry B")
        id_a = await store.store(entry_a)
        id_b = await store.store(entry_b)

        search_id = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', ?, [], CURRENT_TIMESTAMP)",
            [search_id, [id_a]],  # only entry A in results
        )
        recent_searches: list[dict] = [
            {
                "search_id": search_id,
                "entry_ids": {id_a},
                "timestamp": datetime.now(UTC),
            }
        ]

        # Fetch entry B - not in the search results
        await _handle_get(store, {"entry_id": id_b}, recent_searches, config)

        row = store.connection.execute(
            "SELECT COUNT(*) FROM feedback_log"
        ).fetchone()
        assert row is not None
        assert row[0] == 0


# ---------------------------------------------------------------------------
# 5. Per-type breakdown via entry_type filter
# ---------------------------------------------------------------------------


class TestPerTypeBreakdown:
    async def test_per_type_breakdown_empty_when_no_filter(
        self,
        store: DuckDBStore,
    ) -> None:
        """per_type_breakdown is empty dict when no entry_type filter is given."""
        data = await _quality(store)
        assert data["per_type_breakdown"] == {}

    async def test_per_type_breakdown_filters_by_entry_type(
        self,
        store: DuckDBStore,
    ) -> None:
        """per_type_breakdown counts feedback for entries of the requested type."""
        session_entry = make_entry(content="session entry", entry_type=EntryType.SESSION)
        inbox_entry = make_entry(content="inbox entry", entry_type=EntryType.INBOX)
        session_id = await store.store(session_entry)
        inbox_id = await store.store(inbox_entry)

        # Insert a search_log row.
        sid = str(uuid.uuid4())
        store.connection.execute(
            "INSERT INTO search_log (id, query, result_entry_ids, result_scores, timestamp) "
            "VALUES (?, 'q', ?, [], CURRENT_TIMESTAMP)",
            [sid, [session_id, inbox_id]],
        )

        # Insert feedback for both types.
        for eid, signal in [(session_id, "positive"), (inbox_id, "negative")]:
            store.connection.execute(
                "INSERT INTO feedback_log (id, search_id, entry_id, signal, timestamp) "
                "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                [str(uuid.uuid4()), sid, eid, signal],
            )

        data = await _quality(store, entry_type="session")
        breakdown = data["per_type_breakdown"]
        assert "session" in breakdown
        assert breakdown["session"]["total_feedback"] == 1
        assert breakdown["session"]["positive_count"] == 1
        assert breakdown["session"]["positive_rate"] == 1.0

    async def test_per_type_breakdown_unknown_type_returns_zeros(
        self,
        store: DuckDBStore,
    ) -> None:
        """Per-type breakdown for a type with no feedback returns zero counts."""
        data = await _quality(store, entry_type="reference")
        breakdown = data["per_type_breakdown"]
        # Either key absent or all zeros.
        if "reference" in breakdown:
            assert breakdown["reference"]["total_feedback"] == 0
            assert breakdown["reference"]["positive_count"] == 0
            assert breakdown["reference"]["positive_rate"] == 0.0
