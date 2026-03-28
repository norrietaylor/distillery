"""Command-line interface for Distillery.

Provides the ``distillery`` entry point with the following subcommands:

- ``status``: Display database statistics (total entries, breakdown by type
  and status, database path, and configured embedding model).
- ``health``: Verify database connectivity and exit with code 0 on success
  or code 1 on failure.

Global options:
- ``--version``: Print the package version and exit.
- ``--config PATH``: Override the default configuration file path.
- ``--format {text,json}``: Choose output format.

The ``DISTILLERY_CONFIG`` environment variable is also respected when
``--config`` is not supplied (handled by :func:`~distillery.config.load_config`).
"""

from __future__ import annotations

import argparse
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

        return {
            "total_entries": total,
            "entries_by_type": entries_by_type,
            "entries_by_status": entries_by_status,
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
    }

    if fmt == "json":
        print(json.dumps(data, indent=2))
    else:
        print(f"database_path:    {data['database_path']}")
        print(f"embedding_model:  {data['embedding_model']}")
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
    else:  # pragma: no cover – argparse rejects unknown subcommands
        parser.error(f"Unknown command: {command}")