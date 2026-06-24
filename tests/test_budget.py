"""Tests for the embedding budget tracker and rate limit config."""

from __future__ import annotations

import datetime

import duckdb
import pytest

from distillery.config import DistilleryConfig, RateLimitConfig, _validate, load_config
from distillery.mcp.budget import (
    EmbeddingBudgetError,
    check_budget,
    get_daily_usage,
    increment_usage,
    record_and_check,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB connection with the _meta table."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE _meta (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)")
    return c


# ---------------------------------------------------------------------------
# Unit tests: budget tracker
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetDailyUsage:
    def test_returns_zero_when_no_usage(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Zero is returned when no embedding calls have been recorded today."""
        assert get_daily_usage(conn) == 0

    def test_returns_stored_value(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Previously stored counter value is returned correctly."""
        key = f"embed_calls_{datetime.date.today().isoformat()}"
        conn.execute("INSERT INTO _meta VALUES (?, ?)", [key, "42"])
        assert get_daily_usage(conn) == 42


@pytest.mark.unit
class TestIncrementUsage:
    def test_creates_counter_on_first_call(self, conn: duckdb.DuckDBPyConnection) -> None:
        """First increment creates the counter and returns 1."""
        result = increment_usage(conn)
        assert result == 1
        assert get_daily_usage(conn) == 1

    def test_increments_existing_counter(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Subsequent increments accumulate correctly."""
        increment_usage(conn, count=5)
        result = increment_usage(conn, count=3)
        assert result == 8

    def test_custom_count(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Custom count value is applied on first call."""
        result = increment_usage(conn, count=10)
        assert result == 10


@pytest.mark.unit
class TestCheckBudget:
    def test_passes_when_under_budget(self, conn: duckdb.DuckDBPyConnection) -> None:
        """No error raised when usage is below the daily limit."""
        increment_usage(conn, count=5)
        check_budget(conn, daily_limit=10)  # should not raise

    def test_raises_when_at_limit(self, conn: duckdb.DuckDBPyConnection) -> None:
        """EmbeddingBudgetError raised when usage equals the daily limit."""
        increment_usage(conn, count=10)
        with pytest.raises(EmbeddingBudgetError) as exc_info:
            check_budget(conn, daily_limit=10)
        assert exc_info.value.used == 10
        assert exc_info.value.limit == 10

    def test_raises_when_over_limit(self, conn: duckdb.DuckDBPyConnection) -> None:
        """EmbeddingBudgetError raised when usage exceeds the daily limit."""
        increment_usage(conn, count=15)
        with pytest.raises(EmbeddingBudgetError):
            check_budget(conn, daily_limit=10)

    def test_unlimited_when_zero(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Zero daily_limit disables the budget check entirely."""
        increment_usage(conn, count=9999)
        check_budget(conn, daily_limit=0)  # should not raise


@pytest.mark.unit
class TestRecordAndCheck:
    def test_increments_and_returns_new_total(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Records usage and returns the new daily total."""
        result = record_and_check(conn, daily_limit=100, count=5)
        assert result == 5

    def test_raises_when_budget_exhausted(self, conn: duckdb.DuckDBPyConnection) -> None:
        """EmbeddingBudgetError raised when budget is already exhausted."""
        increment_usage(conn, count=10)
        with pytest.raises(EmbeddingBudgetError):
            record_and_check(conn, daily_limit=10, count=1)

    def test_raises_when_count_would_exceed_budget(self, conn: duckdb.DuckDBPyConnection) -> None:
        """EmbeddingBudgetError raised when used + count would exceed the limit."""
        increment_usage(conn, count=499)
        with pytest.raises(EmbeddingBudgetError):
            record_and_check(conn, daily_limit=500, count=2)

    def test_tracks_even_when_unlimited(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Usage is still tracked when the budget is unlimited (daily_limit=0)."""
        result = record_and_check(conn, daily_limit=0, count=3)
        assert result == 3
        assert get_daily_usage(conn) == 3


# ---------------------------------------------------------------------------
# Unit tests: concurrency (issue #608)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConcurrentAccess:
    """Regression tests for the concurrent budget-counter write race.

    Originally (issue #608) a module-level ``_write_lock`` serialized direct
    multithreaded calls to the budget functions on one shared connection.  The
    #655 fix moves that serialization to the store: production callers reach the
    counter only via :meth:`DuckDBStore.record_embedding_usage`, which runs the
    upsert under the store's ``_conn_lock``.  These tests exercise that path —
    concurrent ``record_embedding_usage`` calls must never raise
    ``Conflict on update`` / duplicate-key / aborted-transaction errors, must
    count exactly, and must not overspend the cap.
    """

    async def test_concurrent_record_usage_does_not_raise(self, store: object) -> None:
        """Concurrent record_embedding_usage calls through the store succeed."""
        import asyncio

        n_tasks = 8
        iterations = 25

        async def worker() -> None:
            for _ in range(iterations):
                await store.record_embedding_usage(count=1, daily_limit=10_000_000)

        await asyncio.gather(*(worker() for _ in range(n_tasks)))

        assert get_daily_usage(store.connection) == n_tasks * iterations

    async def test_concurrent_increments_count_correctly(self, store: object) -> None:
        """The _meta counter reflects every concurrent increment exactly once."""
        import asyncio

        n_tasks = 6
        iterations = 20

        async def worker() -> None:
            for _ in range(iterations):
                await store.record_embedding_usage(count=1, daily_limit=0)

        await asyncio.gather(*(worker() for _ in range(n_tasks)))

        assert get_daily_usage(store.connection) == n_tasks * iterations

    async def test_concurrent_record_usage_cannot_overspend(self, store: object) -> None:
        """Concurrent record_embedding_usage calls never push usage past daily_limit."""
        import asyncio

        daily_limit = 10
        n_tasks = 8
        iterations = 5  # 40 attempted calls against a limit of 10
        successes: list[int] = []

        async def worker() -> None:
            for _ in range(iterations):
                try:
                    await store.record_embedding_usage(count=1, daily_limit=daily_limit)
                except EmbeddingBudgetError:
                    pass  # expected once the cap is reached
                else:
                    successes.append(1)

        await asyncio.gather(*(worker() for _ in range(n_tasks)))

        assert len(successes) == daily_limit
        assert get_daily_usage(store.connection) == daily_limit


@pytest.mark.unit
class TestStoreRecordEmbeddingUsage:
    """The serialized store wrapper increments and still enforces the budget (#655)."""

    async def test_increments_counter(self, store: object) -> None:
        """record_embedding_usage adds to today's counter and returns the total."""
        total = await store.record_embedding_usage(count=3, daily_limit=100)
        assert total == 3
        assert get_daily_usage(store.connection) == 3
        total = await store.record_embedding_usage(count=2, daily_limit=100)
        assert total == 5

    async def test_propagates_budget_error_when_over_limit(self, store: object) -> None:
        """EmbeddingBudgetError still propagates unchanged through the store path."""
        await store.record_embedding_usage(count=10, daily_limit=10)
        with pytest.raises(EmbeddingBudgetError):
            await store.record_embedding_usage(count=1, daily_limit=10)


# ---------------------------------------------------------------------------
# Unit tests: config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRateLimitConfig:
    def test_defaults(self) -> None:
        """Default values are 0 (unlimited) / 900 / 80.

        As of issue #351 ``embedding_budget_daily`` defaults to ``0`` so
        the provider's own rate limiter is the source of truth. Users can
        opt into a hard cost ceiling by setting a positive integer.
        """
        cfg = RateLimitConfig()
        assert cfg.embedding_budget_daily == 0
        assert cfg.max_db_size_mb == 900
        assert cfg.warn_db_size_pct == 80

    def test_load_config_without_rate_limit_section_defaults_to_unlimited(
        self, tmp_path: object
    ) -> None:
        """Omitting ``rate_limit`` from YAML yields unlimited embedding budget."""
        import pathlib

        p = pathlib.Path(str(tmp_path)) / "empty.yaml"
        # Provide the minimum valid config: an empty mapping.
        p.write_text("{}\n")
        config = load_config(str(p))
        assert config.rate_limit.embedding_budget_daily == 0

    def test_validate_negative_budget_raises(self) -> None:
        """Negative embedding_budget_daily is rejected by validation."""
        config = DistilleryConfig(rate_limit=RateLimitConfig(embedding_budget_daily=-1))
        with pytest.raises(ValueError, match="embedding_budget_daily"):
            _validate(config)

    def test_validate_negative_max_db_size_raises(self) -> None:
        """Negative max_db_size_mb is rejected by validation."""
        config = DistilleryConfig(rate_limit=RateLimitConfig(max_db_size_mb=-1))
        with pytest.raises(ValueError, match="max_db_size_mb"):
            _validate(config)

    def test_validate_warn_pct_out_of_range_raises(self) -> None:
        """warn_db_size_pct above 100 is rejected by validation."""
        config = DistilleryConfig(rate_limit=RateLimitConfig(warn_db_size_pct=101))
        with pytest.raises(ValueError, match="warn_db_size_pct"):
            _validate(config)

    def test_validate_zero_budget_is_valid(self) -> None:
        """Zero embedding_budget_daily (unlimited) passes validation."""
        config = DistilleryConfig(rate_limit=RateLimitConfig(embedding_budget_daily=0))
        _validate(config)  # should not raise

    def test_load_config_with_rate_limit_section(self, tmp_path: object) -> None:
        """YAML rate_limit section is parsed into RateLimitConfig correctly."""
        import pathlib

        p = pathlib.Path(str(tmp_path)) / "test.yaml"
        p.write_text(
            "rate_limit:\n"
            "  embedding_budget_daily: 100\n"
            "  max_db_size_mb: 500\n"
            "  warn_db_size_pct: 90\n"
        )
        config = load_config(str(p))
        assert config.rate_limit.embedding_budget_daily == 100
        assert config.rate_limit.max_db_size_mb == 500
        assert config.rate_limit.warn_db_size_pct == 90
