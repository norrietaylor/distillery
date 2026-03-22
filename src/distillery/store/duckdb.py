"""DuckDB storage backend for Distillery.

Implements the ``DistilleryStore`` protocol using DuckDB with the ``vss``
extension for vector similarity search via HNSW indexing.

This module provides:
  - Connection management with automatic database creation
  - Schema initialisation (``entries`` table with embedding column)
  - VSS extension loading and HNSW index creation
  - Async wrappers around synchronous DuckDB operations

CRUD operations and search methods are added by subsequent tasks (T02.3, T02.4).
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

if TYPE_CHECKING:
    from distillery.embedding.protocol import EmbeddingProvider

logger = logging.getLogger(__name__)

# SQL for the entries table.  The ``embedding`` column uses a fixed-size
# FLOAT array whose length is set at runtime based on the configured
# embedding dimensions.
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
    embedding       FLOAT[{dimensions}]
);
"""

_CREATE_HNSW_INDEX = """
CREATE INDEX IF NOT EXISTS idx_entries_embedding
ON entries
USING HNSW (embedding)
WITH (metric = 'cosine');
"""


class DuckDBStore:
    """DuckDB-backed implementation of the ``DistilleryStore`` protocol.

    The constructor accepts a database path and an embedding provider.  On
    first call to :meth:`initialize`, the database file is created (with
    ``0600`` permissions), the ``entries`` table is defined, the ``vss``
    extension is loaded, and an HNSW index is built on the ``embedding``
    column.

    All public methods are ``async`` -- they wrap synchronous DuckDB calls
    via :func:`asyncio.to_thread` to keep the event loop responsive.

    Parameters
    ----------
    db_path:
        Filesystem path to the DuckDB database file.  The parent directory
        must exist.  Pass ``":memory:"`` for an ephemeral in-memory store
        (useful for tests).
    embedding_provider:
        An object satisfying the ``EmbeddingProvider`` protocol.  Its
        ``dimensions`` property determines the width of the ``embedding``
        column.
    """

    # ------------------------------------------------------------------
    # Construction & lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        db_path: str,
        embedding_provider: "EmbeddingProvider",
    ) -> None:
        self._db_path = db_path
        self._embedding_provider = embedding_provider
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Connection helpers (sync -- called inside asyncio.to_thread)
    # ------------------------------------------------------------------

    def _ensure_parent_dir(self) -> None:
        """Create the parent directory for the database file if needed."""
        if self._db_path == ":memory:":
            return
        parent = Path(self._db_path).parent
        parent.mkdir(parents=True, exist_ok=True)

    def _open_connection(self) -> duckdb.DuckDBPyConnection:
        """Open (or create) the DuckDB database and return a connection."""
        self._ensure_parent_dir()
        conn = duckdb.connect(self._db_path)

        # If we just created the file, lock down permissions.
        if self._db_path != ":memory:" and Path(self._db_path).exists():
            os.chmod(self._db_path, 0o600)

        return conn

    def _setup_vss(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Install and load the vss extension, enable HNSW persistence."""
        conn.execute("INSTALL vss;")
        conn.execute("LOAD vss;")
        conn.execute("SET hnsw_enable_experimental_persistence = true;")
        logger.info("VSS extension loaded with HNSW persistence enabled")

    def _create_schema(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Create the ``entries`` table and HNSW index if they don't exist."""
        dimensions = self._embedding_provider.dimensions
        ddl = _CREATE_ENTRIES_TABLE.format(dimensions=dimensions)
        conn.execute(ddl)
        logger.info(
            "Entries table ready (embedding dimensions=%d)",
            dimensions,
        )

    def _create_index(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Create the HNSW index on the embedding column."""
        try:
            conn.execute(_CREATE_HNSW_INDEX)
            logger.info("HNSW index on entries.embedding ready")
        except duckdb.CatalogException:
            # Index already exists -- safe to ignore.
            logger.debug("HNSW index already exists, skipping creation")

    def _sync_initialize(self) -> None:
        """Synchronous initialisation: open connection, create schema."""
        conn = self._open_connection()
        self._setup_vss(conn)
        self._create_schema(conn)
        self._create_index(conn)
        self._conn = conn
        self._initialized = True
        logger.info("DuckDBStore initialized at %s", self._db_path)

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open the database, create tables, and build the HNSW index.

        This must be called once before any other method.  It is safe to
        call multiple times -- subsequent calls are no-ops.
        """
        if self._initialized:
            return
        await asyncio.to_thread(self._sync_initialize)

    async def close(self) -> None:
        """Close the database connection and release resources."""
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None
            self._initialized = False
            logger.info("DuckDBStore connection closed")

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Return the underlying DuckDB connection.

        Raises
        ------
        RuntimeError
            If :meth:`initialize` has not been called yet.
        """
        if self._conn is None:
            raise RuntimeError(
                "DuckDBStore has not been initialized. "
                "Call 'await store.initialize()' first."
            )
        return self._conn

    @property
    def embedding_provider(self) -> "EmbeddingProvider":
        """Return the configured embedding provider."""
        return self._embedding_provider

    # ------------------------------------------------------------------
    # Stub protocol methods (to be implemented by T02.3 and T02.4)
    # ------------------------------------------------------------------

    async def store(self, entry: Any) -> str:
        """Persist a new entry and return its ID."""
        raise NotImplementedError("store() will be implemented in T02.3")

    async def get(self, entry_id: str) -> Any:
        """Retrieve an entry by its ID."""
        raise NotImplementedError("get() will be implemented in T02.3")

    async def update(self, entry_id: str, updates: dict) -> Any:
        """Apply a partial update to an existing entry."""
        raise NotImplementedError("update() will be implemented in T02.3")

    async def delete(self, entry_id: str) -> bool:
        """Soft-delete an entry by setting its status to ``archived``."""
        raise NotImplementedError("delete() will be implemented in T02.3")

    async def search(
        self,
        query: str,
        filters: dict | None,
        limit: int,
    ) -> list:
        """Perform semantic search with optional metadata filters."""
        raise NotImplementedError("search() will be implemented in T02.4")

    async def find_similar(
        self,
        content: str,
        threshold: float,
        limit: int,
    ) -> list:
        """Find entries whose cosine similarity exceeds *threshold*."""
        raise NotImplementedError("find_similar() will be implemented in T02.4")

    async def list_entries(
        self,
        filters: dict | None,
        limit: int,
        offset: int,
    ) -> list:
        """List entries with optional filtering and pagination."""
        raise NotImplementedError("list_entries() will be implemented in T02.4")
