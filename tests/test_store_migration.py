"""Tests for schema migration and _meta version tracking.

Covers:
  T01.2 — _meta version tracking (schema_version, duckdb_version, vss_version)
  T02.x — migration system tests (run_pending_migrations, idempotency, partial)
"""

from __future__ import annotations

import duckdb
import pytest

from distillery.store.duckdb import DuckDBStore  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal in-memory embedding provider for migration tests
# ---------------------------------------------------------------------------


class _MinimalProvider:
    """Minimal 4-dimensional embedding provider for migration tests."""

    @property
    def dimensions(self) -> int:
        return 4

    @property
    def model_name(self) -> str:
        return "test-4d"

    def embed(self, text: str) -> list[float]:
        return [0.25, 0.25, 0.25, 0.25]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


# ---------------------------------------------------------------------------
# T01.2: _meta version tracking
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_version_tracking() -> None:
    """After initialize(), _meta must contain schema_version and duckdb_version.

    Verifies:
    - 'schema_version' key exists in _meta with a string value
    - 'duckdb_version' key exists and matches the running DuckDB library version
    - The stored duckdb_version matches duckdb.__version__
    """
    provider = _MinimalProvider()
    store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
    await store.initialize()

    try:
        conn = store._conn  # type: ignore[attr-defined]
        assert conn is not None

        rows = {row[0]: row[1] for row in conn.execute("SELECT key, value FROM _meta").fetchall()}

        # schema_version must be present and be a string representation of an integer
        assert "schema_version" in rows, "_meta missing 'schema_version' key"
        assert rows["schema_version"].isdigit(), (
            f"schema_version should be a numeric string, got {rows['schema_version']!r}"
        )

        # duckdb_version must be present and match the running library version
        assert "duckdb_version" in rows, "_meta missing 'duckdb_version' key"
        assert rows["duckdb_version"] == duckdb.__version__, (
            f"duckdb_version mismatch: stored={rows['duckdb_version']!r}, "
            f"expected={duckdb.__version__!r}"
        )

    finally:
        await store.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_duckdb_version_updated_on_reopen() -> None:
    """duckdb_version in _meta is updated each time _sync_initialize runs.

    Simulates a stored version that differs from the running version (patched)
    and verifies the value is overwritten with the current version.
    """
    provider = _MinimalProvider()
    store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
    await store.initialize()

    try:
        conn = store._conn  # type: ignore[attr-defined]
        assert conn is not None

        # Manually set a fake stored version to simulate an older database
        conn.execute(
            "INSERT INTO _meta (key, value) VALUES ('duckdb_version', '0.0.0') "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value"
        )

        # Re-run _track_version_info directly to simulate re-initialization
        store._track_version_info(conn)  # type: ignore[attr-defined]

        row = conn.execute("SELECT value FROM _meta WHERE key = 'duckdb_version'").fetchone()
        assert row is not None
        assert row[0] == duckdb.__version__, (
            f"Expected duckdb_version to be updated to {duckdb.__version__!r}, got {row[0]!r}"
        )

    finally:
        await store.close()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_meta_schema_version_default_zero() -> None:
    """schema_version defaults to '0' on a fresh database before any migrations."""
    provider = _MinimalProvider()
    store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
    await store.initialize()

    try:
        conn = store._conn  # type: ignore[attr-defined]
        assert conn is not None

        row = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'").fetchone()
        assert row is not None, "_meta missing schema_version"
        assert row[0] == "0", f"Fresh database schema_version should be '0', got {row[0]!r}"

    finally:
        await store.close()
