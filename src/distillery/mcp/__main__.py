"""Entry point for the Distillery MCP server.

Run with:
    python -m distillery.mcp

Or via the CLI entry point:
    distillery-mcp

The server communicates over stdio using the MCP protocol and exposes
Distillery storage operations as tools to any connected MCP client (e.g.
Claude Code).

Exit codes:
    0   -- server exited cleanly
    1   -- startup or runtime error
"""

from __future__ import annotations

import asyncio
import logging
import sys


def _configure_logging() -> None:
    """Configure logging to stderr so it does not interfere with stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stderr,
    )


def main() -> int:
    """CLI entry point for ``python -m distillery.mcp`` and ``distillery-mcp``.

    Returns:
        Exit code -- ``0`` on success, ``1`` on error.
    """
    _configure_logging()
    logger = logging.getLogger(__name__)

    try:
        from distillery.mcp.server import create_server

        server = create_server()
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
