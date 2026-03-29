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
import contextlib
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from distillery.models import Entry, EntryStatus, validate_metadata

if TYPE_CHECKING:
    from distillery.embedding.protocol import EmbeddingProvider
    from distillery.store.protocol import SearchResult

logger = logging.getLogger(__name__)


def _sql_escape(value: str) -> str:
    """Escape a string value for safe embedding in a SQL literal.

    Doubles any single-quote characters so the value can be safely placed
    inside a SQL single-quoted string (e.g. ``SET s3_region = 'us-east-1'``).
    """
    return value.replace("'", "''")


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

_ADD_ACCESSED_AT_COLUMN = """
ALTER TABLE entries ADD COLUMN IF NOT EXISTS accessed_at TIMESTAMP;
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
    ``0600`` permissions for local files), the ``entries`` table is defined,
    the ``vss`` extension is loaded, and an HNSW index is built on the
    ``embedding`` column.

    S3-backed storage is supported by passing an ``s3://`` path as
    ``db_path``.  The ``httpfs`` extension is loaded and AWS credentials
    are resolved from environment variables (``AWS_ACCESS_KEY_ID``,
    ``AWS_SECRET_ACCESS_KEY``, ``AWS_SESSION_TOKEN``) or an IAM role when
    running on AWS infrastructure.

    MotherDuck cloud databases are supported by passing an ``md:`` path
    (e.g. ``md:distillery``).  DuckDB automatically reads the
    ``MOTHERDUCK_TOKEN`` environment variable.

    All public methods are ``async`` -- they wrap synchronous DuckDB calls
    via :func:`asyncio.to_thread` to keep the event loop responsive.

    Parameters
    ----------
    db_path:
        Filesystem path to the DuckDB database file, an S3 URI
        (``s3://bucket/path/distillery.db``), a MotherDuck URI
        (``md:database_name``), or ``":memory:"`` for an ephemeral
        in-memory store (useful for tests).
    embedding_provider:
        An object satisfying the ``EmbeddingProvider`` protocol.  Its
        ``dimensions`` property determines the width of the ``embedding``
        column.
    s3_region:
        AWS region for S3 storage.  Falls back to the ``AWS_DEFAULT_REGION``
        / ``AWS_REGION`` environment variables when ``None``.
    s3_endpoint:
        Custom S3-compatible endpoint URL (e.g. MinIO, Cloudflare R2).
        When set, path-style URL access is enabled automatically.
    """

    # ------------------------------------------------------------------
    # Construction & lifecycle
    # ------------------------------------------------------------------

    def __init__(
        self,
        db_path: str,
        embedding_provider: EmbeddingProvider,
        s3_region: str | None = None,
        s3_endpoint: str | None = None,
    ) -> None:
        self._db_path = db_path
        self._embedding_provider = embedding_provider
        self._s3_region = s3_region
        self._s3_endpoint = s3_endpoint
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._initialized: bool = False
        self._vss_available: bool = False

    # ------------------------------------------------------------------
    # Cloud path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_s3_path(db_path: str) -> bool:
        """Return ``True`` if *db_path* is an S3 URI (``s3://`` prefix)."""
        return db_path.startswith("s3://")

    @staticmethod
    def _is_motherduck_path(db_path: str) -> bool:
        """Return ``True`` if *db_path* is a MotherDuck URI (``md:`` prefix)."""
        return db_path.startswith("md:")

    # ------------------------------------------------------------------
    # Connection helpers (sync -- called inside asyncio.to_thread)
    # ------------------------------------------------------------------

    def _ensure_parent_dir(self) -> None:
        """Create the parent directory for the database file if needed.

        No-op for in-memory, S3, and MotherDuck paths.
        """
        if self._db_path == ":memory:":
            return
        if self._is_s3_path(self._db_path) or self._is_motherduck_path(self._db_path):
            return
        parent = Path(self._db_path).parent
        parent.mkdir(parents=True, exist_ok=True)

    def _open_connection(self) -> duckdb.DuckDBPyConnection:
        """Open (or create) the DuckDB database and return a connection."""
        self._ensure_parent_dir()
        conn = duckdb.connect(self._db_path)

        # Lock down permissions only for local files that exist on disk.
        is_local = (
            self._db_path != ":memory:"
            and not self._is_s3_path(self._db_path)
            and not self._is_motherduck_path(self._db_path)
        )
        if is_local and Path(self._db_path).exists():
            os.chmod(self._db_path, 0o600)

        return conn

    def _setup_vss(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Install and load the vss extension, enable HNSW persistence.

        If the VSS extension is unavailable (e.g. in constrained environments
        like AWS Lambda), we log a warning and continue without it.  Vector
        search will still work via brute-force cosine distance — just slower.
        """
        try:
            conn.execute("INSTALL vss;")
            conn.execute("LOAD vss;")
            conn.execute("SET hnsw_enable_experimental_persistence = true;")
            self._vss_available = True
            logger.info("VSS extension loaded with HNSW persistence enabled")
        except (duckdb.IOException, duckdb.CatalogException, duckdb.Error) as exc:
            self._vss_available = False
            logger.warning(
                "VSS extension not available — HNSW indexing disabled, "
                "falling back to brute-force vector search: %s",
                exc,
            )

    def _setup_httpfs(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Install and load the httpfs extension, then configure S3 credentials.

        Credential resolution order:
        1. ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` environment variables
        2. IAM role / instance metadata (when running on AWS infrastructure and
           no explicit env vars are present -- DuckDB httpfs performs its own
           credential-chain lookup in that case)

        ``AWS_SESSION_TOKEN`` is forwarded when present (required for temporary
        STS credentials).

        ``AWS_DEFAULT_REGION`` / ``AWS_REGION`` environment variables are used
        as the region fallback when ``s3_region`` is not set in config.

        For non-AWS S3-compatible endpoints (MinIO, Cloudflare R2, etc.) the
        ``s3_endpoint`` config field should be set; path-style URL access is
        enabled automatically.
        """
        conn.execute("INSTALL httpfs;")
        conn.execute("LOAD httpfs;")

        # Region: config > AWS_DEFAULT_REGION > AWS_REGION
        region = (
            self._s3_region
            or os.environ.get("AWS_DEFAULT_REGION")
            or os.environ.get("AWS_REGION")
        )
        if region:
            conn.execute(f"SET s3_region = '{_sql_escape(region)}';")

        # Custom endpoint for S3-compatible services
        if self._s3_endpoint:
            conn.execute(f"SET s3_endpoint = '{_sql_escape(self._s3_endpoint)}';")
            conn.execute("SET s3_url_style = 'path';")

        # Explicit AWS credentials from environment (optional; IAM role used as fallback)
        access_key = os.environ.get("AWS_ACCESS_KEY_ID")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
        if access_key:
            conn.execute(f"SET s3_access_key_id = '{_sql_escape(access_key)}';")
        if secret_key:
            conn.execute(f"SET s3_secret_access_key = '{_sql_escape(secret_key)}';")

        session_token = os.environ.get("AWS_SESSION_TOKEN")
        if session_token:
            conn.execute(f"SET s3_session_token = '{_sql_escape(session_token)}';")

        logger.info(
            "httpfs extension loaded (region=%s, endpoint=%s, explicit_creds=%s)",
            region or "auto",
            self._s3_endpoint or "default",
            bool(access_key),
        )

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
        """Create the HNSW index on the embedding column.

        Skipped when the VSS extension is not available — vector search
        degrades to brute-force cosine distance which is still correct.
        """
        if not self._vss_available:
            logger.warning("HNSW index not created (VSS extension not available)")
            return
        try:
            conn.execute(_CREATE_HNSW_INDEX)
            logger.info("HNSW index on entries.embedding ready")
        except duckdb.CatalogException:
            # Index already exists -- safe to ignore.
            logger.debug("HNSW index already exists, skipping creation")
        except duckdb.BinderException:
            logger.warning(
                "HNSW index type not recognized — skipping index creation"
            )

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
            "SELECT key, value FROM _meta WHERE key IN ('embedding_model', 'embedding_dimensions')"
        )
        rows = {row[0]: row[1] for row in result.fetchall()}

        model = self._embedding_provider.model_name
        dims = str(self._embedding_provider.dimensions)

        if not rows:
            # First use -- record the model metadata.  Use ON CONFLICT DO
            # NOTHING so concurrent sessions racing through this path don't
            # fail on a primary-key constraint violation.
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES (?, ?) ON CONFLICT DO NOTHING",
                ["embedding_model", model],
            )
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES (?, ?) ON CONFLICT DO NOTHING",
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

    def _add_accessed_at_column(self, conn: duckdb.DuckDBPyConnection) -> None:
        """
        Ensure the `entries` table has an `accessed_at` TIMESTAMP column.

        If the column already exists this is a no-op; otherwise the table
        schema is altered to add ``accessed_at``.
        """
        conn.execute(_ADD_ACCESSED_AT_COLUMN)
        logger.debug("accessed_at column ready on entries table")

    # Transient exceptions that trigger the outer connection retry loop.
    _TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
        duckdb.IOException,
        duckdb.ConnectionException,
        duckdb.HTTPException,
    )

    def _sync_initialize(self) -> None:
        """
        Initialize the DuckDB connection and ensure the database is ready for use.

        Opens or creates the DuckDB database, loads and configures the VSS
        extension, creates or migrates the schema (entries, logs, and metadata),
        validates or records embedding model metadata, and ensures the HNSW
        index and ``accessed_at`` column exist.

        Transient connection failures (IOException, ConnectionException,
        HTTPException) are retried up to 3 times with exponential backoff
        (1 s, 2 s, 4 s).  Write-write conflicts (common when multiple
        stateless HTTP sessions start concurrently) are retried in an
        inner loop.
        """
        import time

        backoff_delays = [1.0, 2.0, 4.0]
        last_exc: Exception | None = None

        for outer_attempt in range(3):
            conn = None
            try:
                conn = self._open_connection()

                # httpfs must be loaded before vss when using S3 storage.
                if self._is_s3_path(self._db_path):
                    self._setup_httpfs(conn)

                self._setup_vss(conn)

                # Wrap the entire initialization write path in a retry loop to
                # handle write-write conflicts during concurrent initialization.
                # All the wrapped operations use CREATE IF NOT EXISTS or
                # transactional upsert patterns, making retries safe.
                for attempt in range(3):
                    try:
                        self._create_schema(conn)
                        self._add_accessed_at_column(conn)
                        self._create_log_tables(conn)
                        self._create_meta_table(conn)
                        self._validate_or_record_meta(conn)
                        self._create_index(conn)
                        break  # Success - exit inner retry loop
                    except (duckdb.TransactionException, duckdb.ConstraintException):
                        if attempt < 2:
                            logger.warning(
                                "Write-write conflict during initialization "
                                "(attempt %d/3), retrying…",
                                attempt + 1,
                            )
                            time.sleep(0.1 * (attempt + 1))
                        else:
                            raise

                self._conn = conn
                self._initialized = True
                logger.info("DuckDBStore initialized at %s", self._db_path)
                return  # Success -- exit outer retry loop

            except self._TRANSIENT_EXCEPTIONS as exc:
                last_exc = exc
                if outer_attempt < 2:
                    delay = backoff_delays[outer_attempt]
                    logger.warning(
                        "Transient connection error during initialization "
                        "(attempt %d/3: %s), retrying in %.0fs…",
                        outer_attempt + 1,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                # On last attempt, fall through to raise below.
            finally:
                # Close the connection on failure before retrying — avoid
                # leaking partially-initialized connections.
                if conn is not None and not self._initialized:
                    with contextlib.suppress(Exception):
                        conn.close()

        # All retries exhausted.
        assert last_exc is not None  # noqa: S101
        raise last_exc

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
                "DuckDBStore has not been initialized. Call 'await store.initialize()' first."
            )
        return self._conn

    @property
    def vss_available(self) -> bool:
        """Return whether the VSS extension was loaded successfully."""
        return self._vss_available

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
        validate_metadata(entry.entry_type.value, entry.metadata)
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
        """
        Retrieve the entry with the given ID and convert it to an Entry object.

        Parameters:
            entry_id (str): UUID of the entry to retrieve.

        Returns:
            Entry | None: The matching Entry if found, `None` if no entry exists with the given ID.

        Notes:
            Also attempts to update the entry's `accessed_at` timestamp; failures to update are ignored.
        """
        conn = self.connection
        sql = f"SELECT {self._ENTRY_COLUMNS} FROM entries WHERE id = ?"
        result = conn.execute(sql, [entry_id])
        col_names = [desc[0] for desc in result.description]
        row = result.fetchone()
        if row is None:
            return None
        # Fire-and-forget: update accessed_at, entry still returned on failure.
        try:
            conn.execute(
                "UPDATE entries SET accessed_at = current_timestamp WHERE id = ?",
                [entry_id],
            )
        except Exception:  # pragma: no cover
            logger.debug("accessed_at update failed for id=%s (ignored)", entry_id)
        return self._row_to_entry(row, col_names)

    async def get(self, entry_id: str) -> Entry | None:
        """Retrieve an entry by its ID.

        Returns:
            The matching ``Entry``, or ``None`` if the ID does not exist.
        """
        return await asyncio.to_thread(self._sync_get, entry_id)

    def _sync_update(self, entry_id: str, updates: dict[str, Any]) -> Entry:
        """
        Apply partial updates to an existing entry and return its updated representation.

        Performs a database UPDATE for the entry identified by entry_id using the keys
        provided in updates. Immutable fields are rejected. If `content` is updated,
        a new embedding is computed and stored. `metadata` dicts are serialized to
        JSON and `tags` lists are stored as arrays. The entry's `version` is
        incremented and both `updated_at` and `accessed_at` are refreshed to the
        current UTC time.

        Parameters:
            entry_id (str): UUID of the entry to update.
            updates (dict[str, Any]): Mapping of column names to new values. Supported
                special cases:
                  - Enum-like objects with a `.value` attribute are stored as that value.
                  - `metadata`: dict values are serialized to JSON.
                  - `tags`: lists are stored as array values.
                  - `content`: triggers recomputation and storage of the embedding.

        Returns:
            Entry: The entry record after the update.

        Raises:
            ValueError: If updates include immutable fields (e.g., id, created_at, source).
            KeyError: If no entry exists with the given id or if the entry cannot be
                found after the update.
        """
        # Reject attempts to change immutable fields.
        bad_keys = self._IMMUTABLE_FIELDS & updates.keys()
        if bad_keys:
            raise ValueError(f"Cannot update immutable field(s): {', '.join(sorted(bad_keys))}")

        conn = self.connection

        # Verify the entry exists first (also fetch entry_type and metadata for validation).
        check_sql = "SELECT id, entry_type, metadata FROM entries WHERE id = ?"
        check_result = conn.execute(check_sql, [entry_id])
        existing_row = check_result.fetchone()
        if existing_row is None:
            raise KeyError(f"No entry found with id={entry_id!r}")
        existing_entry_type: str = existing_row[1]
        existing_metadata_json: str = existing_row[2]
        existing_metadata: dict[str, Any] = (
            json.loads(existing_metadata_json) if existing_metadata_json else {}
        )

        # Validate metadata against the effective entry type schema.
        # Trigger validation when metadata OR entry_type changes — changing
        # the type without supplying new metadata could leave required fields
        # missing for the target type.
        if "metadata" in updates or "entry_type" in updates:
            raw_type = updates.get("entry_type", existing_entry_type)
            effective_entry_type = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
            effective_metadata = updates.get("metadata", existing_metadata)
            validate_metadata(effective_entry_type, effective_metadata)

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

        # Always increment version and refresh updated_at and accessed_at.
        set_parts.append("version = version + 1")
        set_parts.append("updated_at = ?")
        set_params.append(now)
        set_parts.append("accessed_at = ?")
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
        sql = "UPDATE entries SET status = ?, updated_at = ? WHERE id = ?"
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

        if "tag_prefix" in filters and filters["tag_prefix"]:
            prefix = filters["tag_prefix"]
            # Match entries where any tag equals the prefix exactly or starts with
            # "prefix/" to avoid partial-segment matches (e.g. "project/billing"
            # must not match "project/billing-v2/api").
            clauses.append("len(list_filter(tags, t -> t = ? OR starts_with(t, ?))) > 0")
            params.append(prefix)
            params.append(prefix + "/")

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

        # Support metadata path filters like "metadata.external_id".
        # DuckDB stores metadata as a JSON string; use json_extract_string
        # to pull out the nested value for exact-match comparison.
        # Whitelist path segments to alphanumeric + underscore to prevent
        # SQL injection via crafted filter keys.  Fail closed on invalid
        # paths so callers cannot accidentally get unfiltered results.
        for key, val in filters.items():
            if key.startswith("metadata."):
                json_path = key.split(".", 1)[1]
                if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", json_path):
                    raise ValueError(
                        f"Invalid metadata filter path segment: {json_path!r}. "
                        "Only alphanumeric characters and underscores are allowed."
                    )
                clauses.append(f"json_extract_string(metadata, '$.{json_path}') = ?")
                params.append(str(val))

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
        "tags, status, metadata, created_at, updated_at, version, accessed_at"
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
        """
        Search the store for entries semantically similar to the provided query, optionally constrained by metadata filters.

        Applies the given metadata filters to restrict candidates and returns matches sorted by descending similarity. Scores in each SearchResult are normalized to the range [0, 1].

        Parameters:
            query (str): Text to search for.
            filters (dict[str, Any] | None): Optional metadata filters. Supported keys include
                `entry_type`, `author`, `project`, `tags`, `status`, `date_from`, and `date_to`.
            limit (int): Maximum number of results to return.

        Returns:
            list[SearchResult]: Matches ordered by decreasing similarity; each result contains the matched Entry and a `score` in [0, 1].
        """
        from distillery.store.protocol import SearchResult

        embedding = self._embedding_provider.embed(query)

        def _sync() -> list[SearchResult]:
            """
            Execute a synchronous similarity search using the prepared embedding and filters, returning matching entries ordered by similarity.

            Performs a SQL query that computes cosine similarity between stored embeddings and the provided embedding, orders results by similarity descending, and returns a list of SearchResult objects. As a best-effort side effect, updates the `accessed_at` timestamp for returned entries; failures to update are ignored.

            Returns:
                list[SearchResult]: A list of search results ordered by descending similarity. Each result's `score` is normalized to the range [0.0, 1.0].
            """
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
            returned_ids: list[str] = []
            for row in rows:
                row_dict = dict(zip(col_names, row, strict=True))
                raw_score = float(row_dict.pop("score"))
                score = (raw_score + 1.0) / 2.0
                entry = self._row_to_entry(
                    tuple(row_dict.values()),
                    list(row_dict.keys()),
                )
                results.append(SearchResult(entry=entry, score=score))
                returned_ids.append(entry.id)

            # Update accessed_at for all returned entries (fire-and-forget).
            if returned_ids:
                try:
                    placeholders = ", ".join("?" for _ in returned_ids)
                    conn.execute(
                        f"UPDATE entries SET accessed_at = current_timestamp "
                        f"WHERE id IN ({placeholders})",
                        returned_ids,
                    )
                except Exception:  # pragma: no cover
                    logger.debug("accessed_at bulk update failed (ignored)")

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
            # Convert normalized [0, 1] threshold to raw [-1, 1] for SQL comparison
            raw_threshold = threshold * 2.0 - 1.0
            params: list[Any] = [embedding, embedding, raw_threshold, limit]
            result = conn.execute(sql, params)
            col_names = [desc[0] for desc in result.description]

            rows = result.fetchall()
            results: list[SearchResult] = []
            for row in rows:
                row_dict = dict(zip(col_names, row, strict=True))
                raw_score = float(row_dict.pop("score"))
                score = (raw_score + 1.0) / 2.0
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
        """
        Retrieve entries matching optional filters, ordered by created_at descending.

        Parameters:
            filters (dict[str, Any] | None): Filter criteria accepted by the store (see `_build_filter_clauses`). If None, no filtering is applied.
            limit (int): Maximum number of entries to return.
            offset (int): Number of entries to skip before returning results.

        Returns:
            list[Entry]: Entries matching the filters for the requested page, ordered newest first.
        """

        def _sync() -> list[Entry]:
            """
            Fetch entries from the database applying filters, ordering by creation time, and paginating the results.

            Returns:
                list[Entry]: Entries that match the provided filters, ordered by created_at descending and limited/offset according to the surrounding scope.
            """
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
            return [self._row_to_entry(row, col_names) for row in rows]

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
        """
        Record a search event in the search_log table and return its generated ID.

        Parameters:
            query (str): The original search query text.
            result_entry_ids (list[str]): Ordered list of entry IDs returned by the search.
            result_scores (list[float]): Corresponding similarity scores for each returned entry.
            session_id (str | None): Optional session identifier to associate with the search.

        Returns:
            search_id (str): UUID string identifying the inserted search_log row.
        """
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
        """
        Record a search event in the search_log table.

        Inserts a row containing the search `query`, the lists of returned entry IDs and their corresponding similarity `result_scores`, and an optional `session_id`. `result_entry_ids` and `result_scores` are parallel lists and must have the same length.

        Parameters:
            query (str): The text of the search query.
            result_entry_ids (list[str]): List of entry UUIDs returned by the search, in result order.
            result_scores (list[float]): List of similarity scores corresponding to `result_entry_ids`.
            session_id (str | None): Optional identifier to group related searches.

        Returns:
            search_id (str): UUID string of the newly created `search_log` row.
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
        """
        Record a feedback signal for a search and return the new feedback entry ID.

        Parameters:
            search_id (str): UUID of the related search (must correspond to an existing search_log entry).
            entry_id (str): UUID of the entry the feedback refers to.
            signal (str): Feedback signal (e.g., "click", "relevant", "not_relevant").

        Returns:
            feedback_id (str): UUID of the newly created feedback_log row.
        """
        feedback_id = str(uuid.uuid4())
        conn = self.connection
        sql = "INSERT INTO feedback_log (id, search_id, entry_id, signal) VALUES (?, ?, ?, ?)"
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
        """
        Record a feedback event linking a search to an interacted entry.

        Inserts a row into the `feedback_log` table that references a prior search event.

        Returns:
            str: UUID string of the created `feedback_log` row.
        """
        return await asyncio.to_thread(self._sync_log_feedback, search_id, entry_id, signal)
