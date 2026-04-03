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
}
"""Ordered mapping of schema version to migration function.

The migration runner executes entries with version > current schema version,
in ascending order.  Each function must be idempotent.
"""
