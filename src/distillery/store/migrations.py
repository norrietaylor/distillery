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
import re
from typing import Any, Protocol

import duckdb

logger = logging.getLogger(__name__)


class MigrationFunc(Protocol):
    """Callable protocol for migration functions.

    Migrations accept a DuckDB connection and optional keyword arguments
    for runtime configuration (e.g. ``dimensions``, ``vss_available``).
    """

    def __call__(self, conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None: ...


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

_CREATE_ENTRY_RELATIONS_TO_ID_INDEX = """
CREATE INDEX IF NOT EXISTS idx_entry_relations_to_id
ON entry_relations (to_id);
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_search_log_timestamp ON search_log (timestamp)")
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


_WIKILINK_PATTERN = re.compile(r"\[\[entry-([0-9A-Fa-f]{8})\]\]")


def backfill_relations_from_wikilinks(conn: duckdb.DuckDBPyConnection) -> int:
    """Scan ``entries.content`` for ``[[entry-<8-hex>]]`` refs and insert ``link`` rows.

    Idempotent: relies on the ``idx_entry_relations_unique`` unique index on
    ``(from_id, to_id, relation_type)`` so re-running never produces duplicates.
    Returns the number of rows actually inserted (excludes index-suppressed
    duplicates, self-references, dangling targets and ambiguous prefixes).

    This helper is the single source of truth for mechanism #8 in issue #496
    (inline wikilink reference parsing).  Entry IDs are UUID4 strings, so the
    leading 8-hex prefix is the first dash-delimited segment.  When two or
    more existing entries share the same 8-hex prefix the reference is
    ambiguous and is skipped entirely (no edge is written to either
    candidate) — idempotency + safety beat completeness.

    The caller is responsible for transaction management — this function
    assumes ``entry_relations`` (and its unique index) already exist.
    """
    import uuid

    # Build a prefix -> id map up front.  Prefixes that collide (>= 2 entries
    # share the same first 8 hex chars) are tracked as "ambiguous" and
    # excluded from the lookup, mirroring the safety-over-completeness rule.
    prefix_to_id: dict[str, str] = {}
    ambiguous: set[str] = set()
    all_ids: set[str] = set()
    for (entry_id,) in conn.execute("SELECT id FROM entries").fetchall():
        if not isinstance(entry_id, str) or len(entry_id) < 8:
            continue
        all_ids.add(entry_id)
        prefix = entry_id[:8].lower()
        if prefix in ambiguous:
            continue
        existing = prefix_to_id.get(prefix)
        if existing is None:
            prefix_to_id[prefix] = entry_id
        elif existing != entry_id:
            # Two distinct entries share the same 8-hex prefix — refuse to
            # link to either to avoid silently picking the wrong target.
            ambiguous.add(prefix)
            del prefix_to_id[prefix]
            logger.debug(
                "Wikilink backfill: prefix %r is ambiguous; skipping all references", prefix
            )

    rows = conn.execute("SELECT id, content FROM entries WHERE content IS NOT NULL").fetchall()
    inserted = 0
    for entry_id, content in rows:
        if not isinstance(content, str) or not content:
            continue
        # ``set`` to dedupe multiple occurrences of the same prefix within a
        # single entry — the unique index would catch them anyway, but this
        # avoids the extra round-trips.
        seen_prefixes: set[str] = set()
        for match in _WIKILINK_PATTERN.finditer(content):
            prefix = match.group(1).lower()
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            to_id = prefix_to_id.get(prefix)
            if to_id is None:
                # Either ambiguous (already logged above) or no such entry.
                continue
            if to_id == entry_id:
                # Self-references are not meaningful.
                continue
            if to_id not in all_ids:
                continue
            relation_id = str(uuid.uuid4())
            row = conn.execute(
                "INSERT OR IGNORE INTO entry_relations (id, from_id, to_id, relation_type) "
                "VALUES (?, ?, ?, 'link') RETURNING id",
                [relation_id, entry_id, to_id],
            ).fetchone()
            if row:
                inserted += 1

    return inserted


# Matches absolute http(s) URLs embedded in entry content.  Trailing
# punctuation (``.``, ``,``, ``)``, ``]``, ``>``) is excluded so a URL at the
# end of a sentence resolves cleanly against a stored ``external_id``.
_CONTENT_URL_PATTERN = re.compile(r"https?://[^\s<>\")\]]+")

# Matches bare ``#<number>`` references (issue/PR shorthand) in content.  The
# leading boundary forbids a preceding word char so ``foo#7`` (e.g. a fragment
# of an existing external_id pasted verbatim) is not double-counted here.
_CONTENT_HASH_REF_PATTERN = re.compile(r"(?<![\w#])#(\d+)\b")

# Extracts the trailing issue/PR number from an external_id fragment such as
# ``owner/repo#issue-7``, ``owner/repo#pr-12`` or the bare ``owner/repo#7``.
_EXTERNAL_ID_NUMBER_PATTERN = re.compile(r"#(?:issue-|pr-)?(\d+)$")


def backfill_relations_from_content_refs(conn: duckdb.DuckDBPyConnection) -> int:
    """Scan ``entries.content`` for URLs / ``#<number>`` refs and insert ``citation`` rows.

    Resolves each in-content reference to a stored entry via its
    ``metadata.external_id`` and materialises a ``citation`` edge from the
    scanning entry to the resolved entry.  Two reference shapes are handled:

      * **Absolute URLs** (``https?://…``) are matched exactly against the set
        of stored ``external_id`` values — so an entry whose ``external_id`` is
        ``https://github.com/owner/repo/pull/12`` is linked when another
        entry's content contains that URL verbatim.
      * **Bare ``#<number>`` refs** are resolved against the trailing number of
        ``external_id`` values shaped like ``owner/repo#issue-7``,
        ``owner/repo#pr-12`` or ``owner/repo#7``.  When two or more entries map
        to the same number the reference is ambiguous and skipped entirely.

    Idempotent: relies on the ``idx_entry_relations_unique`` unique index on
    ``(from_id, to_id, relation_type)`` so re-running never produces
    duplicates.  Self-edges and references to absent targets are skipped.
    Returns the number of rows actually inserted.

    This is mechanism for in-content reference resolution (issue #653 step 4).
    The caller is responsible for transaction management — this function
    assumes ``entry_relations`` (and its unique index) already exist.
    """
    import json
    import uuid

    all_ids: set[str] = set()
    # external_id (URL form) -> entry_id, for exact URL matching.  URLs that
    # map to two distinct entries are tracked as ambiguous and excluded so the
    # backfill stays deterministic and idempotent across runs.
    url_to_id: dict[str, str] = {}
    ambiguous_urls: set[str] = set()
    # issue/PR number -> entry_id, for ``#<number>`` matching.  Numbers that
    # map to two distinct entries are tracked as ambiguous and excluded.
    number_to_id: dict[int, str] = {}
    ambiguous_numbers: set[int] = set()

    rows = conn.execute("SELECT id, metadata FROM entries WHERE metadata IS NOT NULL").fetchall()
    for entry_id, metadata_raw in rows:
        if not isinstance(entry_id, str):
            continue
        all_ids.add(entry_id)
        try:
            if isinstance(metadata_raw, str):
                meta = json.loads(metadata_raw)
            elif isinstance(metadata_raw, dict):
                meta = metadata_raw
            else:
                continue
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(meta, dict):
            continue
        external_id = meta.get("external_id")
        if not isinstance(external_id, str) or not external_id:
            continue
        # Deterministic handling of duplicate URLs: once a URL maps to two
        # distinct entries it is ambiguous and excluded from resolution.
        if external_id.startswith(("http://", "https://")) and external_id not in ambiguous_urls:
            existing_url_target = url_to_id.get(external_id)
            if existing_url_target is None:
                url_to_id[external_id] = entry_id
            elif existing_url_target != entry_id:
                ambiguous_urls.add(external_id)
                del url_to_id[external_id]
                logger.debug(
                    "Content-ref backfill: URL %s maps to multiple entries; skipping",
                    external_id,
                )
        number_match = _EXTERNAL_ID_NUMBER_PATTERN.search(external_id)
        if number_match:
            number = int(number_match.group(1))
            if number in ambiguous_numbers:
                continue
            existing = number_to_id.get(number)
            if existing is None:
                number_to_id[number] = entry_id
            elif existing != entry_id:
                ambiguous_numbers.add(number)
                del number_to_id[number]
                logger.debug("Content-ref backfill: #%d maps to multiple entries; skipping", number)

    # Capture entries that carry no metadata too — they can still cite others.
    for (entry_id,) in conn.execute("SELECT id FROM entries WHERE metadata IS NULL").fetchall():
        if isinstance(entry_id, str):
            all_ids.add(entry_id)

    content_rows = conn.execute(
        "SELECT id, content FROM entries WHERE content IS NOT NULL"
    ).fetchall()
    inserted = 0
    for entry_id, content in content_rows:
        if not isinstance(entry_id, str) or not isinstance(content, str) or not content:
            continue
        # Dedupe resolved targets per source entry — the unique index would
        # catch repeats anyway, but this avoids redundant round-trips.
        targets: set[str] = set()
        for url_match in _CONTENT_URL_PATTERN.finditer(content):
            # Strip trailing punctuation (e.g. a sentence-final ``.``/``,`` or a
            # closing ``)``/``]``/``>``) so a URL at the end of a sentence still
            # resolves against the stored ``external_id``.
            raw_url = url_match.group(0).rstrip(".,)]>")
            to_id = url_to_id.get(raw_url)
            if to_id is not None:
                targets.add(to_id)
        for hash_match in _CONTENT_HASH_REF_PATTERN.finditer(content):
            to_id = number_to_id.get(int(hash_match.group(1)))
            if to_id is not None:
                targets.add(to_id)

        for to_id in targets:
            if to_id == entry_id:
                # Self-citations are not meaningful.
                continue
            if to_id not in all_ids:
                continue
            relation_id = str(uuid.uuid4())
            row = conn.execute(
                "INSERT OR IGNORE INTO entry_relations (id, from_id, to_id, relation_type) "
                "VALUES (?, ?, ?, 'citation') RETURNING id",
                [relation_id, entry_id, to_id],
            ).fetchone()
            if row:
                inserted += 1

    return inserted


def backfill_relations_from_metadata(conn: duckdb.DuckDBPyConnection) -> int:
    """Scan ``entries.metadata.related_entries`` and insert missing ``entry_relations`` rows.

    Idempotent: relies on the ``idx_entry_relations_unique`` unique index on
    ``(from_id, to_id, relation_type)`` so re-running never produces duplicates.
    Returns the number of rows actually inserted (excludes index-suppressed
    duplicates).

    This helper is the single source of truth for mechanism #1 in issue #490
    (re-scan on upgrade and on every write) and is invoked from:

      * Migration 8 (initial table creation + backfill).
      * The ``DuckDBStore`` write paths (``_sync_store``,
        ``_sync_store_batch``, ``_sync_update``) after entry insert.
      * ``distillery_relations action="reconcile"`` for operator-initiated
        recovery from drift.

    The caller is responsible for transaction management — this function
    assumes ``entry_relations`` (and its unique index) already exist.
    """
    import json
    import uuid

    existing_ids: set[str] = {r[0] for r in conn.execute("SELECT id FROM entries").fetchall()}
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

        # ``json.loads`` can return list/str/number/None for malformed blobs;
        # guard so a single bad row doesn't abort the whole backfill/reconcile.
        if not isinstance(meta, dict):
            continue

        related: object = meta.get("related_entries")
        if not isinstance(related, list):
            continue

        for to_id in related:
            if not isinstance(to_id, str) or not to_id:
                continue
            if to_id == entry_id:
                # Self-loops are not meaningful for related_entries.
                continue
            if to_id not in existing_ids:
                continue
            relation_id = str(uuid.uuid4())
            inserted = conn.execute(
                "INSERT OR IGNORE INTO entry_relations (id, from_id, to_id, relation_type) "
                "VALUES (?, ?, ?, 'link') RETURNING id",
                [relation_id, entry_id, to_id],
            ).fetchone()
            if inserted:
                backfilled += 1

    return backfilled


def create_entry_relations(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 8: Create ``entry_relations`` table and backfill from metadata.

    Creates the ``entry_relations`` table for typed, queryable relationships
    between entries.  After table creation, backfills existing entries whose
    ``metadata`` JSON column contains a ``related_entries`` list: each element
    is inserted as a row with ``relation_type='link'``.

    The backfill is idempotent — the underlying
    :func:`backfill_relations_from_metadata` helper relies on the unique
    ``(from_id, to_id, relation_type)`` index — and is reused on every store
    startup (issue #490) so entries written before this migration first ran
    populate edges retroactively.
    """
    conn.execute(_CREATE_ENTRY_RELATIONS_TABLE)
    conn.execute(_CREATE_ENTRY_RELATIONS_UNIQUE_INDEX)
    conn.execute(_CREATE_ENTRY_RELATIONS_TO_ID_INDEX)
    logger.info("Migration 8: entry_relations table created")

    backfilled = backfill_relations_from_metadata(conn)
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
        # ``INSTALL fts`` may leave the current transaction in an aborted state
        # when it fails — rollback and begin a fresh transaction so the
        # schema_version INSERT in run_pending_migrations can proceed.
        with contextlib.suppress(duckdb.Error):
            conn.execute("ROLLBACK")
        try:
            conn.execute("BEGIN TRANSACTION")
        except duckdb.Error as begin_exc:
            raise RuntimeError(
                "Migration 7: failed to restart transaction after FTS rollback — "
                "database may be in an inconsistent state"
            ) from begin_exc
        kwargs["fts_available"] = False
        logger.warning("Migration 7: FTS extension install failed (offline?): %s", exc)
    except Exception:
        logger.exception("Migration 7: unexpected FTS index creation failure")
        raise


_ADD_EXPIRES_AT_COLUMN = """
ALTER TABLE entries ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
"""


def add_expires_at(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 9: Add ``expires_at`` column to ``entries``."""
    conn.execute(_ADD_EXPIRES_AT_COLUMN)
    logger.info("Migration 9: expires_at column added")


_ADD_VERIFICATION_COLUMN = """
ALTER TABLE entries ADD COLUMN IF NOT EXISTS verification VARCHAR DEFAULT 'unverified';
"""


def add_verification(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 10: Add ``verification`` column to ``entries``."""
    conn.execute(_ADD_VERIFICATION_COLUMN)
    logger.info("Migration 10: verification column added")


_ADD_SESSION_ID_COLUMN = """
ALTER TABLE entries ADD COLUMN IF NOT EXISTS session_id VARCHAR;
"""


def add_session_id(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 11: Add ``session_id`` column to ``entries``."""
    conn.execute(_ADD_SESSION_ID_COLUMN)
    logger.info("Migration 11: session_id column added")


_ADD_FEED_SOURCE_LIVENESS_COLUMNS = [
    "ALTER TABLE feed_sources ADD COLUMN IF NOT EXISTS last_polled_at TIMESTAMP;",
    "ALTER TABLE feed_sources ADD COLUMN IF NOT EXISTS last_item_count INTEGER DEFAULT 0;",
    "ALTER TABLE feed_sources ADD COLUMN IF NOT EXISTS last_error VARCHAR;",
]


def add_feed_source_liveness(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 12: Add liveness columns to ``feed_sources``.

    Adds three nullable columns used by operators to answer "is this feed
    working?" without consulting a separate sync-status tool:

    - ``last_polled_at`` (TIMESTAMP) — UTC instant of the most recent poll.
    - ``last_item_count`` (INTEGER) — items ingested on the last poll.
    - ``last_error`` (VARCHAR) — truncated error message from the last poll,
      or ``NULL`` when the poll succeeded.
    """
    for stmt in _ADD_FEED_SOURCE_LIVENESS_COLUMNS:
        conn.execute(stmt)
    logger.info("Migration 12: feed_sources liveness columns added")


_CREATE_SYNC_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS sync_jobs (
    job_id            VARCHAR PRIMARY KEY,
    source_url        VARCHAR NOT NULL,
    source_type       VARCHAR NOT NULL,
    status            VARCHAR NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    entries_created   INTEGER NOT NULL DEFAULT 0,
    entries_updated   INTEGER NOT NULL DEFAULT 0,
    relations_created INTEGER NOT NULL DEFAULT 0,
    pages_processed   INTEGER NOT NULL DEFAULT 0,
    errors            VARCHAR,
    error_message     VARCHAR,
    result            VARCHAR
);
"""

_CREATE_SYNC_JOBS_CREATED_AT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_sync_jobs_created_at
ON sync_jobs (created_at);
"""


def create_sync_jobs(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 13: Create the ``sync_jobs`` table.

    Backs the :class:`distillery.feeds.sync_jobs.SyncJobTracker` so background
    gh-sync / feed-history jobs survive server restarts. Fields mirror
    :class:`distillery.feeds.sync_jobs.SyncJob`; ``errors`` and ``result``
    are JSON-encoded strings.
    """
    conn.execute(_CREATE_SYNC_JOBS_TABLE)
    conn.execute(_CREATE_SYNC_JOBS_CREATED_AT_INDEX)
    logger.info("Migration 13: sync_jobs table created")


_ADD_FEED_SOURCE_THRESHOLD_COLUMNS = [
    "ALTER TABLE feed_sources ADD COLUMN IF NOT EXISTS threshold_alert FLOAT;",
    "ALTER TABLE feed_sources ADD COLUMN IF NOT EXISTS threshold_digest FLOAT;",
]


def add_feed_source_thresholds(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 14: Add per-source threshold override columns.

    Adds two nullable ``FLOAT`` columns to ``feed_sources``:

    - ``threshold_alert`` — overrides ``feeds.thresholds.alert`` for this
      source when non-NULL.
    - ``threshold_digest`` — overrides ``feeds.thresholds.digest`` for this
      source when non-NULL.

    NULL means "fall back to global", preserving pre-#480 behaviour for
    sources that were created before the migration ran.
    """
    for stmt in _ADD_FEED_SOURCE_THRESHOLD_COLUMNS:
        conn.execute(stmt)
    logger.info("Migration 14: feed_sources threshold override columns added")


_ADD_ENTRY_RELATION_ATTRIBUTE_COLUMNS = [
    "ALTER TABLE entry_relations ADD COLUMN IF NOT EXISTS weight DOUBLE;",
    "ALTER TABLE entry_relations ADD COLUMN IF NOT EXISTS valid_at TIMESTAMPTZ;",
    "ALTER TABLE entry_relations ADD COLUMN IF NOT EXISTS invalid_at TIMESTAMPTZ;",
    "ALTER TABLE entry_relations ADD COLUMN IF NOT EXISTS metadata JSON;",
]


def add_relation_attributes(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 15: Add weight, temporal validity, and metadata to ``entry_relations``.

    Adds four nullable columns so edges can carry strength and a bi-temporal
    validity window in addition to their type:

    - ``weight`` (DOUBLE) — edge strength (e.g. interest/engagement magnitude).
    - ``valid_at`` (TIMESTAMPTZ) — when the relationship became true.
    - ``invalid_at`` (TIMESTAMPTZ) — when it stopped being true (NULL = still
      valid).
    - ``metadata`` (JSON) — arbitrary per-edge attributes, mirroring
      ``entries.metadata``.

    All columns are nullable with no default, so existing edges and the
    metadata/wikilink backfill paths (which omit them) remain valid; NULL means
    "unspecified", preserving pre-migration behaviour.
    """
    for stmt in _ADD_ENTRY_RELATION_ATTRIBUTE_COLUMNS:
        conn.execute(stmt)
    logger.info("Migration 15: entry_relations weight/valid_at/invalid_at/metadata columns added")


# DuckDB's ALTER TABLE ADD COLUMN does not accept constraints (NOT NULL), so
# add a plain nullable VARCHAR with a default of '' — matching migration 3's
# ``created_by``/``last_modified_by`` pattern. The reader coalesces NULL to ''.
_ADD_FEED_SOURCE_MODE_COLUMN = (
    "ALTER TABLE feed_sources ADD COLUMN IF NOT EXISTS mode VARCHAR DEFAULT '';"
)


def add_feed_source_mode(conn: duckdb.DuckDBPyConnection, **kwargs: Any) -> None:
    """Migration 16: Add the ``mode`` column to ``feed_sources``.

    Selects which content-bearing surface a ``github`` source polls
    (``'releases'`` by default, ``'events'`` opt-in).  Empty string means
    "adapter default", preserving behaviour for ``rss`` sources and any rows
    created before the migration ran (#625).
    """
    conn.execute(_ADD_FEED_SOURCE_MODE_COLUMN)
    logger.info("Migration 16: feed_sources mode column added")


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
    9: add_expires_at,
    10: add_verification,
    11: add_session_id,
    12: add_feed_source_liveness,
    13: create_sync_jobs,
    14: add_feed_source_thresholds,
    15: add_relation_attributes,
    16: add_feed_source_mode,
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
        result = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'")
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
            raise RuntimeError(f"Migration {version} failed: {exc}") from exc

    new_version = pending[-1]
    logger.info("Schema migrated from version %d to %d", current, new_version)
    return new_version
