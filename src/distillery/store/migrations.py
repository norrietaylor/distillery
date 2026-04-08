"""Forward-only schema migration functions for the DuckDB storage backend.

Each migration function is idempotent (uses ``IF NOT EXISTS`` / ``IF NOT
EXISTS`` guards) and accepts a :class:`duckdb.DuckDBPyConnection` as its
first argument.  Additional parameters (``dimensions``, ``vss_available``)
are supplied where the migration requires runtime configuration.

The ``MIGRATIONS`` dict maps integer version numbers (starting at 1) to
their corresponding migration callable.  The migration runner in
:mod:`distillery.store.duckdb` executes pending migrations in order.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, Protocol

import duckdb

logger = logging.getLogger(__name__)


class MigrationFunc(Protocol):
    """Callable protocol for migration functions.

    Migrations accept a DuckDB connection and optional keyword arguments
    for runtime configuration (e.g. ``dimensions``, ``vss_available``).
    """

    def __call__(
        self, conn: duckdb.DuckDBPyConnection, **kwargs: Any
    ) -> None: ...


# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_CREATE_ENTRIES_TABLE = """
CREATE TABLE IF NOT EXISTS entries (
    id              VARCHAR PRIMARY KEY,
    content         VARCHAR NOT NULL,
    entry_type      VARCHAR NOT NULL,
    source          VARCHAR NOT NULL,
    author          VARCHAR NOT NULL,
    project         VARCHAR,
    tags            VARCHAR[] DEFAULT [],
    status          VARCHAR NOT NULL DEFAULT 'active',
    metadata        JSON,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    version         INTEGER NOT NULL DEFAULT 1,
    embedding       FLOAT[{dimensions}],
    created_by      VARCHAR DEFAULT '',
    last_modified_by VARCHAR DEFAULT ''
);
"""

_CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS _meta (
    key   VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);
"""

_CREATE_HNSW_INDEX = """
CREATE INDEX IF NOT EXISTS idx_entries_embedding
ON entries
USING HNSW (embedding)
WITH (metric = 'cosine');
"""

_ADD_ACCESSED_AT_COLUMN = """
ALTER TABLE entries ADD COLUMN IF NOT EXISTS accessed_at TIMESTAMP;
"""

_ADD_OWNERSHIP_COLUMNS = """
ALTER TABLE entries ADD COLUMN IF NOT EXISTS created_by VARCHAR DEFAULT '';
ALTER TABLE entries ADD COLUMN IF NOT EXISTS last_modified_by VARCHAR DEFAULT '';
"""

_CREATE_SEARCH_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS search_log (
    id                 VARCHAR PRIMARY KEY,
    query              VARCHAR NOT NULL,
    result_entry_ids   VARCHAR[],
    result_scores      FLOAT[],
    timestamp          TIMESTAMP NOT NULL DEFAULT current_timestamp,
    session_id         VARCHAR
);
"""

_CREATE_FEEDBACK_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS feedback_log (
    id          VARCHAR PRIMARY KEY,
    search_id   VARCHAR NOT NULL REFERENCES search_log(id),
    entry_id    VARCHAR NOT NULL,
    signal      VARCHAR NOT NULL,
    timestamp   TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

_CREATE_AUDIT_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS audit_log (
    id         VARCHAR PRIMARY KEY,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
    user_id    VARCHAR NOT NULL DEFAULT '',
    tool       VARCHAR NOT NULL,
    entry_id   VARCHAR NOT NULL DEFAULT '',
    action     VARCHAR NOT NULL,
    outcome    VARCHAR NOT NULL
);
"""

_CREATE_FEED_SOURCES_TABLE = """
CREATE TABLE IF NOT EXISTS feed_sources (
    url                    VARCHAR PRIMARY KEY,
    source_type            VARCHAR NOT NULL,
    label                  VARCHAR NOT NULL DEFAULT '',
    poll_interval_minutes  INTEGER NOT NULL DEFAULT 60,
    trust_weight           FLOAT NOT NULL DEFAULT 1.0,
    created_at             TIMESTAMP NOT NULL DEFAULT current_timestamp
);
"""

_CREATE_ENTRY_RELATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS entry_relations (
    id            VARCHAR PRIMARY KEY,
    from_id       VARCHAR NOT NULL,
    to_id         VARCHAR NOT NULL,
    relation_type VARCHAR NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
);
"""

_CREATE_ENTRY_RELATIONS_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_entry_relations_unique
ON entry_relations (from_id, to_id, relation_type);
"""


# ---------------------------------------------------------------------------
# Migration functions
# ---------------------------------------------------------------------------


def initial_schema(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 1: Create the ``entries`` and ``_meta`` tables.

    Requires ``dimensions`` in *kwargs* to set the embedding column width.
    """
    dimensions: int = kwargs["dimensions"]
    ddl = _CREATE_ENTRIES_TABLE.format(dimensions=dimensions)
    conn.execute(ddl)
    conn.execute(_CREATE_META_TABLE)
    logger.info("Migration 1: entries + _meta tables created (dimensions=%d)", dimensions)


def add_accessed_at(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 2: Add ``accessed_at`` column to ``entries``."""
    conn.execute(_ADD_ACCESSED_AT_COLUMN)
    logger.info("Migration 2: accessed_at column added")


def add_ownership_columns(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 3: Add ``created_by`` and ``last_modified_by`` columns."""
    for stmt in _ADD_OWNERSHIP_COLUMNS.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    logger.info("Migration 3: ownership columns added")


def create_log_tables(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 4: Create ``search_log``, ``feedback_log``, and ``audit_log`` tables."""
    conn.execute(_CREATE_SEARCH_LOG_TABLE)
    conn.execute(_CREATE_FEEDBACK_LOG_TABLE)
    conn.execute(_CREATE_AUDIT_LOG_TABLE)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_search_log_timestamp ON search_log (timestamp)"
    )
    logger.info("Migration 4: search_log, feedback_log, audit_log tables created")


def create_feed_sources(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 5: Create the ``feed_sources`` table."""
    conn.execute(_CREATE_FEED_SOURCES_TABLE)
    logger.info("Migration 5: feed_sources table created")


def create_hnsw_index(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 6: Create HNSW cosine index on ``entries.embedding``.

    Requires ``vss_available`` in *kwargs*.  When VSS is not available the
    migration is a no-op (brute-force cosine distance is still correct).
    """
    vss_available: bool = kwargs.get("vss_available", False)
    if not vss_available:
        logger.info("Migration 6: skipping HNSW index (VSS not available)")
        return
    try:
        conn.execute(_CREATE_HNSW_INDEX)
        logger.info("Migration 6: HNSW cosine index created")
    except duckdb.CatalogException:
        logger.debug("Migration 6: HNSW index already exists, skipping")
    except duckdb.BinderException:
        logger.warning("Migration 6: HNSW index type not recognized, skipping")


def create_entry_relations(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 8: Create ``entry_relations`` table and backfill from metadata.

    Creates the ``entry_relations`` table for typed, queryable relationships
    between entries.  After table creation, backfills existing entries whose
    ``metadata`` JSON column contains a ``related_entries`` list: each element
    is inserted as a row with ``relation_type='link'``.

    The backfill is idempotent because the ``CREATE TABLE IF NOT EXISTS`` guard
    means this migration is only executed once per database.
    """
    import json
    import uuid

    conn.execute(_CREATE_ENTRY_RELATIONS_TABLE)
    conn.execute(_CREATE_ENTRY_RELATIONS_UNIQUE_INDEX)
    logger.info("Migration 8: entry_relations table created")

    # Backfill: scan all entries whose metadata contains a 'related_entries' list.
    # Collect all existing entry IDs so we only create relations to valid targets.
    existing_ids: set[str] = {
        r[0] for r in conn.execute("SELECT id FROM entries").fetchall()
    }
    rows = conn.execute("SELECT id, metadata FROM entries WHERE metadata IS NOT NULL").fetchall()
    backfilled = 0
    for entry_id, metadata_raw in rows:
        try:
            if isinstance(metadata_raw, str):
                meta = json.loads(metadata_raw)
            elif isinstance(metadata_raw, dict):
                meta = metadata_raw
            else:
                continue
        except (json.JSONDecodeError, TypeError):
            continue

        related: object = meta.get("related_entries")
        if not isinstance(related, list):
            continue

        for to_id in related:
            if not isinstance(to_id, str) or not to_id:
                continue
            if to_id not in existing_ids:
                continue
            relation_id = str(uuid.uuid4())
            conn.execute(
                "INSERT OR IGNORE INTO entry_relations (id, from_id, to_id, relation_type) "
                "VALUES (?, ?, ?, 'link')",
                [relation_id, entry_id, to_id],
            )
            backfilled += 1

    if backfilled:
        logger.info("Migration 8: backfilled %d entry_relations rows from metadata", backfilled)
    else:
        logger.debug("Migration 8: no metadata.related_entries found to backfill")


def create_fts_index(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 7: Install FTS extension and create full-text index on ``entries.content``.

    Uses ``PRAGMA create_fts_index`` with ``overwrite=1`` so the migration is
    idempotent — re-running it rebuilds the index rather than raising an error.

    Sets ``kwargs["fts_available"]`` to ``True`` on success or ``False`` when
    the extension cannot be loaded.  Callers that pass a shared mutable dict
    via keyword arguments can inspect ``fts_available`` afterwards.

    When the FTS extension is unavailable (e.g. offline environment or
    restricted DuckDB build) the migration degrades gracefully: it logs a
    warning and records ``fts_available=False`` without raising.
    """
    try:
        conn.execute("INSTALL fts")
        conn.execute("LOAD fts")
        conn.execute("PRAGMA create_fts_index('entries', 'id', 'content', overwrite=1)")
        kwargs["fts_available"] = True
        logger.info("Migration 7: FTS extension loaded and index created on entries.content")
    except duckdb.IOException as exc:
        # Extension install requires network access; gracefully degrade.
        kwargs["fts_available"] = False
        logger.warning("Migration 7: FTS extension install failed (offline?): %s", exc)
    except Exception:
        logger.exception("Migration 7: unexpected FTS index creation failure")
        raise


# ---------------------------------------------------------------------------
# Migration registry
# ---------------------------------------------------------------------------

MIGRATIONS: dict[int, MigrationFunc] = {
    1: initial_schema,
    2: add_accessed_at,
    3: add_ownership_columns,
    4: create_log_tables,
    5: create_feed_sources,
    6: create_hnsw_index,
    7: create_fts_index,
    8: create_entry_relations,
}
"""Ordered mapping of schema version to migration function.

The migration runner executes entries with version > current schema version,
in ascending order.  Each function must be idempotent.
"""


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


def get_current_schema_version(conn: duckdb.DuckDBPyConnection) -> int:
    """Read the current schema version from the ``_meta`` table.

    Returns ``0`` if the ``_meta`` table does not exist or the
    ``schema_version`` key has not been set.
    """
    try:
        result = conn.execute(
            "SELECT value FROM _meta WHERE key = 'schema_version'"
        )
        row = result.fetchone()
        if row is not None:
            return int(row[0])
    except duckdb.CatalogException:
        # _meta table does not exist yet.
        pass
    return 0


def run_pending_migrations(
    conn: duckdb.DuckDBPyConnection,
    *,
    dimensions: int,
    vss_available: bool,
) -> int:
    """Execute pending migrations and return the resulting schema version.

    Migrations with version numbers greater than the current schema version
    are executed in ascending order.  Each migration runs inside its own
    transaction; on failure the transaction is rolled back and a
    ``RuntimeError`` is raised.

    After all pending migrations succeed the ``schema_version`` key in
    ``_meta`` is updated to the highest applied version.

    Parameters
    ----------
    conn:
        An open DuckDB connection.
    dimensions:
        Embedding vector width (required by migration 1).
    vss_available:
        Whether the VSS extension is loaded (required by migration 6).

    Returns
    -------
    int
        The schema version after all pending migrations have been applied.
    """
    current = get_current_schema_version(conn)
    pending = sorted(v for v in MIGRATIONS if v > current)

    if not pending:
        logger.debug("Schema is up-to-date at version %d", current)
        return current

    kwargs: dict[str, Any] = {
        "dimensions": dimensions,
        "vss_available": vss_available,
    }

    for version in pending:
        migration = MIGRATIONS[version]
        logger.info("Running migration %d …", version)
        try:
            conn.execute("BEGIN TRANSACTION")
            migration(conn, **kwargs)
            # Advance schema_version inside the same transaction so it stays
            # in sync even if a later migration fails.
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                [str(version)],
            )
            conn.execute("COMMIT")
        except (duckdb.TransactionException, duckdb.ConstraintException):
            # Re-raise retriable DuckDB exceptions so the caller's retry
            # loop in _sync_initialize can handle them.
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise
        except Exception as exc:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise RuntimeError(
                f"Migration {version} failed: {exc}"
            ) from exc

    new_version = pending[-1]
    logger.info("Schema migrated from version %d to %d", current, new_version)
    return new_version
