"""Entry point for the Distillery MCP server.

Run with:
    python -m distillery.mcp

Or via the CLI entry point:
    distillery-mcp

The server communicates over stdio (default) or streamable-HTTP using the MCP
protocol and exposes Distillery storage operations as tools to any connected
MCP client (e.g. Claude Code).

Usage:
    distillery-mcp                          # stdio mode (default)
    distillery-mcp --transport stdio        # explicit stdio mode
    distillery-mcp --transport http         # HTTP mode, default host/port
    distillery-mcp --transport http --host 127.0.0.1 --port 9000

Exit codes:
    0   -- server exited cleanly
    1   -- startup or runtime error
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys


def _configure_logging() -> None:
    """Configure logging to stderr so it does not interfere with stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stderr,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:] when ``None``).

    Returns:
        Parsed :class:`argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        prog="distillery-mcp",
        description="Start the Distillery MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help=(
            "Transport protocol to use. 'stdio' (default) for local use; "
            "'http' for persistent streamable-HTTP endpoint."
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help=(
            "Bind address for HTTP transport (default: %(default)s). "
            "Falls back to DISTILLERY_HOST env var, then '0.0.0.0'."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Bind port for HTTP transport (default: %(default)s). "
            "Falls back to DISTILLERY_PORT env var, then 8000."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Start the Distillery MCP server and run it until completion or interruption.

    When ``--transport http`` is supplied the server binds as a persistent
    streamable-HTTP endpoint.  The default (or ``--transport stdio``) keeps
    the original stdio behaviour unchanged.

    Args:
        argv: Argument list forwarded to :func:`_parse_args`.  Defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Exit code: ``0`` on successful exit or interruption, ``1`` on error.
    """
    # Convert SIGTERM into KeyboardInterrupt so atexit handlers run.
    # Fly.io sends SIGTERM on scale-to-zero; without this, the DuckDB
    # atexit CHECKPOINT never fires and the WAL is left dirty on disk.
    def _sigterm_handler(signum: int, frame: object) -> None:  # pragma: no cover
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _sigterm_handler)

    _configure_logging()
    logger = logging.getLogger(__name__)

    args = _parse_args(argv)

    try:
        from distillery.config import load_config
        from distillery.mcp.server import create_server

        config = load_config()

        if args.transport == "http":
            host = (
                args.host
                if args.host is not None
                else os.environ.get("DISTILLERY_HOST", "0.0.0.0")
            )
            port_env = os.environ.get("DISTILLERY_PORT")
            port = args.port if args.port is not None else (int(port_env) if port_env else 8000)

            auth = None
            provider_name = config.server.auth.provider
            if provider_name == "github":
                from distillery.mcp.auth import (
                    _patch_cimd_localhost_redirect,
                    build_github_auth,
                )

                _patch_cimd_localhost_redirect()
                auth = build_github_auth(config)
            elif provider_name == "none":
                logger.warning(
                    "HTTP server running without authentication "
                    "(server.auth.provider is 'none')",
                )
            else:
                raise ValueError(
                    f"Unknown auth provider {provider_name!r} for HTTP transport. "
                    f"Supported values: 'github', 'none'."
                )

            server = create_server(config=config, auth=auth)
            server.run(
                transport="streamable-http",
                host=host,
                port=port,
                path="/mcp",
                stateless_http=True,
            )
        else:
            server = create_server(config=config)
            asyncio.run(server.run_stdio_async(show_banner=False))

        return 0
    except KeyboardInterrupt:
        logger.info("Distillery MCP server interrupted")
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("Distillery MCP server failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
