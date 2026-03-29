"""Command-line interface for Distillery.

Provides the ``distillery`` entry point with the following subcommands:

- ``status``: Display database statistics (total entries, breakdown by type
  and status, database path, and configured embedding model).
- ``health``: Verify database connectivity and exit with code 0 on success
  or code 1 on failure.
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

    gateway_parser = subparsers.add_parser(
        "gateway",
        help="Start the Distillery HTTP Gateway for the browser extension",
        parents=[shared],
    )
    gateway_parser.add_argument(
        "--gateway-config",
        metavar="PATH",
        default="gateway.yaml",
        help="Path to gateway.yaml (default: gateway.yaml)",
    )
    gateway_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override port from gateway.yaml",
    )
    gateway_parser.add_argument(
        "--host",
        default=None,
        help="Override host from gateway.yaml",
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
# Eval subcommand
# ---------------------------------------------------------------------------


def _cmd_eval(
    scenarios_dir: str | None,
    skill_filter: str | None,
    save_baseline: str | None,
    baseline: str | None,
    model: str,
    fmt: str,
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
            f"Error: eval dependencies not installed. "
            f"Run: pip install 'distillery[eval]'\n{exc}",
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

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    pass_rate = passed / total if total > 0 else 0.0

    if fmt == "json":
        output = []
        for r in results:
            output.append({
                "name": r.scenario_name,
                "skill": r.skill,
                "passed": r.passed,
                "latency_ms": round(r.performance.total_latency_ms, 1),
                "input_tokens": r.performance.input_tokens,
                "output_tokens": r.performance.output_tokens,
                "tool_call_count": r.performance.tool_call_count,
                "tools_called": r.effectiveness.tools_called,
                "failure_reasons": r.effectiveness.failure_reasons,
            })
        summary = {"results": output, "passed": passed, "total": total, "pass_rate": pass_rate}
        print(json.dumps(summary, indent=2))
    else:
        for r in results:
            print(r.summary())
        print(f"\n{'='*60}")
        print(f"Results: {passed}/{total} passed ({pass_rate:.0%})")

    # Save baseline if requested.
    if save_baseline:
        baseline_data = [
            {
                "name": r.scenario_name,
                "skill": r.skill,
                "passed": r.passed,
                "latency_ms": r.performance.total_latency_ms,
                "total_tokens": r.performance.total_tokens,
                "tool_call_count": r.performance.tool_call_count,
            }
            for r in results
        ]
        Path(save_baseline).write_text(json.dumps(baseline_data, indent=2), encoding="utf-8")
        print(f"Baseline saved to {save_baseline}")

    # Regression check if baseline provided.
    if baseline and Path(baseline).exists():
        baseline_data_loaded = json.loads(Path(baseline).read_text(encoding="utf-8"))
        baseline_by_name = {e["name"]: e for e in baseline_data_loaded}
        regressions = []
        for r in results:
            prev = baseline_by_name.get(r.scenario_name)
            if prev and prev["passed"] and not r.passed:
                regressions.append(f"  REGRESSION: {r.scenario_name} was passing, now failing")
        if regressions:
            print("\nRegressions detected:")
            print("\n".join(regressions))
            return 1

    return 0 if passed == total else 1


# ---------------------------------------------------------------------------
# Gateway command
# ---------------------------------------------------------------------------


def _cmd_gateway(
    gateway_config_path: str,
    port: int | None,
    host: str | None,
) -> int:
    """Start the Distillery HTTP Gateway."""
    try:
        import uvicorn
        from distillery.server.app import create_app
        from distillery.server.config import GatewayConfig
    except ImportError:
        print(
            "The gateway command requires additional dependencies.\n"
            "Install them with:  pip install 'distillery[server]'",
            file=sys.stderr,
        )
        return 1

    config_file = Path(gateway_config_path)
    if not config_file.exists():
        print(
            f"Gateway config not found: {config_file}\n"
            "Create a gateway.yaml file. See docs/specs/04-spec-hosted-service.md for format.",
            file=sys.stderr,
        )
        return 1

    try:
        gateway_config = GatewayConfig.load(config_file)
    except (ValueError, KeyError) as exc:
        print(f"Invalid gateway config: {exc}", file=sys.stderr)
        return 1

    app = create_app(gateway_config)
    uvicorn.run(
        app,
        host=host or gateway_config.host,
        port=port or gateway_config.port,
    )
    return 0


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
    elif command == "eval":
        sys.exit(
            _cmd_eval(
                scenarios_dir=getattr(args, "scenarios_dir", None),
                skill_filter=getattr(args, "skill", None),
                save_baseline=getattr(args, "save_baseline", None),
                baseline=getattr(args, "baseline", None),
                model=getattr(args, "model", "claude-haiku-4-5-20251001"),
                fmt=fmt,
            )
        )
    elif command == "gateway":
        sys.exit(
            _cmd_gateway(
                gateway_config_path=getattr(args, "gateway_config", "gateway.yaml"),
                port=getattr(args, "port", None),
                host=getattr(args, "host", None),
            )
        )
    else:  # pragma: no cover – argparse rejects unknown subcommands
        parser.error(f"Unknown command: {command}")
