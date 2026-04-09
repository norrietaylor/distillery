"""Command-line interface for Distillery.

Provides the ``distillery`` entry point with the following subcommands:

- ``status``: Display database statistics (total entries, breakdown by type
  and status, database path, and configured embedding model).
- ``health``: Verify database connectivity and exit with code 0 on success
  or code 1 on failure.
- ``export``: Export all entries and feed sources to a JSON file.
- ``import``: Import entries and feed sources from a JSON export file.
- ``eval``: Run skill evaluation scenarios against Claude (requires
  ``ANTHROPIC_API_KEY`` and ``pip install 'distillery[eval]'``).

Global options:
- ``--version``: Print the package version and exit.
- ``--config PATH``: Override the default configuration file path.
- ``--format {text,json}``: Choose output format.

The ``DISTILLERY_CONFIG`` environment variable is also respected when
``--config`` is not supplied (handled by :func:`~distillery.config.load_config`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from distillery import __version__
from distillery.config import CONFIG_ENV_VAR, load_config


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser.

    ``--config`` and ``--format`` are defined on the top-level parser and
    inherited by each subcommand.  Subcommands define their own copies so
    that they appear in per-subcommand ``--help`` output; the parent
    values act as defaults when the subcommand does not override them.
    """
    # Shared options defined on a parent parser so they appear both at the
    # top level and inside each subcommand's --help.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help=(
            f"Path to configuration file (overrides {CONFIG_ENV_VAR} env var "
            "and the default distillery.yaml search)"
        ),
    )
    shared.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    parser = argparse.ArgumentParser(
        prog="distillery",
        description="Distillery knowledge-base CLI",
        parents=[shared],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"distillery {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "status",
        help="Display database statistics",
        parents=[shared],
    )

    subparsers.add_parser(
        "health",
        help="Verify database connectivity",
        parents=[shared],
    )

    poll_parser = subparsers.add_parser(
        "poll",
        help="Poll configured feed sources and store relevant items",
        parents=[shared],
    )
    poll_parser.add_argument(
        "--source",
        metavar="URL",
        default=None,
        help="Poll only the source with this URL (polls all sources when omitted)",
    )

    retag_parser = subparsers.add_parser(
        "retag",
        help="Backfill topic tags on existing feed entries",
        parents=[shared],
    )
    retag_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview which entries would be updated without writing changes",
    )
    retag_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Retag all feed entries, not just those with empty tags",
    )

    export_parser = subparsers.add_parser(
        "export",
        help="Export all entries and feed sources to a JSON file",
        parents=[shared],
    )
    export_parser.add_argument(
        "--output",
        metavar="PATH",
        required=True,
        help="Path to write the exported JSON file",
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Import entries and feed sources from a JSON export file",
        parents=[shared],
    )
    import_parser.add_argument(
        "--input",
        metavar="PATH",
        required=True,
        help="Path to the JSON export file to import",
    )
    import_parser.add_argument(
        "--mode",
        choices=["merge", "replace"],
        default="merge",
        help="Import mode: merge (skip existing IDs) or replace (delete all before import)",
    )
    import_parser.add_argument(
        "--yes",
        action="store_true",
        default=False,
        help="Skip confirmation prompt for replace mode",
    )

    eval_parser = subparsers.add_parser(
        "eval",
        help="Run skill evaluation scenarios against Claude",
        parents=[shared],
    )
    eval_parser.add_argument(
        "--skill",
        metavar="NAME",
        default=None,
        help="Run only scenarios for this skill (e.g. recall, distill)",
    )
    eval_parser.add_argument(
        "--scenarios-dir",
        metavar="PATH",
        default=None,
        help="Directory containing scenario YAML files (default: tests/eval/scenarios)",
    )
    eval_parser.add_argument(
        "--save-baseline",
        metavar="PATH",
        default=None,
        help="Save eval results as a JSON baseline for regression detection",
    )
    eval_parser.add_argument(
        "--baseline",
        metavar="PATH",
        default=None,
        help="Compare results against a previously saved baseline",
    )
    eval_parser.add_argument(
        "--model",
        metavar="MODEL",
        default="claude-haiku-4-5-20251001",
        help="Claude model to use for eval runs (default: claude-haiku-4-5-20251001)",
    )
    eval_parser.add_argument(
        "--compare-cost",
        action="store_true",
        default=False,
        help="Compare current run cost against baseline (requires --baseline)",
    )

    return parser


def _resolve_args(
    parser: argparse.ArgumentParser,
    argv: list[str] | None,
) -> argparse.Namespace:
    """Parse *argv* (or ``sys.argv[1:]``) and return the namespace."""
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Helpers for database introspection (no async needed for simple COUNT queries)
# ---------------------------------------------------------------------------


def _query_status(db_path: str) -> dict[str, Any]:
    """Open *db_path* in read-only mode and return summary statistics.

    Returns a dict with keys:
    - ``total_entries`` (int)
    - ``entries_by_type`` (dict[str, int])
    - ``entries_by_status`` (dict[str, int])
    - ``schema_version`` (str | None) — value from _meta, or None if unavailable
    - ``duckdb_version`` (str | None) — value from _meta, or None if unavailable

    Raises:
        RuntimeError: If the database cannot be opened or queried.
    """
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("duckdb is not installed") from exc

    try:
        read_only = db_path != ":memory:"
        conn = duckdb.connect(db_path, read_only=read_only)
    except Exception as exc:
        raise RuntimeError(f"Cannot open database at {db_path!r}: {exc}") from exc

    try:
        # Guard against databases that have not been initialised yet.
        table_check = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'entries'"
        ).fetchone()
        if table_check is None or table_check[0] == 0:
            return {
                "total_entries": 0,
                "entries_by_type": {},
                "entries_by_status": {},
                "schema_version": None,
                "duckdb_version": None,
            }

        total_row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
        total: int = total_row[0] if total_row is not None else 0

        type_rows = conn.execute(
            "SELECT entry_type, COUNT(*) FROM entries GROUP BY entry_type ORDER BY entry_type"
        ).fetchall()
        entries_by_type = {str(row[0]): int(row[1]) for row in type_rows}

        status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM entries GROUP BY status ORDER BY status"
        ).fetchall()
        entries_by_status = {str(row[0]): int(row[1]) for row in status_rows}

        # Read version info from _meta if the table exists.
        schema_version: str | None = None
        duckdb_version: str | None = None
        meta_check = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = '_meta'"
        ).fetchone()
        if meta_check is not None and meta_check[0] > 0:
            sv_row = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'").fetchone()
            schema_version = sv_row[0] if sv_row is not None else None
            dv_row = conn.execute("SELECT value FROM _meta WHERE key = 'duckdb_version'").fetchone()
            duckdb_version = dv_row[0] if dv_row is not None else None

        return {
            "total_entries": total,
            "entries_by_type": entries_by_type,
            "entries_by_status": entries_by_status,
            "schema_version": schema_version,
            "duckdb_version": duckdb_version,
        }
    finally:
        conn.close()


def _check_health(db_path: str) -> bool:
    """Return ``True`` if the database at *db_path* is reachable, ``False`` otherwise."""
    try:
        import duckdb
    except ImportError:  # pragma: no cover
        return False

    # ":memory:" is always healthy.
    if db_path == ":memory:":
        return True

    resolved = Path(db_path).expanduser()

    # If the database file does not exist yet, the path must at least be in a
    # writable directory so that DuckDB could create it.
    if not resolved.exists():
        return resolved.parent.exists()

    try:
        conn = duckdb.connect(str(resolved), read_only=True)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_status(config_path: str | None, fmt: str) -> int:
    """Implement the ``status`` subcommand.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    try:
        cfg = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading configuration: {exc}", file=sys.stderr)
        return 1

    db_path = str(Path(cfg.storage.database_path).expanduser())

    try:
        stats = _query_status(db_path)
    except RuntimeError as exc:
        print(f"Error querying database: {exc}", file=sys.stderr)
        return 1

    data: dict[str, Any] = {
        "database_path": db_path,
        "embedding_model": cfg.embedding.model,
        "total_entries": stats["total_entries"],
        "entries_by_type": stats["entries_by_type"],
        "entries_by_status": stats["entries_by_status"],
        "schema_version": stats["schema_version"],
        "duckdb_version": stats["duckdb_version"],
    }

    if fmt == "json":
        print(json.dumps(data, indent=2))
    else:
        print(f"database_path:    {data['database_path']}")
        print(f"embedding_model:  {data['embedding_model']}")
        if data["schema_version"] is not None:
            print(f"schema_version:   {data['schema_version']}")
        if data["duckdb_version"] is not None:
            print(f"duckdb_version:   {data['duckdb_version']}")
        print(f"total_entries:    {data['total_entries']}")
        print("entries_by_type:")
        if data["entries_by_type"]:
            for k, v in data["entries_by_type"].items():
                print(f"  {k}: {v}")
        else:
            print("  (none)")
        print("entries_by_status:")
        if data["entries_by_status"]:
            for k, v in data["entries_by_status"].items():
                print(f"  {k}: {v}")
        else:
            print("  (none)")

    return 0


def _cmd_health(config_path: str | None, fmt: str) -> int:
    """Implement the ``health`` subcommand.

    Returns:
        Exit code (0 on success, 1 on failure).
    """
    try:
        cfg = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading configuration: {exc}", file=sys.stderr)
        return 1

    db_path = str(Path(cfg.storage.database_path).expanduser())
    ok = _check_health(db_path)

    status_str = "OK" if ok else "FAIL"
    if fmt == "json":
        print(json.dumps({"status": status_str, "database_path": db_path}))
    else:
        print(f"status: {status_str}")
        print(f"database_path: {db_path}")

    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Poll subcommand
# ---------------------------------------------------------------------------


def _cmd_poll(config_path: str | None, fmt: str, source_url: str | None) -> int:
    """Implement the ``poll`` subcommand.

    Loads the configuration, initialises the store and embedding provider,
    runs the :class:`~distillery.feeds.poller.FeedPoller`, and prints a
    summary.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    try:
        cfg = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading configuration: {exc}", file=sys.stderr)
        return 1

    async def _run() -> Any:
        import contextlib

        from distillery.feeds.poller import FeedPoller
        from distillery.mcp.server import _create_embedding_provider, _normalize_db_path
        from distillery.store.duckdb import DuckDBStore

        embedding_provider = _create_embedding_provider(cfg)
        db_path = _normalize_db_path(cfg.storage.database_path)

        store = DuckDBStore(
            db_path=db_path,
            embedding_provider=embedding_provider,
            s3_region=cfg.storage.s3_region,
            s3_endpoint=cfg.storage.s3_endpoint,
            hybrid_search=cfg.defaults.hybrid_search,
            rrf_k=cfg.defaults.rrf_k,
            recency_window_days=cfg.defaults.recency_window_days,
            recency_min_weight=cfg.defaults.recency_min_weight,
        )
        await store.initialize()

        # Seed YAML sources into DB only when the table is empty (first run).
        if not await store.list_feed_sources():
            for source in cfg.feeds.sources:
                with contextlib.suppress(ValueError):
                    await store.add_feed_source(
                        url=source.url,
                        source_type=source.source_type,
                        label=source.label,
                        poll_interval_minutes=source.poll_interval_minutes,
                        trust_weight=source.trust_weight,
                    )

        # Check sources from DB.
        db_sources = await store.list_feed_sources()
        if source_url is not None:
            matching = [s for s in db_sources if s["url"] == source_url]
            if not matching:
                return f"not-found:{source_url}"
        elif not db_sources:
            return "no-sources"

        poller = FeedPoller(store=store, config=cfg)
        return await poller.poll(source_url=source_url)

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        print(f"Error during poll: {exc}", file=sys.stderr)
        return 1

    if result == "no-sources":
        msg = "No feed sources configured. Add sources via distillery_watch or distillery.yaml."
        if fmt == "json":
            print(json.dumps({"error": msg, "sources_polled": 0}))
        else:
            print(msg)
        return 0

    if isinstance(result, str) and result.startswith("not-found:"):
        not_found_url = result[len("not-found:") :]
        msg = f"No configured source found with url {not_found_url!r}."
        print(f"Error: {msg}", file=sys.stderr)
        return 1

    summary = result

    if fmt == "json":
        results_data = [
            {
                "source_url": r.source_url,
                "source_type": r.source_type,
                "items_fetched": r.items_fetched,
                "items_stored": r.items_stored,
                "items_skipped_dedup": r.items_skipped_dedup,
                "items_below_threshold": r.items_below_threshold,
                "errors": r.errors,
                "polled_at": r.polled_at.isoformat(),
            }
            for r in summary.results
        ]
        print(
            json.dumps(
                {
                    "sources_polled": summary.sources_polled,
                    "sources_errored": summary.sources_errored,
                    "total_fetched": summary.total_fetched,
                    "total_stored": summary.total_stored,
                    "total_skipped_dedup": summary.total_skipped_dedup,
                    "total_below_threshold": summary.total_below_threshold,
                    "results": results_data,
                    "started_at": summary.started_at.isoformat(),
                    "finished_at": summary.finished_at.isoformat(),
                },
                indent=2,
            )
        )
    else:
        print("Poll cycle complete:")
        print(f"  sources_polled:        {summary.sources_polled}")
        print(f"  sources_errored:       {summary.sources_errored}")
        print(f"  total_fetched:         {summary.total_fetched}")
        print(f"  total_stored:          {summary.total_stored}")
        print(f"  total_skipped_dedup:   {summary.total_skipped_dedup}")
        print(f"  total_below_threshold: {summary.total_below_threshold}")
        for r in summary.results:
            status = "ERROR" if r.errors else "OK"
            print(f"  [{status}] {r.source_url}: fetched={r.items_fetched} stored={r.items_stored}")
            for err in r.errors:
                print(f"    error: {err}", file=sys.stderr)

    return 0 if summary.sources_errored == 0 else 1


# ---------------------------------------------------------------------------
# Retag subcommand
# ---------------------------------------------------------------------------

_RETAG_BATCH_SIZE = 100


def _cmd_retag(
    config_path: str | None,
    fmt: str,
    dry_run: bool,
    force: bool,
) -> int:
    """Implement the ``retag`` subcommand.

    Backfills topic tags on existing feed entries by running
    :func:`~distillery.feeds.poller.derive_all_tags` against the current tag
    vocabulary.

    Args:
        config_path: Path to configuration file, or ``None`` to use defaults.
        fmt: Output format (``"text"`` or ``"json"``).
        dry_run: When ``True``, report counts without persisting changes.
        force: When ``True``, retag *all* feed entries regardless of whether
            they already have tags.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    try:
        cfg = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading configuration: {exc}", file=sys.stderr)
        return 1

    async def _run() -> tuple[int, int]:
        """Return (total_scanned, total_updated)."""
        from distillery.feeds.models import FeedItem
        from distillery.feeds.poller import build_keyword_map, derive_all_tags
        from distillery.mcp.server import _create_embedding_provider, _normalize_db_path
        from distillery.models import EntryType
        from distillery.store.duckdb import DuckDBStore

        embedding_provider = _create_embedding_provider(cfg)
        db_path = _normalize_db_path(cfg.storage.database_path)

        store = DuckDBStore(
            db_path=db_path,
            embedding_provider=embedding_provider,
            s3_region=cfg.storage.s3_region,
            s3_endpoint=cfg.storage.s3_endpoint,
            hybrid_search=cfg.defaults.hybrid_search,
            rrf_k=cfg.defaults.rrf_k,
            recency_window_days=cfg.defaults.recency_window_days,
            recency_min_weight=cfg.defaults.recency_min_weight,
        )
        await store.initialize()

        # Build keyword map once for the entire backfill cycle.
        vocabulary = await store.get_tag_vocabulary()
        keyword_map = build_keyword_map(vocabulary)

        total_scanned = 0
        total_updated = 0
        offset = 0

        while True:
            batch = await store.list_entries(
                filters={"entry_type": EntryType.FEED.value},
                limit=_RETAG_BATCH_SIZE,
                offset=offset,
            )
            if not batch:
                break

            for entry in batch:
                total_scanned += 1

                # Skip already-tagged entries unless --force.
                if not force and entry.tags:
                    continue

                # Reconstruct a minimal FeedItem from entry metadata for tag derivation.
                meta = entry.metadata or {}
                source_type: str = meta.get("source_type", "rss")
                item = FeedItem(
                    source_url=meta.get("source_url", ""),
                    source_type=source_type,
                    item_id=entry.id,
                    title=meta.get("title") or None,
                    url=meta.get("url") or None,
                    content=entry.content or None,
                    published_at=entry.created_at,
                    extra=meta,
                )
                new_tags = derive_all_tags(item, source_type, keyword_map)

                if set(new_tags) != set(entry.tags):
                    if not dry_run:
                        await store.update(entry.id, {"tags": new_tags})
                    total_updated += 1

            offset += len(batch)
            if len(batch) < _RETAG_BATCH_SIZE:
                break

        await store.close()
        return total_scanned, total_updated

    try:
        total_scanned, total_updated = asyncio.run(_run())
    except Exception as exc:
        print(f"Error during retag: {exc}", file=sys.stderr)
        return 1

    action = "would update" if dry_run else "updated"
    if fmt == "json":
        print(
            json.dumps(
                {
                    "dry_run": dry_run,
                    "force": force,
                    "total_scanned": total_scanned,
                    "total_updated": total_updated,
                }
            )
        )
    else:
        print(f"Retag complete (dry_run={dry_run}, force={force}):")
        print(f"  total_scanned: {total_scanned}")
        print(f"  total_{action.replace(' ', '_')}: {total_updated}")

    return 0


# ---------------------------------------------------------------------------
# Export subcommand
# ---------------------------------------------------------------------------


def _cmd_export(config_path: str | None, fmt: str, output_path: str) -> int:
    """Implement the ``export`` subcommand.

    Queries all entries, feed sources, and _meta from the database and writes
    a portable JSON snapshot to *output_path*.  Embeddings are omitted so the
    file can be safely imported on any instance.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    import datetime

    try:
        cfg = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading configuration: {exc}", file=sys.stderr)
        return 1

    def _run_export() -> Any:
        import duckdb as _duckdb

        from distillery.mcp.server import _normalize_db_path

        db_path = _normalize_db_path(cfg.storage.database_path)

        # Open read-only to avoid running migrations or modifying _meta.
        if db_path == ":memory:":
            raise RuntimeError("Cannot export from an in-memory database")
        resolved = Path(db_path).expanduser()
        if not resolved.exists():
            raise RuntimeError(f"Database file not found: {db_path}")

        conn = _duckdb.connect(str(resolved), read_only=True)
        try:
            # Verify the entries table exists.
            table_check = conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'entries'"
            ).fetchone()
            if table_check is None or table_check[0] == 0:
                return [], [], {}

            # Query entries (no embedding column).
            entry_rows = conn.execute(
                "SELECT id, content, entry_type, source, status, tags, metadata, "
                "version, project, author, created_at, updated_at, created_by, "
                "last_modified_by, expires_at FROM entries"
            ).fetchall()
            entry_cols = [
                "id",
                "content",
                "entry_type",
                "source",
                "status",
                "tags",
                "metadata",
                "version",
                "project",
                "author",
                "created_at",
                "updated_at",
                "created_by",
                "last_modified_by",
                "expires_at",
            ]
            entries: list[dict[str, Any]] = []
            for row in entry_rows:
                entry: dict[str, Any] = {}
                for col, val in zip(entry_cols, row, strict=True):
                    if hasattr(val, "isoformat"):
                        entry[col] = val.isoformat()
                    elif col == "metadata" and isinstance(val, str):
                        entry[col] = json.loads(val) if val else {}
                    else:
                        entry[col] = val
                entries.append(entry)

            # Query feed_sources.
            feed_rows = conn.execute("SELECT * FROM feed_sources").fetchall()
            feed_cols = [desc[0] for desc in conn.description]
            feed_sources: list[dict[str, Any]] = []
            for row in feed_rows:
                fsrc: dict[str, Any] = {}
                for col, val in zip(feed_cols, row, strict=True):
                    if hasattr(val, "isoformat"):
                        fsrc[col] = val.isoformat()
                    else:
                        fsrc[col] = val
                feed_sources.append(fsrc)

            # Query _meta.
            meta_rows = conn.execute("SELECT key, value FROM _meta").fetchall()
            meta: dict[str, str] = {str(row[0]): str(row[1]) for row in meta_rows}

            return entries, feed_sources, meta
        finally:
            conn.close()

    try:
        entries, feed_sources, meta = _run_export()
    except Exception as exc:
        print(f"Error during export: {exc}", file=sys.stderr)
        return 1

    exported_at = datetime.datetime.now(datetime.UTC).isoformat()
    payload: dict[str, Any] = {
        "version": 1,
        "exported_at": exported_at,
        "meta": meta,
        "entries": entries,
        "feed_sources": feed_sources,
    }

    try:
        out = Path(output_path)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"Error writing export file: {exc}", file=sys.stderr)
        return 1

    n_entries = len(entries)
    n_sources = len(feed_sources)
    print(f"Exported {n_entries} entries and {n_sources} feed sources to {output_path}")
    return 0


# ---------------------------------------------------------------------------
# Import subcommand
# ---------------------------------------------------------------------------

_IMPORT_BATCH_SIZE = 50


def _cmd_import(
    config_path: str | None,
    fmt: str,
    input_path: str,
    mode: str,
    yes: bool,
) -> int:
    """Implement the ``import`` subcommand.

    Reads a JSON export file produced by ``distillery export`` and inserts the
    entries and feed sources into the database.  In *merge* mode existing IDs
    are skipped; in *replace* mode all existing entries are deleted first.

    Returns:
        Exit code (0 on success, 1 on error).
    """
    # --- 1. Load and validate JSON structure ---
    try:
        raw_text = Path(input_path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error reading import file: {exc}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"Error parsing import file (invalid JSON): {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("Error: import file must be a JSON object", file=sys.stderr)
        return 1

    missing = [k for k in ("version", "entries", "feed_sources") if k not in payload]
    if missing:
        print(
            f"Error: import file is missing required keys: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    # Validate export format version.
    supported_versions = {1}
    export_version = payload.get("version")
    if export_version not in supported_versions:
        print(
            f"Error: unsupported export format version {export_version!r} "
            f"(supported: {sorted(supported_versions)})",
            file=sys.stderr,
        )
        return 1

    entries_data = payload["entries"]
    feed_sources_data = payload["feed_sources"]
    if not isinstance(entries_data, list) or not isinstance(feed_sources_data, list):
        print(
            "Error: 'entries' and 'feed_sources' must be JSON arrays",
            file=sys.stderr,
        )
        return 1

    # --- 2. Replace-mode confirmation ---
    if mode == "replace" and not yes:
        try:
            answer = input("This will delete all existing entries. Continue? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Import cancelled.", file=sys.stderr)
            return 1

    # --- 3. Load config ---
    try:
        cfg = load_config(config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading configuration: {exc}", file=sys.stderr)
        return 1

    async def _run() -> tuple[int, int, int, int]:
        """Return (imported, skipped, reembedded, sources_imported)."""
        import contextlib
        import datetime

        from distillery.mcp.server import _create_embedding_provider, _normalize_db_path
        from distillery.models import Entry, EntrySource, EntryStatus, EntryType
        from distillery.store.duckdb import DuckDBStore

        embedding_provider = _create_embedding_provider(cfg)
        db_path = _normalize_db_path(cfg.storage.database_path)

        store = DuckDBStore(
            db_path=db_path,
            embedding_provider=embedding_provider,
            s3_region=cfg.storage.s3_region,
            s3_endpoint=cfg.storage.s3_endpoint,
            hybrid_search=cfg.defaults.hybrid_search,
            rrf_k=cfg.defaults.rrf_k,
            recency_window_days=cfg.defaults.recency_window_days,
            recency_min_weight=cfg.defaults.recency_min_weight,
        )
        await store.initialize()

        conn = store._conn
        assert conn is not None

        # --- 4. Collect entries for insertion (pre-embedding) ---
        imported = 0
        skipped = 0
        reembedded = 0

        to_insert: list[dict[str, Any]] = []
        for raw in entries_data:
            entry_id: str = raw.get("id", "")
            if mode == "merge" and entry_id:
                existing_row = conn.execute(
                    "SELECT id FROM entries WHERE id = ?", [entry_id]
                ).fetchone()
                if existing_row is not None:
                    skipped += 1
                    continue
            to_insert.append(raw)

        # --- 5. Pre-compute all embeddings before any destructive changes ---
        def _parse_dt(val: Any) -> datetime.datetime:
            if isinstance(val, datetime.datetime):
                if val.tzinfo is None:
                    return val.replace(tzinfo=datetime.UTC)
                return val
            parsed = datetime.datetime.fromisoformat(str(val))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=datetime.UTC)
            return parsed

        staged_rows: list[tuple[Entry, list[float]]] = []
        for batch_start in range(0, len(to_insert), _IMPORT_BATCH_SIZE):
            batch = to_insert[batch_start : batch_start + _IMPORT_BATCH_SIZE]
            contents = [b.get("content", "") for b in batch]
            embeddings = await asyncio.to_thread(embedding_provider.embed_batch, contents)
            reembedded += len(batch)

            for raw, embedding in zip(batch, embeddings, strict=True):
                entry = Entry(
                    id=raw.get("id", ""),
                    content=raw.get("content", ""),
                    entry_type=EntryType(raw.get("entry_type", "inbox")),
                    source=EntrySource(raw.get("source", "import")),
                    author=raw.get("author", ""),
                    project=raw.get("project"),
                    tags=list(raw.get("tags") or []),
                    status=EntryStatus(raw.get("status", "active")),
                    metadata=dict(raw.get("metadata") or {}),
                    version=int(raw.get("version", 1)),
                    created_at=_parse_dt(
                        raw.get("created_at", datetime.datetime.now(datetime.UTC).isoformat())
                    ),
                    updated_at=_parse_dt(
                        raw.get("updated_at", datetime.datetime.now(datetime.UTC).isoformat())
                    ),
                    created_by=raw.get("created_by", ""),
                    last_modified_by=raw.get("last_modified_by", ""),
                    expires_at=(
                        _parse_dt(raw["expires_at"]) if raw.get("expires_at") is not None else None
                    ),
                )
                staged_rows.append((entry, embedding))

            print(
                f"  Progress: {min(batch_start + _IMPORT_BATCH_SIZE, len(to_insert))}"
                f"/{len(to_insert)} entries embedded...",
                file=sys.stderr,
            )

        # --- 6. Atomic replace: delete + insert inside a transaction ---
        try:
            conn.execute("BEGIN TRANSACTION")

            if mode == "replace":
                conn.execute("DELETE FROM entries")
                conn.execute("DELETE FROM feed_sources")

            for entry, embedding in staged_rows:
                conn.execute(
                    "INSERT INTO entries "
                    "(id, content, entry_type, source, author, project, tags, status, "
                    " metadata, created_at, updated_at, version, embedding, "
                    " created_by, last_modified_by, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
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
                        entry.created_by,
                        entry.last_modified_by,
                        entry.expires_at,
                    ],
                )
                imported += 1

            conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise

        # --- 7. Import feed sources ---
        sources_imported = 0
        for fsrc in feed_sources_data:
            with contextlib.suppress(ValueError):
                await store.add_feed_source(
                    url=fsrc.get("url", ""),
                    source_type=fsrc.get("source_type", "rss"),
                    label=fsrc.get("label", ""),
                    poll_interval_minutes=int(fsrc.get("poll_interval_minutes", 60)),
                    trust_weight=float(fsrc.get("trust_weight", 1.0)),
                )
                sources_imported += 1

        await store.close()
        return imported, skipped, reembedded, sources_imported

    try:
        imported, skipped, reembedded, sources_imported = asyncio.run(_run())
    except Exception as exc:
        print(f"Error during import: {exc}", file=sys.stderr)
        return 1

    print(
        f"Imported {imported} entries ({skipped} skipped, {reembedded} re-embedded)"
        f" and {sources_imported} feed sources"
    )
    return 0


# ---------------------------------------------------------------------------
# Retrieval metrics helpers
# ---------------------------------------------------------------------------

#: MRR threshold — scenarios below this value are marked failed.
_MRR_THRESHOLD: float = 0.7
#: Precision@5 threshold — scenarios below this value are marked failed.
_PRECISION_THRESHOLD: float = 0.6
#: Number of top results to consider for precision/recall.
_RETRIEVAL_K: int = 5


def _load_golden_retrieval_labels(
    golden_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Load golden retrieval labels from *golden_dir*/retrieval.yaml.

    Returns a mapping of scenario name → list of golden label dicts with
    ``"entry_id"`` (a content fingerprint) and ``"relevant"`` (bool).

    The content fingerprint is the first 100 characters of each seed entry's
    content, used to match against tool call response content fields since
    actual UUIDs are not predictable at golden-data authoring time.

    Returns an empty dict when the golden file is not found or cannot be parsed.
    """
    golden_path = golden_dir / "retrieval.yaml"
    if not golden_path.exists():
        return {}

    try:
        import yaml
    except ImportError:
        return {}

    try:
        raw: Any = yaml.safe_load(golden_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(raw, dict) or "scenarios" not in raw:
        return {}

    labels_by_name: dict[str, list[dict[str, Any]]] = {}
    for scenario_data in raw.get("scenarios", []):
        if not isinstance(scenario_data, dict):
            continue
        name: str = scenario_data.get("name", "")
        if not name:
            continue
        seed_entries: list[Any] = scenario_data.get("seed_entries", [])
        judgments: list[Any] = scenario_data.get("relevance_judgments", [])

        golden_labels: list[dict[str, Any]] = []
        for judgment in judgments:
            if not isinstance(judgment, dict):
                continue
            idx = judgment.get("entry_index")
            relevant = judgment.get("relevant", False)
            if not isinstance(idx, int) or idx >= len(seed_entries):
                continue
            entry = seed_entries[idx]
            if not isinstance(entry, dict):
                continue
            content: str = str(entry.get("content", ""))
            # Use a 100-char content fingerprint as the entry_id for matching.
            fingerprint = content[:100]
            golden_labels.append({"entry_id": fingerprint, "relevant": relevant})

        labels_by_name[name] = golden_labels

    return labels_by_name


def _build_retrieval_tool_calls(
    result: Any,
) -> list[Any]:
    """Return ToolCallRecord copies with ``id`` replaced by a content fingerprint.

    The ``distillery_search`` response contains a ``results`` list where each
    item has both an ``id`` (UUID) and a ``content`` field.  This function
    rebuilds the response so ``id = content[:100]``, enabling comparison
    against content-fingerprint golden labels produced by
    :func:`_load_golden_retrieval_labels`.
    """
    from distillery.eval.models import ToolCallRecord

    translated: list[ToolCallRecord] = []
    for tc in result.tool_calls:
        if tc.tool_name != "distillery_search":
            translated.append(tc)
            continue

        raw_results: Any = tc.response.get("results", [])
        new_results: list[dict[str, Any]] = []
        if isinstance(raw_results, list):
            for item in raw_results:
                if isinstance(item, dict):
                    content_fp = str(item.get("content", ""))[:100]
                    new_item = dict(item)
                    new_item["id"] = content_fp
                    new_results.append(new_item)

        new_response = dict(tc.response)
        new_response["results"] = new_results
        translated.append(
            ToolCallRecord(
                tool_name=tc.tool_name,
                arguments=tc.arguments,
                response=new_response,
                latency_ms=tc.latency_ms,
                error=tc.error,
            )
        )
    return translated


def _apply_retrieval_scoring(
    results: list[Any],
    golden_labels_by_name: dict[str, list[dict[str, Any]]],
) -> None:
    """Compute retrieval metrics for results that have golden labels.

    Mutates each :class:`~distillery.eval.models.ScenarioResult` in *results*:

    - Sets ``retrieval_metrics`` to a :class:`~distillery.eval.retrieval_scorer.RetrievalMetrics`
      instance when golden labels are available for the scenario.
    - Appends to ``effectiveness.failure_reasons`` and sets ``passed = False``
      when MRR < :data:`_MRR_THRESHOLD` or precision@5 < :data:`_PRECISION_THRESHOLD`.
    """
    try:
        from distillery.eval.retrieval_scorer import score_retrieval
    except ImportError:
        return

    for result in results:
        golden_labels = golden_labels_by_name.get(result.scenario_name)
        if not golden_labels:
            continue

        translated_calls = _build_retrieval_tool_calls(result)
        metrics = score_retrieval(
            results=translated_calls,
            golden_labels=golden_labels,
            k=_RETRIEVAL_K,
        )
        result.retrieval_metrics = metrics

        # Enforce thresholds — only when the metric could actually be computed.
        if metrics.mrr is not None and metrics.mrr < _MRR_THRESHOLD:
            result.effectiveness.failure_reasons.append(
                f"MRR {metrics.mrr:.3f} below threshold {_MRR_THRESHOLD}"
            )
            result.passed = False

        if metrics.precision is not None and metrics.precision < _PRECISION_THRESHOLD:
            result.effectiveness.failure_reasons.append(
                f"precision@{_RETRIEVAL_K} {metrics.precision:.3f} below threshold {_PRECISION_THRESHOLD}"
            )
            result.passed = False


def _format_retrieval_metrics_text(result: Any) -> str | None:
    """Return a retrieval metrics line for text output, or ``None`` if unavailable."""
    m = result.retrieval_metrics
    if m is None:
        return None
    parts: list[str] = []
    if m.mrr is not None:
        parts.append(f"MRR={m.mrr:.3f}")
    if m.precision is not None:
        parts.append(f"P@{_RETRIEVAL_K}={m.precision:.3f}")
    if m.recall is not None:
        parts.append(f"R@{_RETRIEVAL_K}={m.recall:.3f}")
    if m.faithfulness is not None:
        parts.append(f"faith={m.faithfulness:.3f}")
    if not parts:
        return None
    return "  retrieval: " + "  ".join(parts)


# ---------------------------------------------------------------------------
# Eval subcommand
# ---------------------------------------------------------------------------


def _cmd_eval(
    scenarios_dir: str | None,
    skill_filter: str | None,
    save_baseline: str | None,
    baseline: str | None,
    model: str,
    fmt: str,
    compare_cost: bool = False,
) -> int:
    """Implement the ``eval`` subcommand.

    Loads scenario YAML files, drives Claude against an in-process MCP
    bridge, and reports pass/fail per scenario with performance metrics.

    Returns:
        Exit code — 0 if all scenarios pass, 1 if any fail or on error.
    """
    try:
        from distillery.eval.runner import ClaudeEvalRunner
        from distillery.eval.scenarios import load_scenarios_from_dir
    except ImportError as exc:
        print(
            f"Error: eval dependencies not installed. Run: pip install 'distillery[eval]'\n{exc}",
            file=sys.stderr,
        )
        return 1

    # Resolve scenarios directory.
    if scenarios_dir is None:
        default_dir = Path(__file__).parents[2] / "tests" / "eval" / "scenarios"
        resolved_dir = default_dir if default_dir.exists() else Path("tests/eval/scenarios")
    else:
        resolved_dir = Path(scenarios_dir)

    if not resolved_dir.exists():
        print(f"Error: scenarios directory not found: {resolved_dir}", file=sys.stderr)
        return 1

    scenarios = load_scenarios_from_dir(resolved_dir)
    if skill_filter:
        scenarios = [s for s in scenarios if s.skill == skill_filter]

    if not scenarios:
        print(f"No scenarios found (skill filter: {skill_filter!r})", file=sys.stderr)
        return 1

    # Override model on all scenarios.
    for s in scenarios:
        s.model = model

    try:
        runner = ClaudeEvalRunner()
    except (ImportError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    async def _run_all() -> list[Any]:
        results = []
        for scenario in scenarios:
            result = await runner.run(scenario)
            results.append(result)
        return results

    results = asyncio.run(_run_all())

    # Load golden retrieval labels and apply retrieval scoring/thresholds.
    golden_dir = Path(__file__).parents[2] / "tests" / "eval" / "golden"
    golden_labels_by_name = _load_golden_retrieval_labels(golden_dir)
    _apply_retrieval_scoring(results, golden_labels_by_name)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    pass_rate = passed / total if total > 0 else 0.0

    def _retrieval_metrics_dict(result: Any) -> dict[str, Any] | None:
        m = result.retrieval_metrics
        if m is None:
            return None
        return {
            "mrr": round(m.mrr, 4) if m.mrr is not None else None,
            "precision_at_k": round(m.precision, 4) if m.precision is not None else None,
            "recall_at_k": round(m.recall, 4) if m.recall is not None else None,
            "faithfulness": round(m.faithfulness, 4) if m.faithfulness is not None else None,
            "k": _RETRIEVAL_K,
        }

    json_output: list[dict[str, Any]] = []
    for r in results:
        entry: dict[str, Any] = {
            "name": r.scenario_name,
            "skill": r.skill,
            "passed": r.passed,
            "latency_ms": round(r.performance.total_latency_ms, 1),
            "input_tokens": r.performance.input_tokens,
            "output_tokens": r.performance.output_tokens,
            "tool_call_count": r.performance.tool_call_count,
            "tools_called": r.effectiveness.tools_called,
            "failure_reasons": r.effectiveness.failure_reasons,
        }
        rm = _retrieval_metrics_dict(r)
        if rm is not None:
            entry["retrieval_metrics"] = rm
        json_output.append(entry)

    summary: dict[str, Any] = {
        "results": json_output,
        "passed": passed,
        "total": total,
        "pass_rate": pass_rate,
    }

    if fmt == "json":
        # Defer printing when compare_cost is active so we can append cost_comparison.
        if not compare_cost:
            print(json.dumps(summary, indent=2))
    else:
        for r in results:
            print(r.summary())
            retrieval_line = _format_retrieval_metrics_text(r)
            if retrieval_line is not None:
                print(retrieval_line)
        print(f"\n{'=' * 60}")
        print(f"Results: {passed}/{total} passed ({pass_rate:.0%})")

    # Save baseline if requested.
    if save_baseline:
        baseline_scenarios = [
            {
                "name": r.scenario_name,
                "skill": r.skill,
                "passed": r.passed,
                "latency_ms": r.performance.total_latency_ms,
                "total_tokens": r.performance.total_tokens,
                "input_tokens": r.performance.input_tokens,
                "output_tokens": r.performance.output_tokens,
                "total_cost_usd": r.performance.total_cost_usd,
                "tool_call_count": r.performance.tool_call_count,
            }
            for r in results
        ]
        per_skill: dict[str, dict[str, float | int]] = {}
        for r in results:
            skill_key = r.skill
            if skill_key not in per_skill:
                per_skill[skill_key] = {"cost_usd": 0.0, "tokens": 0, "scenario_count": 0}
            per_skill[skill_key]["cost_usd"] = (
                float(per_skill[skill_key]["cost_usd"]) + r.performance.total_cost_usd
            )
            per_skill[skill_key]["tokens"] = (
                int(per_skill[skill_key]["tokens"]) + r.performance.total_tokens
            )
            per_skill[skill_key]["scenario_count"] = int(per_skill[skill_key]["scenario_count"]) + 1
        cost_summary = {
            "total_cost_usd": sum(r.performance.total_cost_usd for r in results),
            "total_tokens": sum(r.performance.total_tokens for r in results),
            "per_skill": per_skill,
        }
        baseline_output = {"scenarios": baseline_scenarios, "cost_summary": cost_summary}
        Path(save_baseline).write_text(json.dumps(baseline_output, indent=2), encoding="utf-8")
        print(f"Baseline saved to {save_baseline}")

    # Regression check if baseline provided.
    if baseline and Path(baseline).exists():
        baseline_data_loaded = json.loads(Path(baseline).read_text(encoding="utf-8"))
        # Support both old format (flat list) and new format (dict with "scenarios" key).
        if isinstance(baseline_data_loaded, list):
            loaded_scenarios = baseline_data_loaded
        else:
            loaded_scenarios = baseline_data_loaded.get("scenarios", [])
        baseline_by_name = {e["name"]: e for e in loaded_scenarios}
        regressions = []
        for r in results:
            prev = baseline_by_name.get(r.scenario_name)
            if prev and prev["passed"] and not r.passed:
                regressions.append(f"  REGRESSION: {r.scenario_name} was passing, now failing")
        if regressions:
            print("\nRegressions detected:")
            print("\n".join(regressions))
            return 1

        # Cost comparison if requested.
        if compare_cost:
            baseline_cost_summary = (
                baseline_data_loaded.get("cost_summary")
                if isinstance(baseline_data_loaded, dict)
                else None
            )
            current_total_cost = sum(r.performance.total_cost_usd for r in results)
            current_per_skill: dict[str, float] = {}
            for r in results:
                current_per_skill[r.skill] = (
                    current_per_skill.get(r.skill, 0.0) + r.performance.total_cost_usd
                )

            if baseline_cost_summary is None:
                if fmt == "json":
                    summary["cost_comparison"] = {"note": "no cost baseline available"}
                    print(json.dumps(summary, indent=2))
                else:
                    print("\nCost comparison: no cost baseline available")
            else:
                baseline_total = float(baseline_cost_summary.get("total_cost_usd", 0.0))
                total_delta = current_total_cost - baseline_total
                total_pct = (total_delta / baseline_total * 100) if baseline_total > 0 else 0.0

                baseline_per_skill: dict[str, Any] = baseline_cost_summary.get("per_skill", {})
                per_skill_deltas: dict[str, dict[str, float]] = {}
                cost_warnings: list[str] = []
                for skill, current_skill_cost in current_per_skill.items():
                    prev_skill_data = baseline_per_skill.get(skill)
                    prev_skill_cost = (
                        float(prev_skill_data.get("cost_usd", 0.0))
                        if isinstance(prev_skill_data, dict)
                        else 0.0
                    )
                    skill_delta = current_skill_cost - prev_skill_cost
                    skill_pct = (
                        (skill_delta / prev_skill_cost * 100) if prev_skill_cost > 0 else 0.0
                    )
                    per_skill_deltas[skill] = {
                        "current_usd": round(current_skill_cost, 6),
                        "baseline_usd": round(prev_skill_cost, 6),
                        "delta_usd": round(skill_delta, 6),
                        "delta_pct": round(skill_pct, 1),
                    }
                    if skill_pct > 20.0:
                        cost_warnings.append(
                            f"  WARNING: {skill} cost increased by {skill_pct:.1f}%"
                            f" (${prev_skill_cost:.6f} -> ${current_skill_cost:.6f})"
                        )

                if fmt == "json":
                    summary["cost_comparison"] = {
                        "current_total_usd": round(current_total_cost, 6),
                        "baseline_total_usd": round(baseline_total, 6),
                        "total_delta_usd": round(total_delta, 6),
                        "total_delta_pct": round(total_pct, 1),
                        "per_skill": per_skill_deltas,
                        "warnings": cost_warnings,
                    }
                    print(json.dumps(summary, indent=2))
                else:
                    print(f"\n{'=' * 60}")
                    print("Cost Comparison:")
                    print(
                        f"  Total: ${current_total_cost:.6f}"
                        f" (baseline: ${baseline_total:.6f},"
                        f" delta: {total_delta:+.6f} / {total_pct:+.1f}%)"
                    )
                    for skill, deltas in per_skill_deltas.items():
                        print(
                            f"  {skill}: ${deltas['current_usd']:.6f}"
                            f" (delta: {deltas['delta_usd']:+.6f} / {deltas['delta_pct']:+.1f}%)"
                        )
                    if cost_warnings:
                        print("\nCost warnings:")
                        print("\n".join(cost_warnings))

    # Ensure deferred JSON output is always printed when compare_cost was active.
    if fmt == "json" and compare_cost and "cost_comparison" not in summary:
        summary["cost_comparison"] = {"note": "no baseline provided for cost comparison"}
        print(json.dumps(summary, indent=2))

    return 0 if passed == total else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]`` when ``None``).
    """
    parser = _build_parser()
    args = _resolve_args(parser, argv)

    config_path: str | None = args.config
    fmt: str = args.format if args.format is not None else "text"
    command: str | None = args.command

    if command is None:
        parser.print_help()
        sys.exit(0)
    elif command == "status":
        sys.exit(_cmd_status(config_path, fmt))
    elif command == "health":
        sys.exit(_cmd_health(config_path, fmt))
    elif command == "poll":
        sys.exit(
            _cmd_poll(
                config_path=config_path,
                fmt=fmt,
                source_url=getattr(args, "source", None),
            )
        )
    elif command == "export":
        sys.exit(
            _cmd_export(
                config_path=config_path,
                fmt=fmt,
                output_path=args.output,
            )
        )
    elif command == "import":
        sys.exit(
            _cmd_import(
                config_path=config_path,
                fmt=fmt,
                input_path=args.input,
                mode=args.mode,
                yes=args.yes,
            )
        )
    elif command == "retag":
        sys.exit(
            _cmd_retag(
                config_path=config_path,
                fmt=fmt,
                dry_run=getattr(args, "dry_run", False),
                force=getattr(args, "force", False),
            )
        )
    elif command == "eval":
        sys.exit(
            _cmd_eval(
                scenarios_dir=getattr(args, "scenarios_dir", None),
                skill_filter=getattr(args, "skill", None),
                save_baseline=getattr(args, "save_baseline", None),
                baseline=getattr(args, "baseline", None),
                model=getattr(args, "model", "claude-haiku-4-5-20251001"),
                fmt=fmt,
                compare_cost=getattr(args, "compare_cost", False),
            )
        )
    else:  # pragma: no cover – argparse rejects unknown subcommands
        parser.error(f"Unknown command: {command}")
