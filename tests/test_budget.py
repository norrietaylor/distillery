"""Tests for the embedding budget tracker and rate limit config."""

from __future__ import annotations

import datetime
from unittest.mock import patch

import duckdb
import pytest

from distillery.config import DistilleryConfig, RateLimitConfig, _validate, load_config
from distillery.mcp.budget import (
    EmbeddingBudgetExceeded,
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
        assert get_daily_usage(conn) == 0

    def test_returns_stored_value(self, conn: duckdb.DuckDBPyConnection) -> None:
        key = f"embed_calls_{datetime.date.today().isoformat()}"
        conn.execute("INSERT INTO _meta VALUES (?, ?)", [key, "42"])
        assert get_daily_usage(conn) == 42


@pytest.mark.unit
class TestIncrementUsage:
    def test_creates_counter_on_first_call(self, conn: duckdb.DuckDBPyConnection) -> None:
        result = increment_usage(conn)
        assert result == 1
        assert get_daily_usage(conn) == 1

    def test_increments_existing_counter(self, conn: duckdb.DuckDBPyConnection) -> None:
        increment_usage(conn, count=5)
        result = increment_usage(conn, count=3)
        assert result == 8

    def test_custom_count(self, conn: duckdb.DuckDBPyConnection) -> None:
        result = increment_usage(conn, count=10)
        assert result == 10


@pytest.mark.unit
class TestCheckBudget:
    def test_passes_when_under_budget(self, conn: duckdb.DuckDBPyConnection) -> None:
        increment_usage(conn, count=5)
        check_budget(conn, daily_limit=10)  # should not raise

    def test_raises_when_at_limit(self, conn: duckdb.DuckDBPyConnection) -> None:
        increment_usage(conn, count=10)
        with pytest.raises(EmbeddingBudgetExceeded) as exc_info:
            check_budget(conn, daily_limit=10)
        assert exc_info.value.used == 10
        assert exc_info.value.limit == 10

    def test_raises_when_over_limit(self, conn: duckdb.DuckDBPyConnection) -> None:
        increment_usage(conn, count=15)
        with pytest.raises(EmbeddingBudgetExceeded):
            check_budget(conn, daily_limit=10)

    def test_unlimited_when_zero(self, conn: duckdb.DuckDBPyConnection) -> None:
        increment_usage(conn, count=9999)
        check_budget(conn, daily_limit=0)  # should not raise


@pytest.mark.unit
class TestRecordAndCheck:
    def test_increments_and_returns_new_total(self, conn: duckdb.DuckDBPyConnection) -> None:
        result = record_and_check(conn, daily_limit=100, count=5)
        assert result == 5

    def test_raises_when_budget_exhausted(self, conn: duckdb.DuckDBPyConnection) -> None:
        increment_usage(conn, count=10)
        with pytest.raises(EmbeddingBudgetExceeded):
            record_and_check(conn, daily_limit=10, count=1)

    def test_tracks_even_when_unlimited(self, conn: duckdb.DuckDBPyConnection) -> None:
        result = record_and_check(conn, daily_limit=0, count=3)
        assert result == 3
        assert get_daily_usage(conn) == 3


# ---------------------------------------------------------------------------
# Unit tests: config
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRateLimitConfig:
    def test_defaults(self) -> None:
        cfg = RateLimitConfig()
        assert cfg.embedding_budget_daily == 500
        assert cfg.max_db_size_mb == 900
        assert cfg.warn_db_size_pct == 80

    def test_validate_negative_budget_raises(self) -> None:
        config = DistilleryConfig(rate_limit=RateLimitConfig(embedding_budget_daily=-1))
        with pytest.raises(ValueError, match="embedding_budget_daily"):
            _validate(config)

    def test_validate_negative_max_db_size_raises(self) -> None:
        config = DistilleryConfig(rate_limit=RateLimitConfig(max_db_size_mb=-1))
        with pytest.raises(ValueError, match="max_db_size_mb"):
            _validate(config)

    def test_validate_warn_pct_out_of_range_raises(self) -> None:
        config = DistilleryConfig(rate_limit=RateLimitConfig(warn_db_size_pct=101))
        with pytest.raises(ValueError, match="warn_db_size_pct"):
            _validate(config)

    def test_validate_zero_budget_is_valid(self) -> None:
        config = DistilleryConfig(rate_limit=RateLimitConfig(embedding_budget_daily=0))
        _validate(config)  # should not raise

    def test_load_config_with_rate_limit_section(self, tmp_path: object) -> None:
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
