"""CLI entry point for the Distillery store module.

Run with:
    python -m distillery.store --check

Supported commands
------------------
--check
    Connect to the configured DuckDB database, verify the connection, and
    print the total number of entries (including archived ones).

Exit codes:
    0   -- connection succeeded
    1   -- connection failed (error message written to stderr)
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m distillery.store",
        description="Distillery store health check CLI",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check the DuckDB connection and report entry count.",
    )
    parser.add_argument(
        "--db",
        default=None,
        metavar="PATH",
        help=(
            "Path to the DuckDB database file.  "
            "Defaults to the value from distillery.yaml (or ~/.distillery/distillery.db)."
        ),
    )
    return parser.parse_args(argv)


async def _run_check(db_path: str) -> int:
    """Open *db_path*, count entries, and print a status line.

    Returns 0 on success, 1 on failure.
    """
    # Import here so the module stays importable even without all deps.
    import duckdb  # type: ignore[import]

    try:
        conn = duckdb.connect(db_path)
        # Attempt to read the entries table; it may not exist yet.
        try:
            result = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
            count = result[0] if result else 0
            status = "ok"
        except duckdb.CatalogException:
            # Table does not exist yet -- database is empty / uninitialized.
            count = 0
            status = "ok (schema not yet initialised)"
        finally:
            conn.close()

        print(f"status: {status}")
        print(f"database: {db_path}")
        print(f"entries: {count}")
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _resolve_db_path(explicit_path: str | None) -> str:
    """Return the database path to use, preferring explicit over config."""
    if explicit_path is not None:
        return explicit_path

    # Try to load from config.
    try:
        from distillery.config import load_config  # type: ignore[import]

        cfg = load_config()
        raw = cfg.storage.database_path
        # Expand home directory if needed.
        import os

        return os.path.expanduser(raw)
    except Exception:  # noqa: BLE001
        import os

        return os.path.expanduser("~/.distillery/distillery.db")


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m distillery.store``."""
    args = _parse_args(argv)

    if not args.check:
        print("No action specified. Use --check to verify the connection.", file=sys.stderr)
        print("Usage: python -m distillery.store --check [--db PATH]", file=sys.stderr)
        return 1

    db_path = _resolve_db_path(args.db)
    return asyncio.run(_run_check(db_path))


if __name__ == "__main__":
    sys.exit(main())
