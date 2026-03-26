"""DuckDB storage backend for Distillery.

Implements the ``DistilleryStore`` protocol using DuckDB with the ``vss``
extension for vector similarity search via HNSW indexing.

This module provides:
  - Connection management with automatic database creation
  - Schema initialisation (``entries`` table with embedding column)
  - VSS extension loading and HNSW index creation
  - Async wrappers around synchronous DuckDB operations

CRUD operations are added by T02.3; search, find_similar, and list_entries
are implemented below (T02.4).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from distillery.models import Entry, EntryStatus

if TYPE_CHECKING:
    from distillery.embedding.protocol import EmbeddingProvider
    from distillery.store.protocol import SearchResult

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

_CREATE_META_TABLE = """
CREATE TABLE IF NOT EXISTS _meta (
    key   VARCHAR PRIMARY KEY,
    value VARCHAR NOT NULL
);
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
        embedding_provider: EmbeddingProvider,
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

    def _create_meta_table(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Create the ``_meta`` table if it does not exist."""
        conn.execute(_CREATE_META_TABLE)

    def _create_log_tables(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Create the ``search_log`` and ``feedback_log`` tables if they don't exist."""
        conn.execute(_CREATE_SEARCH_LOG_TABLE)
        conn.execute(_CREATE_FEEDBACK_LOG_TABLE)
        logger.info("search_log and feedback_log tables ready")

    def _validate_or_record_meta(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Validate or record the embedding model metadata.

        On first use the configured model name and dimensions are persisted
        in the ``_meta`` table.  On subsequent opens the stored values are
        compared with the configured provider; a mismatch raises
        ``RuntimeError`` to prevent mixed-model embeddings.
        """
        result = conn.execute(
            "SELECT key, value FROM _meta WHERE key IN "
            "('embedding_model', 'embedding_dimensions')"
        )
        rows = {row[0]: row[1] for row in result.fetchall()}

        model = self._embedding_provider.model_name
        dims = str(self._embedding_provider.dimensions)

        if not rows:
            # First use -- record the model metadata.
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES (?, ?)",
                ["embedding_model", model],
            )
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES (?, ?)",
                ["embedding_dimensions", dims],
            )
            logger.info(
                "Recorded embedding metadata: model=%s, dimensions=%s",
                model,
                dims,
            )
            return

        stored_model = rows.get("embedding_model")
        stored_dims = rows.get("embedding_dimensions")

        if stored_model is not None and stored_model != model:
            raise RuntimeError(
                f"Embedding model mismatch: database was populated with "
                f"{stored_model!r} but the configured provider uses "
                f"{model!r}. Using different models would produce "
                f"incompatible embeddings."
            )

        if stored_dims is not None and stored_dims != dims:
            raise RuntimeError(
                f"Embedding dimensions mismatch: database was populated with "
                f"{stored_dims} dimensions but the configured provider uses "
                f"{dims}. Using different dimensions would produce "
                f"incompatible embeddings."
            )

    def _sync_initialize(self) -> None:
        """Synchronous initialisation: open connection, create schema."""
        conn = self._open_connection()
        self._setup_vss(conn)
        self._create_schema(conn)
        self._create_log_tables(conn)
        self._create_meta_table(conn)
        self._validate_or_record_meta(conn)
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
    def embedding_provider(self) -> EmbeddingProvider:
        """Return the configured embedding provider."""
        return self._embedding_provider

    # ------------------------------------------------------------------
    # CRUD protocol methods (T02.3)
    # ------------------------------------------------------------------

    # Fields that callers may never overwrite via update().
    _IMMUTABLE_FIELDS = frozenset({"id", "created_at", "source"})

    def _sync_store(self, entry: Entry) -> str:
        """Synchronous implementation of store(); called via asyncio.to_thread."""
        conn = self.connection
        embedding = self._embedding_provider.embed(entry.content)

        sql = (
            "INSERT INTO entries "
            "(id, content, entry_type, source, author, project, tags, status, "
            " metadata, created_at, updated_at, version, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        params = [
            entry.id,
            entry.content,
            entry.entry_type.value,
            entry.source.value,
            entry.author,
            entry.project,
            list(entry.tags),
            entry.status.value,
            json.dumps(entry.metadata),
            entry.created_at,
            entry.updated_at,
            entry.version,
            embedding,
        ]
        conn.execute(sql, params)
        logger.debug("Stored entry id=%s", entry.id)
        return entry.id

    async def store(self, entry: Entry) -> str:
        """Persist a new entry and return its ID.

        The entry's content is embedded via the configured embedding provider
        before insertion.

        Returns:
            The UUID string of the stored entry.
        """
        return await asyncio.to_thread(self._sync_store, entry)

    def _sync_get(self, entry_id: str) -> Entry | None:
        """Synchronous implementation of get(); called via asyncio.to_thread."""
        conn = self.connection
        sql = (
            f"SELECT {self._ENTRY_COLUMNS} FROM entries WHERE id = ?"
        )
        result = conn.execute(sql, [entry_id])
        col_names = [desc[0] for desc in result.description]
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_entry(row, col_names)

    async def get(self, entry_id: str) -> Entry | None:
        """Retrieve an entry by its ID.

        Returns:
            The matching ``Entry``, or ``None`` if the ID does not exist.
        """
        return await asyncio.to_thread(self._sync_get, entry_id)

    def _sync_update(self, entry_id: str, updates: dict[str, Any]) -> Entry:
        """Synchronous implementation of update(); called via asyncio.to_thread."""
        # Reject attempts to change immutable fields.
        bad_keys = self._IMMUTABLE_FIELDS & updates.keys()
        if bad_keys:
            raise ValueError(
                f"Cannot update immutable field(s): {', '.join(sorted(bad_keys))}"
            )

        conn = self.connection

        # Verify the entry exists first.
        check_sql = "SELECT id FROM entries WHERE id = ?"
        check_result = conn.execute(check_sql, [entry_id])
        if check_result.fetchone() is None:
            raise KeyError(f"No entry found with id={entry_id!r}")

        now = datetime.now(tz=UTC)

        # Build SET clause from the caller-supplied updates plus system fields.
        set_parts: list[str] = []
        set_params: list[Any] = []

        for key, value in updates.items():
            set_parts.append(f"{key} = ?")
            # Serialise enum values to their string representation.
            if hasattr(value, "value"):
                set_params.append(value.value)
            elif key == "metadata" and isinstance(value, dict):
                set_params.append(json.dumps(value))
            elif key == "tags" and isinstance(value, list):
                set_params.append(list(value))
            else:
                set_params.append(value)

        # Re-embed when content changes.
        if "content" in updates:
            new_embedding = self._embedding_provider.embed(updates["content"])
            set_parts.append("embedding = ?")
            set_params.append(new_embedding)

        # Always increment version and refresh updated_at.
        set_parts.append("version = version + 1")
        set_parts.append("updated_at = ?")
        set_params.append(now)

        set_sql = ", ".join(set_parts)
        sql = f"UPDATE entries SET {set_sql} WHERE id = ?"
        set_params.append(entry_id)

        conn.execute(sql, set_params)
        logger.debug("Updated entry id=%s", entry_id)

        # Re-fetch to return the updated state.
        fetch_result = conn.execute(
            f"SELECT {self._ENTRY_COLUMNS} FROM entries WHERE id = ?",
            [entry_id],
        )
        col_names = [desc[0] for desc in fetch_result.description]
        row = fetch_result.fetchone()
        if row is None:  # pragma: no cover -- shouldn't happen after update
            raise KeyError(f"Entry disappeared after update: id={entry_id!r}")
        return self._row_to_entry(row, col_names)

    async def update(self, entry_id: str, updates: dict[str, Any]) -> Entry:
        """Apply a partial update to an existing entry.

        Increments ``version`` by 1 and refreshes ``updated_at`` to the
        current UTC time.  Attempts to update ``id``, ``created_at``, or
        ``source`` are rejected with a ``ValueError``.

        Raises:
            ValueError: If ``updates`` contains any immutable field.
            KeyError: If no entry with ``entry_id`` exists.

        Returns:
            The updated ``Entry``.
        """
        return await asyncio.to_thread(self._sync_update, entry_id, updates)

    def _sync_delete(self, entry_id: str) -> bool:
        """Synchronous implementation of delete(); called via asyncio.to_thread."""
        conn = self.connection
        now = datetime.now(tz=UTC)
        sql = (
            "UPDATE entries SET status = ?, updated_at = ? WHERE id = ?"
        )
        conn.execute(sql, [EntryStatus.ARCHIVED.value, now, entry_id])

        # Check whether any row was actually affected by inspecting row count.
        count_result = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE id = ? AND status = ?",
            [entry_id, EntryStatus.ARCHIVED.value],
        )
        count_row = count_result.fetchone()
        count: int = count_row[0] if count_row is not None else 0
        found = count > 0
        if found:
            logger.debug("Soft-deleted (archived) entry id=%s", entry_id)
        else:
            logger.debug("delete() called for non-existent entry id=%s", entry_id)
        return found

    async def delete(self, entry_id: str) -> bool:
        """Soft-delete an entry by setting its status to ``archived``.

        Returns:
            ``True`` if the entry was found and archived, ``False`` otherwise.
        """
        return await asyncio.to_thread(self._sync_delete, entry_id)

    # ------------------------------------------------------------------
    # Filter helpers (shared by search, find_similar, list_entries)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter_clauses(
        filters: dict[str, Any] | None,
    ) -> tuple[list[str], list[Any]]:
        """Translate a user-facing filter dict into SQL WHERE fragments.

        Returns a tuple of ``(clauses, params)`` where each clause is a SQL
        expression using ``?`` placeholders and *params* contains the
        corresponding bind values in order.

        Supported filter keys
        ---------------------
        - ``entry_type`` (str | list[str])
        - ``author`` (str)
        - ``project`` (str)
        - ``tags`` (list[str]) -- matches entries containing *any* listed tag
        - ``status`` (str)
        - ``date_from`` (datetime | str) -- inclusive lower bound on ``created_at``
        - ``date_to`` (datetime | str) -- inclusive upper bound on ``created_at``
        """
        if not filters:
            return [], []

        clauses: list[str] = []
        params: list[Any] = []

        if "entry_type" in filters:
            val = filters["entry_type"]
            if isinstance(val, list):
                placeholders = ", ".join("?" for _ in val)
                clauses.append(f"entry_type IN ({placeholders})")
                params.extend(str(v) for v in val)
            else:
                clauses.append("entry_type = ?")
                params.append(str(val))

        if "author" in filters:
            clauses.append("author = ?")
            params.append(filters["author"])

        if "project" in filters:
            clauses.append("project = ?")
            params.append(filters["project"])

        if "tags" in filters:
            tag_list = filters["tags"]
            if tag_list:
                # list_has_any checks whether the tags array shares any
                # element with the provided list.
                clauses.append("list_has_any(tags, ?)")
                params.append(tag_list)

        if "status" in filters:
            clauses.append("status = ?")
            params.append(str(filters["status"]))

        if "date_from" in filters:
            val = filters["date_from"]
            if isinstance(val, str):
                val = datetime.fromisoformat(val)
            clauses.append("created_at >= ?")
            params.append(val)

        if "date_to" in filters:
            val = filters["date_to"]
            if isinstance(val, str):
                val = datetime.fromisoformat(val)
            clauses.append("created_at <= ?")
            params.append(val)

        return clauses, params

    def _row_to_entry(self, row: tuple[Any, ...], columns: list[str]) -> Entry:
        """Convert a DuckDB result row into an ``Entry`` instance.

        Parameters
        ----------
        row:
            A single row tuple from a ``fetchall()`` call.
        columns:
            Column names corresponding to each position in *row*.
        """
        from distillery.models import Entry

        data: dict[str, Any] = dict(zip(columns, row, strict=True))

        # Tags come back as a Python list from DuckDB VARCHAR[].
        if data.get("tags") is None:
            data["tags"] = []

        # Metadata stored as JSON string needs parsing.
        meta = data.get("metadata")
        if isinstance(meta, str):
            data["metadata"] = json.loads(meta)
        elif meta is None:
            data["metadata"] = {}

        return Entry.from_dict(data)

    # Column list used by search / find_similar (excludes ``embedding``).
    _ENTRY_COLUMNS = (
        "id, content, entry_type, source, author, project, "
        "tags, status, metadata, created_at, updated_at, version"
    )

    # ------------------------------------------------------------------
    # Search / similarity / listing (T02.4)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[SearchResult]:
        """Perform semantic search with optional metadata filters.

        Embeds *query* via the configured embedding provider, then uses the
        HNSW index to find nearest neighbours by cosine similarity.  Metadata
        filters are applied as SQL ``WHERE`` predicates.

        Returns a ``list[SearchResult]`` sorted by descending similarity.
        """
        from distillery.store.protocol import SearchResult

        embedding = self._embedding_provider.embed(query)

        def _sync() -> list[SearchResult]:
            conn = self.connection

            where_clauses, params = self._build_filter_clauses(filters)
            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            # DuckDB's array_cosine_similarity returns a value in [-1, 1].
            # We normalise to [0, 1] for the SearchResult.score field.
            sql = (
                f"SELECT {self._ENTRY_COLUMNS}, "
                f"array_cosine_similarity(embedding, ?::FLOAT[{self._embedding_provider.dimensions}]) AS score "
                f"FROM entries "
                f"{where_sql} "
                f"ORDER BY score DESC "
                f"LIMIT ?"
            )
            all_params = [embedding] + params + [limit]
            result = conn.execute(sql, all_params)
            col_names = [desc[0] for desc in result.description]

            rows = result.fetchall()
            results: list[SearchResult] = []
            for row in rows:
                row_dict = dict(zip(col_names, row, strict=True))
                score = float(row_dict.pop("score"))
                entry = self._row_to_entry(
                    tuple(row_dict.values()),
                    list(row_dict.keys()),
                )
                results.append(SearchResult(entry=entry, score=score))
            return results

        return await asyncio.to_thread(_sync)

    async def find_similar(
        self,
        content: str,
        threshold: float,
        limit: int,
    ) -> list[SearchResult]:
        """Find entries whose cosine similarity to *content* exceeds *threshold*.

        Returns a ``list[SearchResult]`` with ``score >= threshold``, sorted by
        descending similarity.
        """
        from distillery.store.protocol import SearchResult

        embedding = self._embedding_provider.embed(content)

        def _sync() -> list[SearchResult]:
            conn = self.connection

            sql = (
                f"SELECT {self._ENTRY_COLUMNS}, "
                f"array_cosine_similarity(embedding, ?::FLOAT[{self._embedding_provider.dimensions}]) AS score "
                f"FROM entries "
                f"WHERE array_cosine_similarity(embedding, ?::FLOAT[{self._embedding_provider.dimensions}]) >= ? "
                f"ORDER BY score DESC "
                f"LIMIT ?"
            )
            params: list[Any] = [embedding, embedding, threshold, limit]
            result = conn.execute(sql, params)
            col_names = [desc[0] for desc in result.description]

            rows = result.fetchall()
            results: list[SearchResult] = []
            for row in rows:
                row_dict = dict(zip(col_names, row, strict=True))
                score = float(row_dict.pop("score"))
                entry = self._row_to_entry(
                    tuple(row_dict.values()),
                    list(row_dict.keys()),
                )
                results.append(SearchResult(entry=entry, score=score))
            return results

        return await asyncio.to_thread(_sync)

    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
    ) -> list[Entry]:
        """List entries with optional metadata filtering and pagination.

        Unlike ``search``, this method does **not** perform semantic ranking.
        Results are ordered by ``created_at`` descending (newest first).

        Returns a ``list[Entry]``.
        """

        def _sync() -> list[Entry]:
            conn = self.connection

            where_clauses, params = self._build_filter_clauses(filters)
            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            sql = (
                f"SELECT {self._ENTRY_COLUMNS} "
                f"FROM entries "
                f"{where_sql} "
                f"ORDER BY created_at DESC "
                f"LIMIT ? OFFSET ?"
            )
            all_params = params + [limit, offset]
            result = conn.execute(sql, all_params)
            col_names = [desc[0] for desc in result.description]

            rows = result.fetchall()
            return [
                self._row_to_entry(row, col_names) for row in rows
            ]

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------
    # Feedback logging (T01.2)
    # ------------------------------------------------------------------

    def _sync_log_search(
        self,
        query: str,
        result_entry_ids: list[str],
        result_scores: list[float],
        session_id: str | None,
    ) -> str:
        """Synchronous implementation of log_search(); called via asyncio.to_thread."""
        import uuid

        search_id = str(uuid.uuid4())
        conn = self.connection
        sql = (
            "INSERT INTO search_log "
            "(id, query, result_entry_ids, result_scores, session_id) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        conn.execute(sql, [search_id, query, result_entry_ids, result_scores, session_id])
        logger.debug("Logged search id=%s query=%r", search_id, query)
        return search_id

    async def log_search(
        self,
        query: str,
        result_entry_ids: list[str],
        result_scores: list[float],
        session_id: str | None = None,
    ) -> str:
        """Record a search event and return its generated ID.

        Appends a row to the ``search_log`` table capturing the query,
        the IDs and similarity scores of returned entries, and an optional
        session identifier for grouping related searches.

        Returns:
            The UUID string of the newly created ``search_log`` row.
        """
        return await asyncio.to_thread(
            self._sync_log_search, query, result_entry_ids, result_scores, session_id
        )

    def _sync_log_feedback(
        self,
        search_id: str,
        entry_id: str,
        signal: str,
    ) -> str:
        """Synchronous implementation of log_feedback(); called via asyncio.to_thread."""
        import uuid

        feedback_id = str(uuid.uuid4())
        conn = self.connection
        sql = (
            "INSERT INTO feedback_log "
            "(id, search_id, entry_id, signal) "
            "VALUES (?, ?, ?, ?)"
        )
        conn.execute(sql, [feedback_id, search_id, entry_id, signal])
        logger.debug(
            "Logged feedback id=%s search_id=%s entry_id=%s signal=%r",
            feedback_id,
            search_id,
            entry_id,
            signal,
        )
        return feedback_id

    async def log_feedback(
        self,
        search_id: str,
        entry_id: str,
        signal: str,
    ) -> str:
        """Record implicit feedback for a search result and return its ID.

        Appends a row to the ``feedback_log`` table linking a specific
        search event to the entry the user interacted with.

        Returns:
            The UUID string of the newly created ``feedback_log`` row.
        """
        return await asyncio.to_thread(
            self._sync_log_feedback, search_id, entry_id, signal
        )
