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
    """
    Start the Distillery MCP server over stdio and run it until completion or interruption.

    Returns:
        Exit code: `0` on successful exit or interruption, `1` on unexpected error.
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
