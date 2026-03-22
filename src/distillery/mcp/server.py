"""MCP server implementation for Distillery.

Exposes storage operations as MCP tools using the stdio transport.
On startup, initializes DuckDBStore and EmbeddingProvider from distillery.yaml config.

Tools implemented here (T04.1):
  - distillery_status: Returns DB stats (total entries, by type, by status,
    database size, embedding model in use).

Additional tools are added in T04.2 (store, get, update) and T04.3 (search,
find_similar, list).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from distillery.config import load_config, DistilleryConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error response helpers
# ---------------------------------------------------------------------------


def error_response(code: str, message: str, details: dict | None = None) -> list[types.TextContent]:
    """Build a structured error response as MCP content.

    Args:
        code: Short machine-readable error code (e.g. ``"NOT_FOUND"``).
        message: Human-readable error description.
        details: Optional extra context dict.

    Returns:
        A single-element list of :class:`~mcp.types.TextContent` with a JSON payload.
    """
    payload: dict[str, Any] = {"error": True, "code": code, "message": message}
    if details:
        payload["details"] = details
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]


def success_response(data: dict) -> list[types.TextContent]:
    """Build a structured success response as MCP content.

    Args:
        data: Payload to serialise as JSON.

    Returns:
        A single-element list of :class:`~mcp.types.TextContent`.
    """
    return [types.TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def validate_required(arguments: dict, *fields: str) -> str | None:
    """Return an error message if any required field is missing from *arguments*.

    Args:
        arguments: The tool argument dict.
        *fields: Field names that must be present and non-empty.

    Returns:
        An error message string if validation fails, or ``None`` if all fields
        are present.
    """
    missing = [f for f in fields if not arguments.get(f)]
    if missing:
        return f"Missing required fields: {', '.join(missing)}"
    return None


def validate_type(arguments: dict, field: str, expected_type: type, label: str) -> str | None:
    """Return an error message if *field* is not of *expected_type*.

    Args:
        arguments: The tool argument dict.
        field: Key to check.
        expected_type: Python type that the value must satisfy.
        label: Human-readable type name for the error message.

    Returns:
        An error message string or ``None``.
    """
    value = arguments.get(field)
    if value is not None and not isinstance(value, expected_type):
        return f"Field '{field}' must be a {label}"
    return None


# ---------------------------------------------------------------------------
# Store & embedding factory helpers
# ---------------------------------------------------------------------------


def _create_embedding_provider(config: DistilleryConfig):  # type: ignore[return]
    """Instantiate an EmbeddingProvider based on config.

    Args:
        config: Loaded :class:`~distillery.config.DistilleryConfig`.

    Returns:
        An object satisfying the ``EmbeddingProvider`` protocol.

    Raises:
        ValueError: If the configured provider is unsupported or the API key is
            missing.
    """
    provider_name = config.embedding.provider
    model = config.embedding.model
    dimensions = config.embedding.dimensions
    api_key_env = config.embedding.api_key_env

    api_key: str | None = None
    if api_key_env:
        api_key = os.environ.get(api_key_env)

    if provider_name == "jina":
        from distillery.embedding.jina import JinaEmbeddingProvider

        return JinaEmbeddingProvider(
            api_key=api_key,
            api_key_env=api_key_env or None,
            model=model,
            dimensions=dimensions,
        )
    elif provider_name == "openai":
        from distillery.embedding.openai import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(
            api_key=api_key,
            api_key_env=api_key_env or None,
            model=model,
            dimensions=dimensions,
        )
    elif provider_name == "":
        # No provider configured -- return a lightweight stub used for testing
        # and status-only operations.
        from distillery.mcp._stub_embedding import StubEmbeddingProvider

        return StubEmbeddingProvider(dimensions=dimensions)
    else:
        raise ValueError(
            f"Unsupported embedding provider: {provider_name!r}. "
            "Must be one of: 'jina', 'openai'."
        )


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_server(config: DistilleryConfig | None = None) -> Server:
    """Build and return the configured MCP :class:`~mcp.server.Server`.

    The server is stateless at construction time -- the store and embedding
    provider are initialised during the lifespan context manager when the
    stdio transport connects.

    Args:
        config: Pre-loaded configuration.  When ``None`` the config is loaded
            from the standard locations (``DISTILLERY_CONFIG`` env var, then
            ``distillery.yaml`` in the cwd).

    Returns:
        A fully decorated :class:`~mcp.server.Server` ready to run.
    """
    if config is None:
        config = load_config()

    # We use a mutable container so that the inner handlers can reference the
    # store and embedding provider that are set up during lifespan.
    _state: dict[str, Any] = {}

    @asynccontextmanager
    async def _lifespan(server: Server):  # type: ignore[misc]
        """Startup / shutdown lifecycle for the Distillery MCP server."""
        logger.info("Distillery MCP server starting up …")

        # Build embedding provider and store.
        embedding_provider = _create_embedding_provider(config)
        _state["embedding_provider"] = embedding_provider
        _state["config"] = config

        db_path = os.path.expanduser(config.storage.database_path)

        from distillery.store.duckdb import DuckDBStore

        store = DuckDBStore(db_path=db_path, embedding_provider=embedding_provider)
        await store.initialize()
        _state["store"] = store

        logger.info(
            "Distillery MCP server ready (db=%s, embedding=%s)",
            db_path,
            getattr(embedding_provider, "model_name", "unknown"),
        )

        try:
            yield
        finally:
            logger.info("Distillery MCP server shutting down …")
            await store.close()
            logger.info("Distillery MCP server shutdown complete")

    server = Server("distillery", lifespan=_lifespan)

    # -----------------------------------------------------------------------
    # Tool registry
    # -----------------------------------------------------------------------

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="distillery_status",
                description=(
                    "Return runtime statistics for the Distillery knowledge base: "
                    "total entries, counts broken down by entry type and status, "
                    "database file size on disk, and the embedding model in use."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(
        tool_name: str, arguments: dict
    ) -> list[types.TextContent]:
        """Dispatch incoming tool calls to the appropriate handler."""
        store = _state.get("store")
        embedding_provider = _state.get("embedding_provider")
        cfg: DistilleryConfig = _state.get("config", config)

        if store is None:
            return error_response(
                "SERVER_ERROR",
                "Server is not fully initialised. Please retry.",
            )

        if tool_name == "distillery_status":
            return await _handle_status(store, embedding_provider, cfg)

        return error_response("UNKNOWN_TOOL", f"Unknown tool: {tool_name!r}")

    return server


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def _handle_status(
    store: Any,
    embedding_provider: Any,
    config: DistilleryConfig,
) -> list[types.TextContent]:
    """Implement the ``distillery_status`` tool.

    Queries the DuckDB store for aggregate statistics and returns them as a
    JSON payload.

    Args:
        store: Initialised :class:`~distillery.store.duckdb.DuckDBStore`.
        embedding_provider: The active embedding provider instance.
        config: The loaded Distillery configuration.

    Returns:
        MCP content list with a single JSON ``TextContent`` block.
    """
    try:
        stats = await asyncio.to_thread(_sync_gather_stats, store, embedding_provider, config)
        return success_response(stats)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Error gathering status stats")
        return error_response("STATUS_ERROR", f"Failed to gather status: {exc}")


def _sync_gather_stats(
    store: Any,
    embedding_provider: Any,
    config: DistilleryConfig,
) -> dict:
    """Synchronous helper that queries DuckDB for status statistics.

    Runs inside ``asyncio.to_thread`` so that blocking DuckDB calls do not
    stall the event loop.

    Args:
        store: Initialised ``DuckDBStore`` whose ``connection`` property is
            available.
        embedding_provider: Active embedding provider (for model metadata).
        config: Loaded ``DistilleryConfig``.

    Returns:
        A dict suitable for JSON serialisation.
    """
    conn = store.connection

    # Total entry count (all statuses).
    total_row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
    total_entries: int = total_row[0] if total_row else 0

    # Counts grouped by entry_type.
    type_rows = conn.execute(
        "SELECT entry_type, COUNT(*) AS cnt FROM entries GROUP BY entry_type ORDER BY cnt DESC"
    ).fetchall()
    entries_by_type = {row[0]: row[1] for row in type_rows}

    # Counts grouped by status.
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM entries GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    entries_by_status = {row[0]: row[1] for row in status_rows}

    # Database file size.
    db_path = os.path.expanduser(config.storage.database_path)
    database_size_bytes: int | None = None
    if db_path != ":memory:":
        try:
            database_size_bytes = Path(db_path).stat().st_size
        except OSError:
            database_size_bytes = None

    # Embedding model info.
    model_name = getattr(embedding_provider, "model_name", "unknown")
    embedding_dimensions = getattr(embedding_provider, "dimensions", None)

    return {
        "status": "ok",
        "total_entries": total_entries,
        "entries_by_type": entries_by_type,
        "entries_by_status": entries_by_status,
        "database_size_bytes": database_size_bytes,
        "embedding_model": model_name,
        "embedding_dimensions": embedding_dimensions,
        "database_path": db_path,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_server(config: DistilleryConfig | None = None) -> None:
    """Run the Distillery MCP server over stdio.

    This is the top-level coroutine launched by ``__main__.py``.

    Args:
        config: Optional pre-loaded config.  Defaults to auto-discovery.
    """
    server = create_server(config)
    init_options = server.create_initialization_options()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, init_options)
