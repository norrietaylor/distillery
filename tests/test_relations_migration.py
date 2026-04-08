"""Tests for migration 8 — entry_relations table creation and backfill.

Covers:
  - Migration 8 creates the entry_relations table with correct columns
  - Backfill inserts rows from metadata.related_entries with relation_type='link'
  - Backfill skips entries with no related_entries in metadata
  - Backfill is idempotent (migration only runs once per DB)
  - Migration runs in sequence after migration 7 (full migration from zero)
"""

from __future__ import annotations

import json
import uuid

import duckdb
import pytest

from distillery.store.migrations import (
    MIGRATIONS,
    create_entry_relations,
    run_pending_migrations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIMENSIONS = 4
_EMBEDDING = [0.25, 0.25, 0.25, 0.25]


def _setup_db_through_migration_7(conn: duckdb.DuckDBPyConnection) -> None:
    """Run migrations 1–7 so the entries table exists and is ready for backfill tests."""
    for v in range(1, 8):
        MIGRATIONS[v](conn, dimensions=_DIMENSIONS, vss_available=False)
    conn.execute(
        "INSERT INTO _meta (key, value) VALUES ('schema_version', '7') "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
    )


def _insert_entry(
    conn: duckdb.DuckDBPyConnection,
    entry_id: str,
    metadata: dict | None = None,
) -> None:
    """Insert a minimal entry row directly."""
    meta_json = json.dumps(metadata) if metadata else None
    conn.execute(
        "INSERT INTO entries (id, content, entry_type, source, author, metadata, embedding) "
        "VALUES (?, 'test content', 'inbox', 'manual', 'tester', ?, ?)",
        [entry_id, meta_json, _EMBEDDING],
    )


# ---------------------------------------------------------------------------
# Test: table structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_8_creates_table() -> None:
    """Migration 8 creates the entry_relations table with the expected columns."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_db_through_migration_7(conn)
        create_entry_relations(conn)

        # Verify table exists
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_name = 'entry_relations'"
        ).fetchall()
        assert rows, "entry_relations table was not created"

        # Verify columns
        cols = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'entry_relations'"
            ).fetchall()
        }
        assert "id" in cols, "id column missing"
        assert "from_id" in cols, "from_id column missing"
        assert "to_id" in cols, "to_id column missing"
        assert "relation_type" in cols, "relation_type column missing"
        assert "created_at" in cols, "created_at column missing"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test: backfill
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_8_backfill_inserts_link_rows() -> None:
    """Backfill inserts rows from metadata.related_entries with relation_type='link'."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_db_through_migration_7(conn)

        entry_a = str(uuid.uuid4())
        entry_b = str(uuid.uuid4())
        entry_c = str(uuid.uuid4())

        # entry_a has related_entries pointing at entry_b and entry_c
        _insert_entry(conn, entry_a, metadata={"related_entries": [entry_b, entry_c]})
        _insert_entry(conn, entry_b)
        _insert_entry(conn, entry_c)

        create_entry_relations(conn)

        rows = conn.execute(
            "SELECT from_id, to_id, relation_type FROM entry_relations ORDER BY to_id"
        ).fetchall()

        assert len(rows) == 2, f"Expected 2 backfill rows, got {len(rows)}"
        from_ids = {r[0] for r in rows}
        to_ids = {r[1] for r in rows}
        types = {r[2] for r in rows}

        assert from_ids == {entry_a}
        assert to_ids == {entry_b, entry_c}
        assert types == {"link"}
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_8_backfill_skips_no_related_entries() -> None:
    """Entries with no related_entries in metadata produce no backfill rows."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_db_through_migration_7(conn)

        entry_a = str(uuid.uuid4())
        _insert_entry(conn, entry_a, metadata={"tags": ["python"], "note": "no relations here"})

        create_entry_relations(conn)

        count = conn.execute("SELECT COUNT(*) FROM entry_relations").fetchone()[0]
        assert count == 0, f"Expected 0 backfill rows, got {count}"
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_8_backfill_skips_null_metadata() -> None:
    """Entries with NULL metadata are skipped cleanly."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_db_through_migration_7(conn)

        entry_a = str(uuid.uuid4())
        _insert_entry(conn, entry_a, metadata=None)

        create_entry_relations(conn)

        count = conn.execute("SELECT COUNT(*) FROM entry_relations").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_8_backfill_ignores_non_string_related_entries() -> None:
    """Non-string values in related_entries list are silently skipped."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_db_through_migration_7(conn)

        entry_a = str(uuid.uuid4())
        # Mix of valid IDs, None, int, empty string — only valid strings should be inserted
        entry_b = str(uuid.uuid4())
        _insert_entry(
            conn,
            entry_a,
            metadata={"related_entries": [entry_b, None, 42, "", "valid-but-no-target"]},
        )
        _insert_entry(conn, entry_b)

        create_entry_relations(conn)

        rows = conn.execute("SELECT to_id FROM entry_relations").fetchall()
        to_ids = {r[0] for r in rows}
        # entry_b exists in entries table so it should be linked
        assert entry_b in to_ids
        # "valid-but-no-target" is a non-empty string but no entry exists with
        # that ID, so the migration must skip it
        assert "valid-but-no-target" not in to_ids
        # None and 42 must NOT be in results
        assert None not in to_ids
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test: full migration sequence
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_migration_8_runs_in_full_sequence() -> None:
    """run_pending_migrations from zero produces schema_version=8 with entry_relations table."""
    conn = duckdb.connect(":memory:")
    try:
        version = run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)

        assert version == 9, f"Expected schema version 9, got {version}"

        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "entry_relations" in tables, "entry_relations table missing after full migration"
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_8_idempotent() -> None:
    """Running all migrations twice leaves entry_relations intact with no errors."""
    conn = duckdb.connect(":memory:")
    try:
        first = run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)
        second = run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)

        assert first == second == 9
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "entry_relations" in tables
    finally:
        conn.close()


@pytest.mark.unit
def test_migration_8_partial_from_7() -> None:
    """Starting from schema_version=7 applies migrations 8 and 9."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_db_through_migration_7(conn)

        version = run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)

        assert version == 9
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "entry_relations" in tables
    finally:
        conn.close()
