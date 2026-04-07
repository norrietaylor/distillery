"""Tests for schema migration and _meta version tracking.

Covers:
  T01.2 — _meta version tracking (schema_version, duckdb_version, vss_version)
  T02.x — migration system tests (run_pending_migrations, idempotency, partial)
"""

from __future__ import annotations

import duckdb
import pytest

from distillery.store.duckdb import DuckDBStore  # noqa: E402
from distillery.store.migrations import (
    MIGRATIONS,
    get_current_schema_version,
    run_pending_migrations,
)

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

        # vss_version: present when VSS is available, absent or empty otherwise.
        # We don't assert a specific value since VSS availability varies by
        # environment, but the key should exist if VSS loaded successfully.
        if "vss_version" in rows:
            assert isinstance(rows["vss_version"], str), (
                f"vss_version should be a string, got {type(rows['vss_version'])}"
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
async def test_meta_schema_version_after_init() -> None:
    """schema_version reflects the latest migration after initialization.

    A fresh database runs all pending migrations during ``initialize()``,
    so the schema version should equal the highest migration number (6).
    """
    from distillery.store.migrations import MIGRATIONS

    provider = _MinimalProvider()
    store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
    await store.initialize()

    try:
        conn = store._conn  # type: ignore[attr-defined]
        assert conn is not None

        row = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'").fetchone()
        assert row is not None, "_meta missing schema_version"
        expected = str(max(MIGRATIONS))
        assert row[0] == expected, (
            f"Fresh database schema_version should be {expected!r}, got {row[0]!r}"
        )

    finally:
        await store.close()


# ---------------------------------------------------------------------------
# T02.4: Migration system tests (run_pending_migrations)
# ---------------------------------------------------------------------------

_EXPECTED_TABLES = {"entries", "_meta", "search_log", "feedback_log", "audit_log", "feed_sources"}
_DIMENSIONS = 4


def _table_names(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """Return the set of user-visible table names in the connection."""
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()
    return {row[0] for row in rows}


@pytest.mark.unit
def test_migration_from_zero() -> None:
    """Fresh in-memory DB → run_pending_migrations → schema_version=6, all tables exist."""
    conn = duckdb.connect(":memory:")
    try:
        version = run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)

        assert version == max(MIGRATIONS), f"Expected version {max(MIGRATIONS)}, got {version}"
        assert get_current_schema_version(conn) == max(MIGRATIONS)

        tables = _table_names(conn)
        for expected_table in _EXPECTED_TABLES:
            assert expected_table in tables, f"Table {expected_table!r} missing after migration"
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_idempotent() -> None:
    """Running migrations twice on the same DB produces the same result with no errors."""
    conn = duckdb.connect(":memory:")
    try:
        first = run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)
        second = run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)

        assert first == second == max(MIGRATIONS)
        assert get_current_schema_version(conn) == max(MIGRATIONS)
        assert _table_names(conn) >= _EXPECTED_TABLES
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_partial() -> None:
    """Set schema_version=3 in _meta → run_pending_migrations → only 4,5,6 run → version=6."""
    conn = duckdb.connect(":memory:")
    try:
        # Run migrations 1-3 manually so the base tables exist.
        for v in [1, 2, 3]:
            MIGRATIONS[v](conn, dimensions=_DIMENSIONS, vss_available=False)

        # Set schema_version to 3 to simulate a partially-migrated database.
        conn.execute(
            "INSERT INTO _meta (key, value) VALUES ('schema_version', '3') "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )

        assert get_current_schema_version(conn) == 3

        version = run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)

        assert version == max(MIGRATIONS), f"Expected {max(MIGRATIONS)}, got {version}"
        assert get_current_schema_version(conn) == max(MIGRATIONS)

        # Tables created by migrations 4 and 5 must now exist.
        tables = _table_names(conn)
        for expected_table in {"search_log", "feedback_log", "audit_log", "feed_sources"}:
            assert expected_table in tables, (
                f"Table {expected_table!r} missing after partial migration"
            )
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_failure_rollback() -> None:
    """Injecting a failing migration raises RuntimeError; schema_version unchanged."""
    from unittest.mock import patch

    def _bad_migration(conn: duckdb.DuckDBPyConnection, **kwargs: object) -> None:
        raise ValueError("injected failure")

    # Patch MIGRATIONS to add a failing migration one version beyond the latest.
    next_version = max(MIGRATIONS) + 1
    patched: dict[int, object] = dict(MIGRATIONS)
    patched[next_version] = _bad_migration

    conn = duckdb.connect(":memory:")
    try:
        # Run all real migrations first so we reach a stable state.
        run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)
        assert get_current_schema_version(conn) == max(MIGRATIONS)

        with (
            patch("distillery.store.migrations.MIGRATIONS", patched),
            pytest.raises(RuntimeError, match=f"Migration {next_version} failed"),
        ):
            run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)

        # The schema_version must not have advanced beyond the last successful migration.
        assert get_current_schema_version(conn) == max(MIGRATIONS)
    finally:
        conn.close()


@pytest.mark.unit
def test_get_current_schema_version() -> None:
    """Returns 0 for a fresh DB (no _meta), and the correct version after migrations."""
    conn = duckdb.connect(":memory:")
    try:
        # Fresh DB has no _meta table → version 0.
        assert get_current_schema_version(conn) == 0

        run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)

        assert get_current_schema_version(conn) == max(MIGRATIONS)
    finally:
        conn.close()
