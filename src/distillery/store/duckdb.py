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
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload
from urllib.parse import unquote, urlparse

import duckdb

from distillery.models import Entry, EntryStatus, validate_metadata
from distillery.store.migrations import _CREATE_META_TABLE, run_pending_migrations

if TYPE_CHECKING:
    from distillery.embedding.protocol import EmbeddingProvider
    from distillery.store.protocol import SearchResult

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _sql_escape(value: str) -> str:
    """Escape a string value for safe embedding in a SQL literal.

    Doubles any single-quote characters so the value can be safely placed
    inside a SQL single-quoted string (e.g. ``SET s3_region = 'us-east-1'``).
    """
    return value.replace("'", "''")


def _sanitise_last_error(error: str | None, max_len: int) -> str | None:
    """Collapse whitespace and truncate a feed-poll error string.

    Returns ``None`` when *error* is ``None`` or empty after stripping so
    successful polls clear any previous error.  Control characters
    (including newlines and carriage returns) are collapsed to single
    spaces so the payload is operator-friendly and less likely to leak
    stack-trace fragments verbatim.  The resulting string is truncated
    to *max_len* characters with an ellipsis suffix when truncation
    occurs.

    Raises:
        ValueError: if *max_len* is not a positive integer. Without this
            guard, ``collapsed[: max_len - 1] + "…"`` would return a value
            longer than the caller-requested limit, which could persist
            oversized ``last_error`` strings.
    """
    if max_len <= 0:
        raise ValueError("max_len must be a positive integer")
    if error is None:
        return None
    # Collapse runs of whitespace / control chars to single spaces.
    collapsed = re.sub(r"\s+", " ", error).strip()
    if not collapsed:
        return None
    if len(collapsed) <= max_len:
        return collapsed
    # Preserve total length of exactly *max_len* including ellipsis.
    return collapsed[: max_len - 1] + "\u2026"


_AGGREGATE_EXPR_MAP: dict[str, str] = {
    "entry_type": "entry_type",
    "status": "status",
    "author": "author",
    "project": "project",
    "source": "source",
    "tags": "UNNEST(tags)",
    "metadata.source_url": "json_extract_string(metadata, '$.source_url')",
    "metadata.source_type": "json_extract_string(metadata, '$.source_type')",
}


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
        *,
        hybrid_search: bool = True,
        rrf_k: int = 60,
        recency_window_days: int = 90,
        recency_min_weight: float = 0.5,
    ) -> None:
        self._db_path = db_path
        self._embedding_provider = embedding_provider
        self._s3_region = s3_region
        self._s3_endpoint = s3_endpoint
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._initialized: bool = False
        self._vss_available: bool = False
        self._fts_available: bool = False
        self._hybrid_search: bool = hybrid_search
        self._rrf_k: int = rrf_k
        self._recency_window_days: int = recency_window_days
        self._recency_min_weight: float = recency_min_weight
        # Serializes access to the shared ``DuckDBPyConnection``.  DuckDB
        # connections are **not** thread-safe for concurrent use, but every
        # store operation funnels through ``asyncio.to_thread`` which runs
        # ``fn`` on the default thread-pool executor — so concurrent
        # coroutines (e.g. ``asyncio.gather`` across feed sources in
        # ``FeedPoller.poll``) end up touching ``self._conn`` from multiple
        # worker threads at once.  That race surfaced as glibc heap
        # corruption (``corrupted double-linked list``) wedging the server
        # process, and as the ``Invalid Input Error: Attempting to execute
        # an unsuccessful or closed pending query result`` upstream of the
        # FTS-rebuild failure that triggered issue #414.  ``_conn_lock``
        # is created lazily on first ``_run_sync`` call so the store can
        # be instantiated outside an event loop (e.g. construction at
        # module import in tests); see ``_get_conn_lock``.
        self._conn_lock: asyncio.Lock | None = None

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

        ``INSTALL vss`` downloads from the network and can block indefinitely
        when connectivity is unavailable.  To avoid hangs we first check if
        the extension is already installed; if not, we attempt ``LOAD vss``
        (which fails fast) so we never issue a blocking download.
        """
        cursor = conn.cursor()
        try:
            row = cursor.execute(
                "SELECT installed, loaded FROM duckdb_extensions() WHERE extension_name = 'vss'"
            ).fetchone()
            already_installed = row[0] if row else False
            already_loaded = row[1] if row else False

            if not already_installed:
                # LOAD fails fast with IOException when files are missing,
                # whereas INSTALL can block indefinitely on a network fetch.
                logger.info(
                    "VSS extension not pre-installed — attempting LOAD "
                    "(will fail fast if files are missing; pre-install vss "
                    "during image build to guarantee availability)"
                )
                cursor.execute("LOAD vss;")
            elif not already_loaded:
                cursor.execute("LOAD vss;")

            cursor.execute("SET hnsw_enable_experimental_persistence = true;")
            self._vss_available = True
            logger.info("VSS extension loaded with HNSW persistence enabled")
        except (duckdb.IOException, duckdb.CatalogException, duckdb.Error) as exc:
            self._vss_available = False
            logger.warning(
                "VSS extension not available — HNSW indexing disabled, "
                "falling back to brute-force vector search: %s",
                exc,
            )
        finally:
            cursor.close()

    def _setup_fts(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Load the FTS extension and rebuild the full-text index.

        If the FTS extension is unavailable (e.g. in constrained environments)
        we log a warning and continue without it.  Search falls back to
        vector-only mode.
        """
        try:
            conn.execute("INSTALL fts")
            conn.execute("LOAD fts")
            self._fts_available = True
            logger.info("FTS extension loaded")
        except (duckdb.IOException, duckdb.CatalogException, duckdb.Error) as exc:
            self._fts_available = False
            logger.warning(
                "FTS extension not available — hybrid search disabled, "
                "falling back to vector-only search: %s",
                exc,
            )

    def _rebuild_fts_index(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Rebuild the full-text search index on ``entries.content``.

        Uses ``PRAGMA create_fts_index(..., overwrite=1)`` which atomically
        drops and recreates the ``fts_main_entries`` schema inside the FTS
        extension's own routine.  A ``CHECKPOINT`` is issued immediately
        afterwards so the FTS DDL is flushed to the main database file rather
        than lingering in the WAL.

        This matters because DuckDB's WAL replay cannot always re-order FTS
        schema drop/create DDL when the process is killed abruptly
        (SIGKILL, OOM, Fly.io scale-to-zero hard-stop) before a checkpoint
        runs.  Replay has been observed to fail with:

            Cannot drop entry "fts_main_entries" because there are entries
            that depend on it.

        Checkpointing after each rebuild means the WAL never carries FTS
        DDL across process boundaries, eliminating the replay hazard.  See
        GitHub issue #349 for background.
        """
        if not self._fts_available:
            return
        try:
            # ``overwrite=1`` makes the PRAGMA idempotent — the FTS extension
            # handles dropping any existing ``fts_main_entries`` schema
            # internally, so we don't emit a separate DROP SCHEMA into the
            # WAL.  Run outside an explicit BEGIN so the PRAGMA commits
            # cleanly on its own; the immediate CHECKPOINT below flushes
            # the resulting DDL out of the WAL.
            conn.execute("PRAGMA create_fts_index('entries', 'id', 'content', overwrite=1)")
            logger.debug("FTS index rebuilt on entries.content")
        except duckdb.Error as exc:
            logger.warning("FTS index rebuild failed: %s", exc)
            self._fts_available = False
            # ROLLBACK the aborted transaction so the connection is usable
            # for the next caller.  Without this, the PRAGMA failure leaves
            # the connection in an aborted-transaction state that propagates
            # to every subsequent statement as ``TransactionContext Error:
            # Current transaction is aborted (please ROLLBACK)``.  That
            # cascade silently disables ``FeedPoller._has_external_id``
            # (issue #414), which fails closed but still represents a
            # temporary loss of dedup until the next healthy lookup.
            self._rollback_quietly(conn)
            return

        # Force a CHECKPOINT so the FTS schema DDL is persisted to the
        # main database file.  If the process is killed before the next
        # checkpoint, WAL replay will not have to re-apply FTS DDL —
        # which is where we have seen ordering-related replay failures.
        try:
            conn.execute("CHECKPOINT")
        except duckdb.Error as exc:  # pragma: no cover — best-effort
            logger.debug("Post-FTS-rebuild CHECKPOINT skipped: %s", exc)

    def _checkpoint_after_write(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Flush WAL to the main database file after a write operation.

        DuckDB's implicit auto-commit writes each statement to the WAL, but
        those writes only reach the main database file on the next
        ``CHECKPOINT``.  Without periodic checkpoints the WAL can grow
        unbounded and — more importantly — any ungraceful termination
        (SIGKILL, OOM, crash, abrupt scale-to-zero) leaves user writes
        stranded in the WAL.  On the next startup, DuckDB attempts to
        replay the WAL; if that replay fails for any reason (e.g. a
        partially-written FTS schema rebuild), the
        :meth:`_sync_initialize` recovery path can discard the WAL
        entirely — silently losing the writes.  This was the root cause of
        issue #346: entries returned ``persisted: true`` then vanished
        between creation and later mutation.

        Calling ``CHECKPOINT`` after each successful write bounds the WAL
        delta to a single entry's worth of data, making writes durable
        even under ungraceful termination.  DuckDB's ``CHECKPOINT`` is a
        no-op when the WAL is already empty, so the overhead on an idle
        database is negligible.

        Checkpoint failures are logged and swallowed — the write itself
        has already been committed to the WAL, so returning success to
        the caller is still correct.  A failed checkpoint just means the
        WAL stays slightly larger than usual.
        """
        try:
            conn.execute("CHECKPOINT")
        except duckdb.Error as exc:
            # Non-fatal: the row is already in the WAL.  Log so operators
            # can see repeated failures, but don't raise — the caller has
            # already observed a successful write.
            logger.debug("CHECKPOINT after write failed (non-fatal): %s", exc)

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
            self._s3_region or os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
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

    def _track_version_info(self, conn: duckdb.DuckDBPyConnection) -> None:
        """Persist DuckDB and VSS version info in ``_meta``.

        Compares the stored ``duckdb_version`` against the running library
        version and warns on major/minor mismatch.  Then upserts
        ``duckdb_version`` and (when available) ``vss_version``.

        Schema version tracking is handled by
        :func:`~distillery.store.migrations.run_pending_migrations`.
        """
        current_duckdb_version: str = duckdb.__version__

        # Compare stored duckdb_version; warn on major/minor mismatch
        stored_result = conn.execute("SELECT value FROM _meta WHERE key = 'duckdb_version'")
        stored_row = stored_result.fetchone()
        if stored_row is not None:
            stored_version: str = stored_row[0]
            stored_parts = stored_version.split(".")
            current_parts = current_duckdb_version.split(".")
            if (
                len(stored_parts) >= 2
                and len(current_parts) >= 2
                and (stored_parts[0] != current_parts[0] or stored_parts[1] != current_parts[1])
            ):
                logger.warning(
                    "DuckDB version changed: stored=%s, current=%s — "
                    "consider running distillery export/import if schema differs",
                    stored_version,
                    current_duckdb_version,
                )

        # Upsert duckdb_version
        conn.execute(
            "INSERT INTO _meta (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            ["duckdb_version", current_duckdb_version],
        )

        # Get VSS extension version if available; upsert into _meta
        vss_version: str = ""
        try:
            vss_result = conn.execute(
                "SELECT extension_version FROM duckdb_extensions() WHERE extension_name = 'vss'"
            )
            vss_row = vss_result.fetchone()
            if vss_row is not None:
                vss_version = vss_row[0] or ""
        except Exception:  # noqa: BLE001
            pass  # VSS extension metadata not available — silently skip

        if vss_version:
            conn.execute(
                "INSERT INTO _meta (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                ["vss_version", vss_version],
            )

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

    def _recover_from_wal_replay_failure(self, exc: duckdb.Error) -> duckdb.DuckDBPyConnection:
        """Recover from a WAL replay failure caused by FTS schema DDL.

        Replay is known to fail for FTS-related DDL when the process was
        killed between an FTS index rebuild and the subsequent checkpoint
        (see issue #349).  Recovery moves the WAL file aside to a
        timestamped backup so any uncommitted data is preserved for manual
        inspection, then retries the connection.

        Only local file paths are eligible for recovery; in-memory,
        S3, and MotherDuck URIs re-raise the original error.

        Returns
        -------
        duckdb.DuckDBPyConnection
            A fresh connection to the database (now opened without WAL).

        Raises
        ------
        duckdb.Error
            Re-raised when the error is not WAL/FTS-related, when the path
            is not a recoverable local file, or when no ``.wal`` sidecar
            exists on disk.
        """
        exc_msg = str(exc)
        # Match only the specific replay-failure signature.  A broader
        # substring match on "WAL" would also trigger on unrelated WAL
        # open errors, silently moving user data aside.
        is_fts_replay_failure = "Failure while replaying WAL file" in exc_msg and (
            "fts_main_entries" in exc_msg or "Cannot drop entry" in exc_msg
        )
        if not is_fts_replay_failure:
            raise exc

        # Resolve _db_path to a real filesystem path.  urlparse treats
        # Windows drive letters (``C:\...``) as URI schemes, and file://
        # URIs need unquoting + path extraction rather than a raw
        # ``Path(self._db_path + ".wal")`` concat.
        db_file = self._resolve_local_db_path()
        if db_file is None:
            raise exc

        wal_path = Path(str(db_file) + ".wal")
        if not wal_path.exists():
            raise exc

        # Move the WAL aside with a timestamped suffix so operators can
        # recover uncommitted data if needed.  Silently deleting the WAL
        # (the previous behaviour) is unrecoverable and unfriendly.
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = wal_path.with_suffix(f".wal.corrupt.{timestamp}")
        try:
            wal_path.rename(backup_path)
        except OSError as rename_exc:
            # Leave the WAL in place and propagate the failure.  The
            # previous behaviour unlinked the WAL as a fallback, which
            # reintroduced the exact data-loss path this recovery is
            # meant to eliminate.
            logger.error(
                "Could not preserve WAL as %s; leaving the original WAL file "
                "in place for manual recovery.  Original replay failure: %s",
                backup_path,
                exc,
                exc_info=rename_exc,
            )
            raise exc from rename_exc

        logger.warning(
            "Database WAL appears corrupt (FTS-related): %s. "
            "Moved WAL aside to %s and retrying — uncommitted data has "
            "been preserved for manual recovery but will NOT be replayed. "
            "The FTS index will be rebuilt from scratch during init.",
            exc,
            backup_path,
        )
        return self._open_connection()

    def _resolve_local_db_path(self) -> Path | None:
        """Return the filesystem path for ``self._db_path`` if it's local.

        Handles four shapes:

        * ``":memory:"`` — not local.
        * S3 / MotherDuck URIs — not local.
        * ``file://`` URIs — local; unquote the path component.
        * Windows drive-letter paths (``C:\\...``) — local; ``urlparse``
          would otherwise mistake ``C`` for a URI scheme.
        * Plain POSIX or relative paths — local.

        Returns ``None`` for non-local paths so the caller can skip
        recovery rather than acting on a URI that has no meaningful
        ``.wal`` sidecar on the local filesystem.
        """
        raw = self._db_path
        if raw == ":memory:":
            return None
        if self._is_s3_path(raw) or self._is_motherduck_path(raw):
            return None

        parsed = urlparse(raw)
        scheme = parsed.scheme.lower()

        # Windows drive letter: scheme is a single ASCII letter and the
        # "netloc" is empty; treat the raw string as a local path.
        if len(scheme) == 1 and scheme.isalpha():
            return Path(raw)

        if scheme == "file":
            # file:// URI: combine authority (UNC host) + path.  Two
            # edge cases matter:
            #   * file://server/share/path → UNC; re-attach "//server"
            #     in front of the path so the resulting Path points at
            #     \\server\share\path on Windows (and stays harmless on
            #     POSIX, where UNC is not a thing).
            #   * file:///C:/path → parsed.path is "/C:/path".  Strip
            #     the leading slash so Path("C:/path") resolves to the
            #     Windows drive-letter form instead of a relative
            #     "/C:/..." that no filesystem understands.
            path_part = unquote(parsed.path)
            netloc = parsed.netloc
            if netloc:
                return Path("//" + netloc + path_part)
            # Strip the synthetic leading slash in front of a Windows
            # drive letter (e.g. "/C:/foo" → "C:/foo").
            if (
                len(path_part) >= 3
                and path_part[0] == "/"
                and path_part[1].isalpha()
                and path_part[2] == ":"
            ):
                path_part = path_part[1:]
            return Path(path_part)

        if scheme == "":
            return Path(raw)

        return None

    def _sync_initialize(self) -> None:
        """Initialize the DuckDB connection and run pending schema migrations.

        Opens or creates the DuckDB database, loads and configures the VSS
        extension, runs forward-only migrations via
        :func:`~distillery.store.migrations.run_pending_migrations`, validates
        embedding metadata, and records DuckDB/VSS version info.

        Write-write conflicts (common when multiple stateless HTTP sessions
        start concurrently) are retried automatically by wrapping the entire
        initialization write path in a retry loop.

        If the database cannot be opened due to a corrupt WAL (e.g. from an
        interrupted FTS index rebuild), the WAL is moved aside to a
        ``.wal.corrupt.<timestamp>`` sidecar and the connection is retried
        via :meth:`_recover_from_wal_replay_failure`.  The backup preserves
        any uncommitted data for manual recovery — it is NOT automatically
        replayed.

        Historically this recovery path was the last link in the chain
        that produced "ghost entry_ids" (issue #346): writes sitting in
        a WAL on an ungraceful restart were silently discarded, causing
        entries that returned ``persisted: true`` to disappear on a later
        ``get`` / ``update``.  Writes now checkpoint eagerly (see
        :meth:`_checkpoint_after_write`) so reaching this branch with
        user data in the WAL should be rare; :meth:`_rebuild_fts_index`
        aggressively checkpoints after each rebuild to further minimise
        how often this path is exercised (see issue #349).
        """
        import time

        try:
            conn = self._open_connection()
        except duckdb.Error as exc:
            conn = self._recover_from_wal_replay_failure(exc)

        # httpfs must be loaded before vss when using S3 storage.
        if self._is_s3_path(self._db_path):
            self._setup_httpfs(conn)

        self._setup_vss(conn)

        # Load FTS extension for hybrid search (must happen before index rebuild).
        if self._hybrid_search:
            self._setup_fts(conn)

        # Wrap the entire initialization write path in a retry loop to handle
        # write-write conflicts during concurrent initialization.  All the
        # wrapped operations use CREATE IF NOT EXISTS / transactional upsert
        # patterns, making retries safe.
        for attempt in range(3):
            try:
                # 1. Bootstrap the _meta table so get_current_schema_version
                #    can read schema_version even on a brand-new database.
                conn.execute(_CREATE_META_TABLE)

                # 2. Run all pending forward-only migrations.
                schema_version = run_pending_migrations(
                    conn,
                    dimensions=self._embedding_provider.dimensions,
                    vss_available=self._vss_available,
                )

                # 3. Validate or record embedding model metadata.
                self._validate_or_record_meta(conn)

                # 4. Ensure HNSW index exists.  Migration 6 may have been
                #    applied when VSS was unavailable; this backfills the
                #    index on a subsequent startup where VSS is present.
                if self._vss_available:
                    with contextlib.suppress(duckdb.CatalogException, duckdb.BinderException):
                        conn.execute(
                            "CREATE INDEX IF NOT EXISTS idx_entries_embedding "
                            "ON entries USING HNSW (embedding) "
                            "WITH (metric = 'cosine');"
                        )

                # 5. Record DuckDB / VSS version info in _meta.
                self._track_version_info(conn)

                logger.info(
                    "Schema at version %d, DuckDB %s",
                    schema_version,
                    duckdb.__version__,
                )
                break  # Success — exit retry loop
            except (duckdb.TransactionException, duckdb.ConstraintException):
                if attempt < 2:
                    logger.warning(
                        "Write-write conflict during initialization (attempt %d/3), retrying…",
                        attempt + 1,
                    )
                    time.sleep(0.1 * (attempt + 1))
                else:
                    raise

        # Rebuild the FTS index so it covers any entries inserted before the
        # FTS extension was available or any content changes since last startup.
        if self._fts_available:
            self._rebuild_fts_index(conn)

        # Log search mode.
        if self._hybrid_search and self._fts_available:
            logger.info(
                "Hybrid search active (BM25 + vector, RRF k=%d, "
                "recency_window=%dd, recency_min_weight=%.2f)",
                self._rrf_k,
                self._recency_window_days,
                self._recency_min_weight,
            )
        else:
            reason = (
                "disabled by config" if not self._hybrid_search else "FTS extension unavailable"
            )
            logger.info("Vector-only search active (%s)", reason)

        # Force a WAL checkpoint so all schema changes are flushed to the
        # main database file.  This protects against SIGKILL or abrupt parent
        # death leaving the WAL in a partially-written state.
        try:
            conn.execute("CHECKPOINT")
        except duckdb.Error as exc:  # pragma: no cover – in-memory DBs may skip
            logger.debug("Post-init CHECKPOINT skipped: %s", exc)

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
        """Checkpoint the WAL and close the database connection.

        Holds ``_conn_lock`` so the close cannot race an in-flight
        ``_run_sync`` worker still mutating the connection (issue #416).
        """
        if self._conn is None:
            return
        async with self._get_conn_lock():
            if self._conn is None:  # double-checked under the lock
                return
            try:
                await asyncio.to_thread(self._conn.execute, "CHECKPOINT")
            except duckdb.Error as exc:  # pragma: no cover
                logger.debug("Shutdown CHECKPOINT skipped: %s", exc)
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
    def embedding_provider(self) -> EmbeddingProvider:
        """Return the configured embedding provider."""
        return self._embedding_provider

    # ------------------------------------------------------------------
    # Transaction safety (issue #363)
    # ------------------------------------------------------------------

    @staticmethod
    def _rollback_quietly(conn: duckdb.DuckDBPyConnection) -> None:
        """Best-effort ``ROLLBACK`` to clear an aborted transaction.

        DuckDB leaves a connection in an aborted-transaction state when a
        statement raises inside an implicit or explicit transaction — every
        subsequent call on the same connection fails with
        ``TransactionContext Error: Current transaction is aborted (please
        ROLLBACK)``.  Issuing a ``ROLLBACK`` clears the aborted state and
        restores the connection to a usable baseline.

        Errors from ``ROLLBACK`` itself are logged at debug level and
        swallowed — if rollback fails we are no worse off than if we had
        never tried.  Callers must still propagate the original exception.
        """
        try:
            conn.rollback()
        except duckdb.Error as rollback_exc:
            logger.debug("Post-error ROLLBACK skipped: %s", rollback_exc)

    def _get_conn_lock(self) -> asyncio.Lock:
        """Return the connection-serialization lock, creating it lazily.

        ``asyncio.Lock`` binds to the running event loop, but ``DuckDBStore``
        may be instantiated outside one (e.g. at module import in tests).
        Creating the lock here, on the first call from inside an async
        method, guarantees it lives on the same loop the store is being
        used from.
        """
        if self._conn_lock is None:
            self._conn_lock = asyncio.Lock()
        return self._conn_lock

    async def _run_sync(
        self,
        fn: Callable[..., _T],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> _T:
        """Run *fn* via :func:`asyncio.to_thread` with rollback on error.

        Wraps every sync store operation so that any exception raised by
        *fn* triggers a best-effort ``ROLLBACK`` on the shared DuckDB
        connection **before** the exception propagates.  Without this,
        a single failed write would leave the shared connection in an
        aborted-transaction state and all subsequent reads and writes
        would fail until the connection was recycled (issue #363).

        Holds ``_conn_lock`` for the duration of the to-thread call so
        only one worker thread touches the shared ``DuckDBPyConnection``
        at a time.  DuckDB connections are not thread-safe for concurrent
        use; without this lock, parallel callers (notably ``FeedPoller``'s
        per-source ``asyncio.gather``) would race inside DuckDB's C++
        buffer manager and intermittently corrupt the glibc heap, wedging
        the process with ``corrupted double-linked list`` (issue #416).
        Throughput on parallel store operations is reduced to one-at-a-time;
        a future optimisation could narrow the lock to the SQL portion of
        each ``_sync_*`` method (releasing it across the embedding network
        call) but correctness comes first.

        Read-only operations (e.g. :meth:`_sync_get`) can also reach this
        path when a prior uncaught exception poisoned the connection;
        running ``ROLLBACK`` after the failed read restores the connection
        so the next call succeeds rather than cascading the same error.
        """
        async with self._get_conn_lock():
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except Exception:
                # Catching ``Exception`` — not ``BaseException`` — so that
                # ``asyncio.CancelledError`` does not trigger rollback.
                # When a task is cancelled while awaiting
                # ``asyncio.to_thread(fn, …)`` the worker thread executing
                # *fn* keeps running (Python has no safe way to forcibly
                # stop a thread), so issuing ``conn.rollback()`` from a
                # second worker thread would race against the still-live
                # first one on the shared DuckDB connection.  On
                # cancellation we simply re-raise; on ordinary exceptions
                # *fn* has already returned control so the rollback is
                # safe.  The rollback runs while we still hold the lock
                # so the connection is single-threaded throughout.
                conn = self._conn
                if conn is not None:
                    await asyncio.to_thread(self._rollback_quietly, conn)
                raise

    async def rollback(self) -> None:
        """Public rollback hook for non-store code paths that touch the connection.

        The MCP tool layer occasionally issues raw ``conn.execute`` calls
        (e.g. the per-request embedding-budget counter in
        :mod:`distillery.mcp.budget`) that bypass :meth:`_run_sync`.  Those
        call sites can invoke ``await store.rollback()`` in their exception
        handlers to clear an aborted transaction before the next request.

        Holds ``_conn_lock`` so the rollback cannot race a concurrent
        ``_run_sync`` worker still mutating the connection (issue #416).
        """
        if self._conn is None:
            return
        async with self._get_conn_lock():
            conn = self._conn
            if conn is None:  # double-checked under the lock
                return
            await asyncio.to_thread(self._rollback_quietly, conn)

    async def probe_readiness(self) -> tuple[bool, str | None]:
        """Return ``(True, None)`` when the connection can answer a trivial query.

        Exercised by the MCP status handler (``distillery_status``) and by
        :meth:`initialize` immediately after schema setup so that a database
        file which mounts but is not queryable (e.g. after a partial WAL
        replay / volume snapshot inconsistency — see issue #363 follow-up)
        surfaces as an explicit error instead of a silent null in the
        status payload.

        The probe runs ``SELECT COUNT(*) FROM entries`` via the normal
        async path so transient aborted-transaction state is rolled back
        by :meth:`_run_sync` before a second probe is attempted.
        """
        if self._conn is None:
            return False, "store not initialized"
        try:
            await self._run_sync(
                lambda: self._conn.execute("SELECT COUNT(*) FROM entries").fetchone()  # type: ignore[union-attr]
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"
        return True, None

    # ------------------------------------------------------------------
    # CRUD protocol methods (T02.3)
    # ------------------------------------------------------------------

    # Fields that callers may never overwrite via update().
    _IMMUTABLE_FIELDS = frozenset({"id", "created_at", "source"})

    # Columns that may be updated via _sync_update().  Any key not in this set
    # is rejected *after* the immutable-field check, closing the SQL-injection
    # vector where dynamic column names are interpolated into the UPDATE clause.
    _ALLOWED_UPDATE_COLUMNS = frozenset(
        {
            "content",
            "entry_type",
            "author",
            "project",
            "tags",
            "status",
            "verification",
            "metadata",
            "last_modified_by",
            "expires_at",
            "session_id",
        }
    )

    def _sync_store(self, entry: Entry) -> str:
        """Synchronous implementation of store(); called via asyncio.to_thread."""
        validate_metadata(entry.entry_type.value, entry.metadata)
        conn = self.connection
        embedding = self._embedding_provider.embed(entry.content)

        sql = (
            "INSERT INTO entries "
            "(id, content, entry_type, source, author, project, tags, status, "
            " verification, metadata, created_at, updated_at, version, embedding, "
            " created_by, last_modified_by, expires_at, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
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
            entry.verification.value,
            json.dumps(entry.metadata),
            entry.created_at,
            entry.updated_at,
            entry.version,
            embedding,
            entry.created_by,
            entry.last_modified_by,
            entry.expires_at,
            entry.session_id,
        ]
        conn.execute(sql, params)
        # Rebuild FTS index so new content is searchable via BM25.
        self._rebuild_fts_index(conn)
        # Flush WAL so the new row survives ungraceful termination.
        # See :meth:`_checkpoint_after_write` for why this matters (issue #346).
        self._checkpoint_after_write(conn)
        logger.debug("Stored entry id=%s", entry.id)
        return entry.id

    async def store(self, entry: Entry) -> str:
        """Persist a new entry and return its ID.

        The entry's content is embedded via the configured embedding provider
        before insertion.

        Returns:
            The UUID string of the stored entry.
        """
        return await self._run_sync(self._sync_store, entry)

    def _sync_store_batch(self, entries: Sequence[Entry]) -> list[str]:
        """Synchronous batch-store implementation; called via asyncio.to_thread."""
        if not entries:
            return []

        for entry in entries:
            validate_metadata(entry.entry_type.value, entry.metadata)

        conn = self.connection

        # Batch embed all contents in one call.
        embeddings = self._embedding_provider.embed_batch([e.content for e in entries])
        if len(embeddings) != len(entries):
            raise RuntimeError(
                f"embed_batch returned {len(embeddings)} vectors for "
                f"{len(entries)} entries — aborting to avoid partial inserts."
            )

        sql = (
            "INSERT INTO entries "
            "(id, content, entry_type, source, author, project, tags, status, "
            " verification, metadata, created_at, updated_at, version, embedding, "
            " created_by, last_modified_by, expires_at, session_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )

        conn.begin()
        try:
            for entry, embedding in zip(entries, embeddings, strict=True):
                params = [
                    entry.id,
                    entry.content,
                    entry.entry_type.value,
                    entry.source.value,
                    entry.author,
                    entry.project,
                    list(entry.tags),
                    entry.status.value,
                    entry.verification.value,
                    json.dumps(entry.metadata),
                    entry.created_at,
                    entry.updated_at,
                    entry.version,
                    embedding,
                    entry.created_by,
                    entry.last_modified_by,
                    entry.expires_at,
                    entry.session_id,
                ]
                conn.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        self._rebuild_fts_index(conn)
        # Flush WAL so the new rows survive ungraceful termination.
        # See :meth:`_checkpoint_after_write` for why this matters (issue #346).
        self._checkpoint_after_write(conn)
        logger.debug("Batch-stored %d entries", len(entries))
        return [e.id for e in entries]

    async def store_batch(self, entries: Sequence[Entry]) -> list[str]:
        """Batch-store entries and return their IDs.

        Embeds all contents in a single batch call and inserts all entries
        in one transaction.  No dedup or conflict checks are performed.

        Returns:
            List of UUID strings for the stored entries.
        """
        return await self._run_sync(self._sync_store_batch, entries)

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
        return await self._run_sync(self._sync_get, entry_id)

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

        # Reject column names not in the whitelist (defence-in-depth against
        # SQL injection via dynamic SET clause construction).
        unknown_keys = updates.keys() - self._ALLOWED_UPDATE_COLUMNS
        if unknown_keys:
            raise ValueError(f"Cannot update unknown column(s): {', '.join(sorted(unknown_keys))}")

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
        # Rebuild FTS index when content changes.
        if "content" in updates:
            self._rebuild_fts_index(conn)
        # Flush WAL so the update survives ungraceful termination.
        # See :meth:`_checkpoint_after_write` for why this matters (issue #346).
        self._checkpoint_after_write(conn)
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
        return await self._run_sync(self._sync_update, entry_id, updates)

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
            # Flush WAL so the status change survives ungraceful termination.
            # See :meth:`_checkpoint_after_write` for why this matters (issue #346).
            self._checkpoint_after_write(conn)
            logger.debug("Soft-deleted (archived) entry id=%s", entry_id)
        else:
            logger.debug("delete() called for non-existent entry id=%s", entry_id)
        return found

    async def delete(self, entry_id: str) -> bool:
        """Soft-delete an entry by setting its status to ``archived``.

        Returns:
            ``True`` if the entry was found and archived, ``False`` otherwise.
        """
        return await self._run_sync(self._sync_delete, entry_id)

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
        - ``verification`` (str) -- one of "unverified", "testing", "verified"
        - ``source`` (str) -- entry origin (e.g. "claude-code", "manual", "inference", etc.)
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
            val = filters["status"]
            if isinstance(val, list):
                if not val:
                    raise ValueError("status filter list must not be empty")
                placeholders = ", ".join("?" for _ in val)
                clauses.append(f"status IN ({placeholders})")
                params.extend(str(v) for v in val)
            else:
                clauses.append("status = ?")
                params.append(str(val))

        if "verification" in filters:
            clauses.append("verification = ?")
            params.append(str(filters["verification"]))

        if "source" in filters:
            clauses.append("source = ?")
            params.append(filters["source"])

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

        if "session_id" in filters:
            clauses.append("session_id = ?")
            params.append(str(filters["session_id"]))

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
        "tags, status, verification, metadata, created_at, updated_at, version, accessed_at, "
        "created_by, last_modified_by, expires_at, session_id"
    )

    # ------------------------------------------------------------------
    # Search / similarity / listing (T02.4)
    # ------------------------------------------------------------------

    def _bm25_search(
        self,
        query: str,
        limit: int,
    ) -> list[tuple[str, int]]:
        """Run a BM25 full-text search and return ``(entry_id, rank)`` pairs.

        Parameters
        ----------
        query:
            Free-text search query.
        limit:
            Maximum number of results.

        Returns
        -------
        list[tuple[str, int]]:
            Pairs of ``(entry_id, 1-based_rank)`` ordered by BM25 score
            descending.  Returns an empty list when FTS is unavailable or
            the query produces no matches.
        """
        if not self._fts_available:
            return []
        conn = self.connection
        try:
            sql = (
                "SELECT id, fts_main_entries.match_bm25(id, ?) AS bm25 "
                "FROM entries "
                "WHERE bm25 IS NOT NULL "
                "ORDER BY bm25 DESC "
                "LIMIT ?"
            )
            rows = conn.execute(sql, [query, limit]).fetchall()
            return [(row[0], rank) for rank, row in enumerate(rows, start=1)]
        except duckdb.Error as exc:
            logger.warning("BM25 search failed, falling back to vector-only: %s", exc)
            return []

    def _recency_weight(self, created_at: datetime) -> float:
        """Compute a recency decay weight in ``[recency_min_weight, 1.0]``.

        Entries created within the last ``recency_window_days`` receive a
        weight of 1.0.  Older entries decay linearly down to
        ``recency_min_weight``.
        """
        now = datetime.now(tz=UTC)
        # DuckDB may return timezone-naive datetimes; treat them as UTC.
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        age_days = (now - created_at).total_seconds() / 86400.0
        if age_days <= self._recency_window_days:
            return 1.0
        # Linear decay from 1.0 to recency_min_weight over another window span
        # beyond the window boundary, clamped at the minimum.
        decay = 1.0 - (age_days - self._recency_window_days) / max(self._recency_window_days, 1)
        return max(self._recency_min_weight, decay)

    async def search(
        self,
        query: str,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[SearchResult]:
        """Search using hybrid BM25 + vector RRF fusion (with recency decay).

        When hybrid search is active and FTS is available, both a vector
        similarity search and a BM25 full-text search are performed.  Results
        are fused using Reciprocal Rank Fusion (RRF) with an optional recency
        decay multiplier.  Falls back gracefully to vector-only when FTS is
        unavailable or hybrid search is disabled.

        Parameters:
            query: Text to search for.
            filters: Optional metadata filters.
            limit: Maximum number of results to return.

        Returns:
            list[SearchResult]: Matches ordered by decreasing fused rank
            (RRF in hybrid mode, raw cosine similarity otherwise).  Each
            ``score`` is the entry's raw cosine similarity to the query
            mapped to ``[0, 1]`` — it is NOT rescaled per-scope, so values
            stay comparable across metadata filters (issue #370).
        """
        from distillery.store.protocol import SearchResult

        embedding = self._embedding_provider.embed(query)
        use_hybrid = self._hybrid_search and self._fts_available

        def _sync() -> list[SearchResult]:
            conn = self.connection

            where_clauses, params = self._build_filter_clauses(filters)
            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            # --- Vector search (always performed) ---
            sql = (
                f"SELECT {self._ENTRY_COLUMNS}, "
                f"array_cosine_similarity(embedding, ?::FLOAT[{self._embedding_provider.dimensions}]) AS score "
                f"FROM entries "
                f"{where_sql} "
                f"ORDER BY score DESC "
                f"LIMIT ?"
            )
            # Fetch more candidates for fusion when hybrid is active.
            vector_limit = limit * 3 if use_hybrid else limit
            all_params = [embedding] + params + [vector_limit]
            result = conn.execute(sql, all_params)
            col_names = [desc[0] for desc in result.description]
            rows = result.fetchall()

            # Build entry lookup, vector ranks, and per-entry cosine similarity.
            entry_map: dict[str, Entry] = {}
            vector_ranks: dict[str, int] = {}
            entry_created: dict[str, datetime] = {}
            cosine_score: dict[str, float] = {}
            for rank, row in enumerate(rows, start=1):
                row_dict = dict(zip(col_names, row, strict=True))
                raw_cosine = float(row_dict.pop("score"))
                entry = self._row_to_entry(
                    tuple(row_dict.values()),
                    list(row_dict.keys()),
                )
                entry_map[entry.id] = entry
                vector_ranks[entry.id] = rank
                entry_created[entry.id] = entry.created_at
                # Map raw cosine similarity in [-1, 1] to a displayed score in [0, 1].
                cosine_score[entry.id] = (raw_cosine + 1.0) / 2.0

            if not use_hybrid:
                # Vector-only: return raw cosine similarity (mapped to [0, 1]).
                # No min-max rescaling — score represents true similarity to the
                # query, identical regardless of any metadata filter (issue #370).
                results: list[SearchResult] = []
                returned_ids: list[str] = []
                for row in rows[:limit]:
                    row_dict = dict(zip(col_names, row, strict=True))
                    row_dict.pop("score")
                    eid = row_dict["id"]
                    results.append(SearchResult(entry=entry_map[eid], score=cosine_score[eid]))
                    returned_ids.append(eid)
                self._touch_accessed(conn, returned_ids)
                return results

            # --- BM25 search ---
            bm25_results = self._bm25_search(query, vector_limit)
            bm25_ranks: dict[str, int] = dict(bm25_results)

            # Fetch entries found by BM25 but not by the vector search so we
            # have a complete entry_map for RRF scoring.  Apply the same
            # filters so BM25-only entries that don't match are excluded.
            # Also compute cosine similarity for these entries so the displayed
            # score remains a true similarity measure (not a per-scope rescale).
            missing_ids = [eid for eid in bm25_ranks if eid not in entry_map]
            if missing_ids:
                placeholders = ", ".join("?" for _ in missing_ids)
                filter_clauses, filter_params = self._build_filter_clauses(filters)
                extra_where = ""
                if filter_clauses:
                    extra_where = " AND " + " AND ".join(filter_clauses)
                dims = self._embedding_provider.dimensions
                fetch_sql = (
                    f"SELECT {self._ENTRY_COLUMNS}, "
                    f"array_cosine_similarity(embedding, ?::FLOAT[{dims}]) AS score "
                    f"FROM entries "
                    f"WHERE id IN ({placeholders}){extra_where}"
                )
                fetch_result = conn.execute(fetch_sql, [embedding, *missing_ids, *filter_params])
                fetch_cols = [desc[0] for desc in fetch_result.description]
                fetched_ids: set[str] = set()
                for row in fetch_result.fetchall():
                    row_dict = dict(zip(fetch_cols, row, strict=True))
                    raw_cosine = float(row_dict.pop("score"))
                    entry = self._row_to_entry(
                        tuple(row_dict.values()),
                        list(row_dict.keys()),
                    )
                    entry_map[entry.id] = entry
                    entry_created[entry.id] = entry.created_at
                    cosine_score[entry.id] = (raw_cosine + 1.0) / 2.0
                    fetched_ids.add(entry.id)
                # Remove BM25-only entries that were excluded by filters.
                for eid in missing_ids:
                    if eid not in fetched_ids:
                        del bm25_ranks[eid]

            # --- RRF fusion with recency decay (used for ORDERING only) ---
            k = self._rrf_k
            all_ids = set(vector_ranks.keys()) | set(bm25_ranks.keys())
            scored: list[tuple[str, float]] = []
            for eid in all_ids:
                rrf_score = 0.0
                if eid in vector_ranks:
                    rrf_score += 1.0 / (k + vector_ranks[eid])
                if eid in bm25_ranks:
                    rrf_score += 1.0 / (k + bm25_ranks[eid])
                # Apply recency decay.
                recency = self._recency_weight(entry_created[eid])
                rrf_score *= recency
                scored.append((eid, rrf_score))

            scored.sort(key=lambda x: x[1], reverse=True)

            # The displayed ``score`` is the raw cosine similarity (mapped to
            # [0, 1]), NOT the RRF rank.  RRF only determines result ordering;
            # rescaling the RRF score (e.g. min-max within the candidate set)
            # would make the value meaningless under metadata filters because
            # the per-scope min/max changes with the filter (issue #370).
            results = []
            returned_ids = []
            for eid, _rrf in scored[:limit]:
                results.append(SearchResult(entry=entry_map[eid], score=cosine_score.get(eid, 0.0)))
                returned_ids.append(eid)

            self._touch_accessed(conn, returned_ids)
            return results

        return await self._run_sync(_sync)

    @staticmethod
    def _touch_accessed(conn: duckdb.DuckDBPyConnection, entry_ids: list[str]) -> None:
        """Best-effort update of ``accessed_at`` for the given entry IDs."""
        if not entry_ids:
            return
        try:
            placeholders = ", ".join("?" for _ in entry_ids)
            conn.execute(
                f"UPDATE entries SET accessed_at = current_timestamp WHERE id IN ({placeholders})",
                entry_ids,
            )
        except Exception:  # pragma: no cover
            logger.debug("accessed_at bulk update failed (ignored)")

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

        return await self._run_sync(_sync)

    @overload
    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
        *,
        stale_days: int | None = ...,
        group_by: None = ...,
        output: None = ...,
    ) -> list[Entry]: ...

    @overload
    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
        *,
        stale_days: int | None = ...,
        group_by: str | None = ...,
        output: str | None = ...,
    ) -> list[Entry] | dict[str, Any]: ...

    async def list_entries(
        self,
        filters: dict[str, Any] | None,
        limit: int,
        offset: int,
        *,
        stale_days: int | None = None,
        group_by: str | None = None,
        output: str | None = None,
    ) -> list[Entry] | dict[str, Any]:
        """
        Retrieve entries matching optional filters, ordered by created_at descending.

        When *group_by* is set, delegates to :meth:`aggregate_entries` and
        returns grouped counts.  When *output="stats"*, returns aggregate
        statistics.  Otherwise returns a paginated list of :class:`Entry`
        objects.

        Parameters:
            filters: Filter criteria accepted by the store (see
                ``_build_filter_clauses``).  ``None`` means no filtering.
            limit: Maximum number of entries (or groups) to return.
            offset: Number of entries to skip before returning results
                (ignored in group_by / stats modes).
            stale_days: Restrict to entries whose last access
                (``COALESCE(accessed_at, updated_at)``) is older than N days.
            group_by: Return grouped counts instead of entries.
            output: ``"stats"`` for aggregate statistics.
        """
        # ----- validate stale_days -----
        if stale_days is not None and stale_days < 0:
            raise ValueError("stale_days must be non-negative")

        # ----- reject mutually-exclusive modes -----
        # ``group_by`` and ``output`` return different shapes
        # (grouped counts vs. aggregate stats); combining them would silently
        # drop one. Reject explicitly so callers get a clear error.
        if group_by is not None and output is not None:
            raise ValueError("group_by and output cannot be combined — pick one")

        # ----- group_by mode: delegate to aggregate_entries -----
        if group_by is not None:
            return await self.aggregate_entries(
                group_by=group_by,
                filters=filters,
                limit=limit,
                stale_days=stale_days,
            )

        # ----- stats mode -----
        if output == "stats":
            return await self._get_entry_stats(filters, stale_days=stale_days)

        # ----- default list mode -----
        def _sync() -> list[Entry]:
            conn = self.connection

            where_clauses, params = self._build_filter_clauses(filters)

            if stale_days is not None:
                where_clauses.append(
                    "COALESCE(accessed_at, updated_at) < NOW() - INTERVAL (CAST(? AS INT)) DAYS"
                )
                params.append(stale_days)

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

        return await self._run_sync(_sync)

    async def _get_entry_stats(
        self,
        filters: dict[str, Any] | None,
        *,
        stale_days: int | None = None,
    ) -> dict[str, Any]:
        """Return aggregate statistics for entries matching *filters*.

        Returns a dict with ``entries_by_type``, ``entries_by_status``,
        ``total_entries``, and ``storage_bytes``.
        """
        if stale_days is not None and stale_days < 0:
            raise ValueError("stale_days must be non-negative")

        def _sync() -> dict[str, Any]:
            conn = self.connection

            where_clauses, params = self._build_filter_clauses(filters)

            if stale_days is not None:
                where_clauses.append(
                    "COALESCE(accessed_at, updated_at) < NOW() - INTERVAL (CAST(? AS INT)) DAYS"
                )
                params.append(stale_days)

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # Total count
            total_row = conn.execute(
                f"SELECT COUNT(*) FROM entries {where_sql}", list(params)
            ).fetchone()
            total_entries = int(total_row[0]) if total_row else 0

            # Entries by type
            type_rows = conn.execute(
                f"SELECT entry_type, COUNT(*) AS cnt FROM entries {where_sql} "
                f"GROUP BY entry_type ORDER BY cnt DESC",
                list(params),
            ).fetchall()
            entries_by_type = {str(row[0]): int(row[1]) for row in type_rows}

            # Entries by status
            status_rows = conn.execute(
                f"SELECT status, COUNT(*) AS cnt FROM entries {where_sql} "
                f"GROUP BY status ORDER BY cnt DESC",
                list(params),
            ).fetchall()
            entries_by_status = {str(row[0]): int(row[1]) for row in status_rows}

            # Storage bytes: always reported as the sum of content byte lengths
            # over the matching entries. ``strlen`` returns the UTF-8 byte
            # count (``length`` counts characters), so non-ASCII content is
            # measured correctly. Using a consistent SUM(strlen(content))
            # metric regardless of scope ensures the field is comparable across
            # filtered and unfiltered calls — mixing physical DB size with a
            # filtered content sum would make the same field incomparable.
            storage_bytes: int = 0
            try:
                byte_row = conn.execute(
                    f"SELECT COALESCE(SUM(strlen(content)), 0) FROM entries {where_sql}",
                    list(params),
                ).fetchone()
                storage_bytes = int(byte_row[0]) if byte_row else 0
            except Exception:  # noqa: BLE001
                storage_bytes = 0

            return {
                "entries_by_type": entries_by_type,
                "entries_by_status": entries_by_status,
                "total_entries": total_entries,
                "storage_bytes": storage_bytes,
            }

        return await self._run_sync(_sync)

    async def count_entries(
        self,
        filters: dict[str, Any] | None,
        *,
        stale_days: int | None = None,
    ) -> int:
        """Return the total number of entries matching *filters*.

        Parameters:
            filters: Filter criteria accepted by the store.
            stale_days: When set, only count entries whose last access
                (``COALESCE(accessed_at, updated_at)``) is older than N days.
                Must be non-negative; negatives would invert the cutoff and
                count almost every row.
        """
        if stale_days is not None and stale_days < 0:
            raise ValueError("stale_days must be non-negative")

        def _sync() -> int:
            conn = self.connection
            where_clauses, params = self._build_filter_clauses(filters)
            if stale_days is not None:
                where_clauses.append(
                    "COALESCE(accessed_at, updated_at) < NOW() - INTERVAL (CAST(? AS INT)) DAYS"
                )
                params.append(stale_days)
            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)
            sql = f"SELECT COUNT(*) FROM entries {where_sql}"
            row = conn.execute(sql, params).fetchone()
            return int(row[0]) if row else 0

        return await self._run_sync(_sync)

    async def aggregate_entries(
        self,
        group_by: str,
        filters: dict[str, Any] | None,
        limit: int,
        *,
        stale_days: int | None = None,
    ) -> dict[str, Any]:
        """Return entry counts grouped by *group_by*, sorted by count descending.

        Parameters:
            group_by: Logical field name.  Supported values:
                ``"entry_type"``, ``"status"``, ``"author"``, ``"project"``,
                ``"source"``, ``"tags"``, ``"metadata.source_url"``,
                ``"metadata.source_type"``.  For ``"tags"`` a two-step CTE
                is used to UNNEST the array before aggregating.  The SQL
                expression is resolved here so that callers only ever pass
                the logical name (validated by the MCP layer against an allowlist).
            filters: Optional metadata constraints (see ``_build_filter_clauses``).
            limit: Maximum number of groups to return.
            stale_days: When set, restricts to entries whose last access
                (``COALESCE(accessed_at, updated_at)``) is older than N days.

        Returns:
            Dict with ``"groups"`` (limited list of ``{"value": ..., "count": ...}``
            dicts), ``"total_groups"`` (int), and ``"total_entries"`` (int).  The
            totals reflect the full result set before ``limit`` is applied.
        """
        if stale_days is not None and stale_days < 0:
            raise ValueError("stale_days must be non-negative")
        group_expr = _AGGREGATE_EXPR_MAP[group_by]

        def _sync() -> dict[str, Any]:
            conn = self.connection
            where_clauses, params = self._build_filter_clauses(filters)
            if stale_days is not None:
                where_clauses.append(
                    "COALESCE(accessed_at, updated_at) < NOW() - INTERVAL (CAST(? AS INT)) DAYS"
                )
                params.append(stale_days)
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            # DuckDB does not support UNNEST() directly inside a CTE
            # SELECT, so for array fields (tags) we use a two-step CTE:
            # first explode rows, then aggregate.  Scalar fields use the
            # original single-CTE path.
            if group_by == "tags":
                # When a tag_prefix filter is present we must apply the same
                # filter to the exploded values, otherwise every tag on a
                # matching row would still be counted (e.g. a row tagged
                # ``["topic/ai", "status/draft"]`` with tag_prefix="topic"
                # would contribute "status/draft" to the grouping). We also
                # recompute ``total_entries`` as the number of distinct
                # matched entries rather than the sum of per-group counts,
                # so its semantics stay consistent with scalar group_by.
                tag_prefix_val: str | None = None
                if filters:
                    raw_prefix = filters.get("tag_prefix")
                    if isinstance(raw_prefix, str) and raw_prefix:
                        tag_prefix_val = raw_prefix
                if tag_prefix_val is not None:
                    exploded_sql = (
                        f"SELECT id AS entry_id, UNNEST(tags) AS value FROM entries {where_sql}"
                    )
                    tag_filter_sql = "WHERE value = ? OR starts_with(value, ?)"
                    params_extra = [tag_prefix_val, tag_prefix_val + "/"]
                else:
                    exploded_sql = (
                        f"SELECT id AS entry_id, UNNEST(tags) AS value FROM entries {where_sql}"
                    )
                    tag_filter_sql = ""
                    params_extra = []
                sql = (
                    f"WITH exploded AS ({exploded_sql}), "
                    f"filtered AS (SELECT entry_id, value FROM exploded {tag_filter_sql}), "
                    f"grouped AS ("
                    f"SELECT value, COUNT(*) AS group_count "
                    f"FROM filtered "
                    f"GROUP BY 1"
                    f") "
                    f"SELECT value, group_count, "
                    f"COUNT(*) OVER () AS total_groups, "
                    f"(SELECT COUNT(DISTINCT entry_id) FROM filtered) AS total_entries "
                    f"FROM grouped "
                    f"ORDER BY group_count DESC, value ASC NULLS LAST "
                    f"LIMIT ?"
                )
                # Insert tag_prefix params after the row-level WHERE params so
                # ordering matches placeholder positions.
                params = params + params_extra
            else:
                sql = (
                    f"WITH grouped AS ("
                    f"SELECT {group_expr} AS value, COUNT(*) AS group_count "
                    f"FROM entries "
                    f"{where_sql} "
                    f"GROUP BY 1"
                    f") "
                    f"SELECT value, group_count, "
                    f"COUNT(*) OVER () AS total_groups, "
                    f"COALESCE(SUM(group_count) OVER (), 0) AS total_entries "
                    f"FROM grouped "
                    f"ORDER BY group_count DESC, value ASC NULLS LAST "
                    f"LIMIT ?"
                )
            rows = conn.execute(sql, list(params) + [limit]).fetchall()
            total_groups = int(rows[0][2]) if rows else 0
            total_entries = int(rows[0][3]) if rows else 0
            groups = [{"value": row[0], "count": row[1]} for row in rows]
            return {
                "groups": groups,
                "total_groups": total_groups,
                "total_entries": total_entries,
            }

        return await self._run_sync(_sync)

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    async def write_audit_log(
        self,
        user_id: str,
        tool: str,
        entry_id: str,
        action: str,
        outcome: str,
    ) -> None:
        """Write a record to the ``audit_log`` table.

        Fire-and-forget — failures are logged but never raised.
        """
        import uuid as _uuid

        def _sync() -> None:
            conn = self.connection
            conn.execute(
                "INSERT INTO audit_log (id, user_id, tool, entry_id, action, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [str(_uuid.uuid4()), user_id, tool, entry_id, action, outcome],
            )

        try:
            await self._run_sync(_sync)
        except Exception:  # noqa: BLE001
            logger.debug("audit_log write failed (ignored)", exc_info=True)

    # ------------------------------------------------------------------
    # Audit log queries
    # ------------------------------------------------------------------

    def _sync_query_audit_log(
        self,
        filters: dict[str, Any] | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Synchronous implementation of query_audit_log(); called via asyncio.to_thread.

        Parameters
        ----------
        filters:
            Optional dict of filter constraints.  Supported keys:
            ``user`` (user_id exact match), ``operation`` (tool exact match),
            ``date_from`` (ISO 8601 str, inclusive lower bound on timestamp),
            ``date_to`` (ISO 8601 str, inclusive upper bound on timestamp).
        limit:
            Maximum number of rows to return.  Clamped to [1, 500].

        Returns
        -------
        list[dict[str, Any]]
            Rows ordered by timestamp DESC.  Each dict has keys:
            ``id``, ``timestamp``, ``user_id``, ``tool``, ``entry_id``,
            ``action``, ``outcome``.
        """
        limit = max(1, min(500, limit))

        clauses: list[str] = []
        params: list[Any] = []

        if filters:
            if "user" in filters:
                clauses.append("user_id = ?")
                params.append(filters["user"])
            if "operation" in filters:
                clauses.append("tool = ?")
                params.append(filters["operation"])
            if "date_from" in filters:
                val = filters["date_from"]
                if isinstance(val, str):
                    val = datetime.fromisoformat(val)
                clauses.append("timestamp >= ?")
                params.append(val)
            if "date_to" in filters:
                val = filters["date_to"]
                if isinstance(val, str):
                    val = datetime.fromisoformat(val)
                clauses.append("timestamp <= ?")
                params.append(val)

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        # Format TIMESTAMPTZ as ISO 8601 in UTC to avoid pytz dependency when
        # DuckDB deserialises timezone-aware timestamps to Python.
        sql = (
            f"SELECT id, strftime(timestamp AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S+00:00'), "
            f"user_id, tool, entry_id, action, outcome "
            f"FROM audit_log "
            f"{where_sql} "
            f"ORDER BY timestamp DESC "
            f"LIMIT ?"
        )
        conn = self.connection
        rows = conn.execute(sql, params + [limit]).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "id": row[0],
                    "timestamp": row[1],
                    "user_id": row[2],
                    "tool": row[3],
                    "entry_id": row[4],
                    "action": row[5],
                    "outcome": row[6],
                }
            )
        return result

    async def query_audit_log(
        self,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query the ``audit_log`` table with optional filters.

        Supports filtering by user, operation (tool name), and date range.
        Results are ordered by timestamp descending.

        Supported filter keys:
            - ``user`` (str) -- match ``user_id`` exactly
            - ``operation`` (str) -- match ``tool`` exactly
            - ``date_from`` (str) -- inclusive lower bound on ``timestamp`` (ISO 8601)
            - ``date_to`` (str) -- inclusive upper bound on ``timestamp`` (ISO 8601)

        Args:
            filters: Optional dict of filter constraints.  ``None`` means no
                filtering.
            limit: Maximum number of rows to return.  Must be in [1, 500];
                values outside this range are clamped.  Default is 50.

        Returns:
            List of dicts with keys: ``id``, ``timestamp`` (ISO 8601 str),
            ``user_id``, ``tool``, ``entry_id``, ``action``, ``outcome``.
            Ordered by descending timestamp.
        """
        return await self._run_sync(self._sync_query_audit_log, filters, limit)

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
        return await self._run_sync(
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
        return await self._run_sync(self._sync_log_feedback, search_id, entry_id, signal)

    # ------------------------------------------------------------------
    # Search log queries for implicit feedback
    # ------------------------------------------------------------------

    def _sync_get_searches_for_entry(self, entry_id: str, since: datetime) -> list[str]:
        """Return IDs of search_log rows that include entry_id and are newer than since."""
        conn = self.connection
        sql = (
            "SELECT id FROM search_log WHERE timestamp >= ? AND list_contains(result_entry_ids, ?)"
        )
        rows = conn.execute(sql, [since, entry_id]).fetchall()
        return [row[0] for row in rows]

    async def get_searches_for_entry(self, entry_id: str, since: datetime) -> list[str]:
        """
        Return IDs of recent searches that returned entry_id.

        Queries ``search_log`` directly so the result is durable across process restarts
        (e.g. Lambda invocations). This replaces the former in-memory ``recent_searches``
        list for implicit feedback correlation.

        Parameters:
            entry_id (str): UUID of the entry to look up.
            since (datetime): Inclusive lower bound on ``search_log.timestamp``.

        Returns:
            list[str]: Search IDs (UUIDs) of matching ``search_log`` rows.
        """
        return await self._run_sync(self._sync_get_searches_for_entry, entry_id, since)

    # ------------------------------------------------------------------
    # Feed source persistence
    # ------------------------------------------------------------------

    def _sync_list_feed_sources(self) -> list[dict[str, Any]]:
        """Return all persisted feed sources as dicts.

        Includes liveness fields (``last_polled_at``, ``last_item_count``,
        ``last_error``, ``next_poll_at``) so operators can determine feed
        health from a single query.  Timestamps are serialised to ISO 8601
        strings.  ``next_poll_at`` is derived from ``last_polled_at +
        poll_interval_minutes`` and is ``None`` when the source has never
        been polled.
        """
        from datetime import timedelta

        assert self._conn is not None
        result = self._conn.execute(
            "SELECT url, source_type, label, poll_interval_minutes, trust_weight, "
            "last_polled_at, last_item_count, last_error "
            "FROM feed_sources ORDER BY created_at"
        )
        rows = result.fetchall()
        sources: list[dict[str, Any]] = []
        for row in rows:
            last_polled_raw: datetime | None = row[5]
            poll_interval_minutes: int = row[3]
            # DuckDB TIMESTAMP is naive — assume UTC and attach tzinfo so the
            # serialised value preserves the "+00:00" offset downstream.
            last_polled_at: datetime | None = None
            if last_polled_raw is not None:
                last_polled_at = (
                    last_polled_raw.replace(tzinfo=UTC)
                    if last_polled_raw.tzinfo is None
                    else last_polled_raw.astimezone(UTC)
                )
            last_polled_iso: str | None = (
                last_polled_at.isoformat() if last_polled_at is not None else None
            )
            next_poll_at: str | None = (
                (last_polled_at + timedelta(minutes=poll_interval_minutes)).isoformat()
                if last_polled_at is not None
                else None
            )
            sources.append(
                {
                    "url": row[0],
                    "source_type": row[1],
                    "label": row[2],
                    "poll_interval_minutes": poll_interval_minutes,
                    "trust_weight": row[4],
                    "last_polled_at": last_polled_iso,
                    "last_item_count": row[6] if row[6] is not None else 0,
                    "last_error": row[7],
                    "next_poll_at": next_poll_at,
                }
            )
        return sources

    def _sync_add_feed_source(
        self,
        url: str,
        source_type: str,
        label: str = "",
        poll_interval_minutes: int = 60,
        trust_weight: float = 1.0,
    ) -> dict[str, Any]:
        """Add a feed source. Raises ValueError if URL already exists."""
        assert self._conn is not None
        try:
            self._conn.execute(
                "INSERT INTO feed_sources "
                "(url, source_type, label, poll_interval_minutes, trust_weight) "
                "VALUES (?, ?, ?, ?, ?)",
                [url, source_type, label, poll_interval_minutes, trust_weight],
            )
        except duckdb.ConstraintException as exc:
            raise ValueError(f"Feed source with URL {url!r} already exists.") from exc
        return {
            "url": url,
            "source_type": source_type,
            "label": label,
            "poll_interval_minutes": poll_interval_minutes,
            "trust_weight": trust_weight,
        }

    def _sync_remove_feed_source(self, url: str) -> bool:
        """Remove a feed source by URL. Returns True if it existed."""
        assert self._conn is not None
        result = self._conn.execute("DELETE FROM feed_sources WHERE url = ? RETURNING url", [url])
        return len(result.fetchall()) > 0

    # Maximum length of a persisted ``last_error`` string.  Longer errors are
    # truncated to keep the liveness payload small and to avoid storing
    # sensitive traceback fragments verbatim.
    _LAST_ERROR_MAX_LEN = 200

    def _sync_record_poll_status(
        self,
        url: str,
        *,
        polled_at: datetime,
        item_count: int,
        error: str | None,
    ) -> bool:
        """Persist the outcome of a poll against a feed source.

        Stores *polled_at*, *item_count*, and a truncated+sanitised *error*
        (or ``NULL``) on the matching ``feed_sources`` row.  Returns
        ``True`` when a row was updated, ``False`` when no source with
        *url* exists.
        """
        assert self._conn is not None
        item_count_int = int(item_count)
        if item_count_int < 0:
            raise ValueError(f"item_count must be non-negative, got: {item_count_int}")
        truncated = _sanitise_last_error(error, self._LAST_ERROR_MAX_LEN)
        # DuckDB's ``TIMESTAMP`` column is timezone-naive — a tz-aware value
        # can be silently coerced or rejected depending on the driver version,
        # which in production surfaced as ``last_polled_at`` staying ``NULL``
        # despite a successful poll (issue #334).  Normalise to naive UTC so
        # the stored value matches what ``_sync_list_feed_sources`` expects
        # (see the naive-UTC reattachment around line 2054).
        polled_at_naive = (
            polled_at.astimezone(UTC).replace(tzinfo=None)
            if polled_at.tzinfo is not None
            else polled_at
        )
        result = self._conn.execute(
            "UPDATE feed_sources "
            "SET last_polled_at = ?, last_item_count = ?, last_error = ? "
            "WHERE url = ? RETURNING url",
            [polled_at_naive, item_count_int, truncated, url],
        )
        return len(result.fetchall()) > 0

    async def list_feed_sources(self) -> list[dict[str, Any]]:
        """Return all persisted feed sources as dicts."""
        return await self._run_sync(self._sync_list_feed_sources)

    async def add_feed_source(
        self,
        url: str,
        source_type: str,
        label: str = "",
        poll_interval_minutes: int = 60,
        trust_weight: float = 1.0,
    ) -> dict[str, Any]:
        """Add a feed source. Raises ValueError if URL already exists."""
        return await self._run_sync(
            self._sync_add_feed_source, url, source_type, label, poll_interval_minutes, trust_weight
        )

    async def remove_feed_source(self, url: str) -> bool:
        """Remove a feed source by URL. Returns True if it existed."""
        return await self._run_sync(self._sync_remove_feed_source, url)

    async def record_poll_status(
        self,
        url: str,
        *,
        polled_at: datetime,
        item_count: int,
        error: str | None,
    ) -> bool:
        """Record the outcome of a poll against a feed source.

        Args:
            url: The feed source URL (primary key).
            polled_at: UTC timestamp of the poll attempt.
            item_count: Items successfully ingested during the poll.
            error: Error message when the poll failed, or ``None`` on success.
                The value is truncated and sanitised before persistence.

        Returns:
            ``True`` if a matching row was updated, ``False`` if no source
            with *url* exists.
        """
        return await self._run_sync(
            self._sync_record_poll_status,
            url,
            polled_at=polled_at,
            item_count=item_count,
            error=error,
        )

    # ------------------------------------------------------------------
    # Metadata helpers
    # ------------------------------------------------------------------

    def _sync_get_metadata(self, key: str) -> str | None:
        """Read a value from the ``_meta`` table."""
        assert self._conn is not None
        result = self._conn.execute("SELECT value FROM _meta WHERE key = ?", [key])
        row = result.fetchone()
        return row[0] if row else None

    def _sync_set_metadata(self, key: str, value: str) -> None:
        """Upsert a value into the ``_meta`` table."""
        assert self._conn is not None
        self._conn.execute(
            "INSERT INTO _meta (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            [key, value],
        )

    async def get_metadata(self, key: str) -> str | None:
        """Read a value from the ``_meta`` key-value table."""
        return await self._run_sync(self._sync_get_metadata, key)

    async def set_metadata(self, key: str, value: str) -> None:
        """Write a value to the ``_meta`` key-value table (upsert)."""
        await self._run_sync(self._sync_set_metadata, key, value)

    def _sync_prune_search_log(self, retention_days: int) -> int:
        """Delete ``search_log`` rows older than *retention_days*.

        Raises
        ------
        ValueError
            If *retention_days* is not a non-negative integer. Negative values
            flip the interval sign and would match almost the entire table.

        Returns
        -------
        int
            The number of rows deleted.
        """
        assert self._conn is not None
        if not isinstance(retention_days, int) or isinstance(retention_days, bool):
            raise ValueError("retention_days must be a non-negative integer")
        if retention_days < 0:
            raise ValueError(
                f"retention_days must be a non-negative integer, got: {retention_days}"
            )
        result = self._conn.execute(
            "DELETE FROM search_log "
            "WHERE timestamp < current_timestamp - INTERVAL (CAST(? AS INT)) DAYS "
            "RETURNING id",
            [retention_days],
        ).fetchall()
        return len(result)

    async def prune_search_log(self, retention_days: int) -> int:
        """Delete ``search_log`` rows older than *retention_days* (async wrapper)."""
        return await self._run_sync(self._sync_prune_search_log, retention_days)

    # ------------------------------------------------------------------
    # Tag vocabulary
    # ------------------------------------------------------------------

    def _sync_get_tag_vocabulary(self, prefix: str | None) -> dict[str, int]:
        """Synchronous implementation of get_tag_vocabulary(); called via asyncio.to_thread."""
        assert self._conn is not None
        result = self._conn.execute("SELECT tags FROM entries WHERE status != 'archived'")
        rows = result.fetchall()

        counts: dict[str, int] = {}
        prefix_slash = (prefix + "/") if prefix is not None else None
        for (tags_col,) in rows:
            if not tags_col:
                continue
            for tag in tags_col:
                if (
                    prefix is not None
                    and tag != prefix
                    and (prefix_slash is None or not tag.startswith(prefix_slash))
                ):
                    continue
                counts[tag] = counts.get(tag, 0) + 1

        return counts

    async def get_tag_vocabulary(self, prefix: str | None = None) -> dict[str, int]:
        """Return a mapping of tag to occurrence count across active entries.

        Args:
            prefix: Optional hierarchical tag prefix to filter by.

        Returns:
            Dict mapping each matching tag string to its occurrence count.
        """
        return await self._run_sync(self._sync_get_tag_vocabulary, prefix)

    # ------------------------------------------------------------------
    # Entry relations
    # ------------------------------------------------------------------

    def _sync_add_relation(self, from_id: str, to_id: str, relation_type: str) -> str:
        """Synchronous implementation of add_relation(); called via asyncio.to_thread."""
        assert self._conn is not None
        # Validate that both entries exist (including archived — preserves historical links)
        from_row = self._conn.execute("SELECT id FROM entries WHERE id = ?", [from_id]).fetchone()
        if from_row is None:
            raise ValueError(f"Entry not found: from_id={from_id!r}")
        to_row = self._conn.execute("SELECT id FROM entries WHERE id = ?", [to_id]).fetchone()
        if to_row is None:
            raise ValueError(f"Entry not found: to_id={to_id!r}")
        # Check for existing relation with the same (from_id, to_id, relation_type)
        existing = self._conn.execute(
            "SELECT id FROM entry_relations WHERE from_id = ? AND to_id = ? AND relation_type = ?",
            [from_id, to_id, relation_type],
        ).fetchone()
        if existing is not None:
            logger.debug(
                "Relation already exists id=%s from=%s to=%s type=%s",
                existing[0],
                from_id,
                to_id,
                relation_type,
            )
            return str(existing[0])
        relation_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO entry_relations (id, from_id, to_id, relation_type) VALUES (?, ?, ?, ?)",
            [relation_id, from_id, to_id, relation_type],
        )
        logger.debug(
            "Added relation id=%s from=%s to=%s type=%s",
            relation_id,
            from_id,
            to_id,
            relation_type,
        )
        return relation_id

    async def add_relation(
        self,
        from_id: str,
        to_id: str,
        relation_type: str,
    ) -> str:
        """Create a typed relation between two entries and return its UUID.

        The method is idempotent: if a relation with the same ``(from_id,
        to_id, relation_type)`` triple already exists, its existing UUID is
        returned instead of creating a duplicate row.

        Args:
            from_id: UUID string of the source entry.
            to_id: UUID string of the target entry.
            relation_type: Freeform label for the relation (e.g. ``"link"``,
                ``"blocks"``, ``"related"``).

        Returns:
            The UUID string of the relation row (existing or newly created).

        Raises:
            ValueError: If either ``from_id`` or ``to_id`` does not exist in
                the store.
        """
        return await self._run_sync(self._sync_add_relation, from_id, to_id, relation_type)

    def _sync_apply_correction(
        self,
        new_entry: Entry,
        wrong_entry_id: str,
    ) -> str:
        """Store a correction entry, link it to the original, and archive the original.

        All three mutations (INSERT new entry, INSERT relation, UPDATE original
        status) run inside a single transaction so the write set is atomic.

        Args:
            new_entry: The fully constructed correction ``Entry``.
            wrong_entry_id: UUID of the original entry being corrected.

        Returns:
            The UUID string of the newly stored correction entry.

        Raises:
            RuntimeError: If any step fails; the transaction is rolled back.
        """
        conn = self.connection
        embedding = self._embedding_provider.embed(new_entry.content)

        try:
            conn.execute("BEGIN TRANSACTION")

            # 1. Store the correction entry.
            insert_sql = (
                "INSERT INTO entries "
                "(id, content, entry_type, source, author, project, tags, status, "
                " verification, metadata, created_at, updated_at, version, embedding, "
                " created_by, last_modified_by, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            )
            conn.execute(
                insert_sql,
                [
                    new_entry.id,
                    new_entry.content,
                    new_entry.entry_type.value,
                    new_entry.source.value,
                    new_entry.author,
                    new_entry.project,
                    list(new_entry.tags),
                    new_entry.status.value,
                    new_entry.verification.value,
                    json.dumps(new_entry.metadata),
                    new_entry.created_at,
                    new_entry.updated_at,
                    new_entry.version,
                    embedding,
                    new_entry.created_by,
                    new_entry.last_modified_by,
                    new_entry.expires_at,
                ],
            )

            # 2. Create the "corrects" relation.
            relation_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO entry_relations (id, from_id, to_id, relation_type) "
                "VALUES (?, ?, ?, ?)",
                [relation_id, new_entry.id, wrong_entry_id, "corrects"],
            )

            # 3. Archive the original entry.
            now = datetime.now(tz=UTC)
            conn.execute(
                "UPDATE entries SET status = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                ["archived", now, wrong_entry_id],
            )

            conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise

        # Rebuild FTS index outside the transaction (non-critical).
        self._rebuild_fts_index(conn)
        logger.debug(
            "Applied correction: new=%s original=%s (archived)",
            new_entry.id,
            wrong_entry_id,
        )
        return new_entry.id

    async def apply_correction(
        self,
        new_entry: Entry,
        wrong_entry_id: str,
    ) -> str:
        """Atomically store a correction, link it, and archive the original.

        See :meth:`_sync_apply_correction` for details.
        """
        return await self._run_sync(self._sync_apply_correction, new_entry, wrong_entry_id)

    def _sync_get_related(
        self,
        entry_id: str,
        direction: str,
        relation_type: str | None,
    ) -> list[dict[str, Any]]:
        """Synchronous implementation of get_related(); called via asyncio.to_thread."""
        assert self._conn is not None
        _valid_directions = ("outgoing", "incoming", "both")
        if direction not in _valid_directions:
            raise ValueError(f"Invalid direction {direction!r}, must be one of {_valid_directions}")
        conditions: list[str] = []
        params: list[Any] = []

        if direction == "outgoing":
            conditions.append("from_id = ?")
            params.append(entry_id)
        elif direction == "incoming":
            conditions.append("to_id = ?")
            params.append(entry_id)
        else:  # "both"
            conditions.append("(from_id = ? OR to_id = ?)")
            params.extend([entry_id, entry_id])

        if relation_type is not None:
            conditions.append("relation_type = ?")
            params.append(relation_type)

        where_clause = " AND ".join(conditions)
        sql = (
            f"SELECT id, from_id, to_id, relation_type, "
            f"strftime(created_at, '%Y-%m-%dT%H:%M:%S') || 'Z' "
            f"FROM entry_relations WHERE {where_clause} ORDER BY created_at ASC"
        )
        result = self._conn.execute(sql, params)
        rows = result.fetchall()
        return [
            {
                "id": row[0],
                "from_id": row[1],
                "to_id": row[2],
                "relation_type": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    async def get_related(
        self,
        entry_id: str,
        direction: str = "both",
        relation_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return relations for an entry, optionally filtered by direction and type.

        Args:
            entry_id: UUID string of the entry whose relations to fetch.
            direction: One of ``"outgoing"``, ``"incoming"``, or ``"both"``
                (default).
            relation_type: Optional filter restricting results to this type.

        Returns:
            List of dicts with keys: ``id``, ``from_id``, ``to_id``,
            ``relation_type``, ``created_at`` (ISO 8601 str).
        """
        return await self._run_sync(self._sync_get_related, entry_id, direction, relation_type)

    def _sync_remove_relation(self, relation_id: str) -> bool:
        """Synchronous implementation of remove_relation(); called via asyncio.to_thread."""
        assert self._conn is not None
        result = self._conn.execute(
            "DELETE FROM entry_relations WHERE id = ? RETURNING id", [relation_id]
        )
        deleted = result.fetchall()
        found = len(deleted) > 0
        if found:
            logger.debug("Removed relation id=%s", relation_id)
        return found

    async def remove_relation(self, relation_id: str) -> bool:
        """Delete a relation row by its UUID.

        Args:
            relation_id: UUID string of the ``entry_relations`` row to remove.

        Returns:
            ``True`` if the row existed and was deleted, ``False`` otherwise.
        """
        return await self._run_sync(self._sync_remove_relation, relation_id)

    def _sync_get_all_related_entry_ids(self) -> set[str]:
        """Synchronous implementation of get_all_related_entry_ids()."""
        assert self._conn is not None
        # Single scan over entry_relations to collect every entry id that
        # appears as either endpoint of any relation. Used by the orphan
        # filter on distillery_list to identify entries with no relations.
        rows = self._conn.execute(
            "SELECT from_id FROM entry_relations UNION SELECT to_id FROM entry_relations"
        ).fetchall()
        return {row[0] for row in rows}

    async def get_all_related_entry_ids(self) -> set[str]:
        """Return the set of entry IDs that appear in any ``entry_relations`` row.

        Used by structural filters (e.g. orphan detection) on
        ``distillery_list``: the complement set is the orphan set. Returns
        an empty set when no relations exist.

        Returns:
            Set of entry UUID strings appearing as either ``from_id`` or
            ``to_id`` in at least one row of ``entry_relations``.
        """
        return await self._run_sync(self._sync_get_all_related_entry_ids)
