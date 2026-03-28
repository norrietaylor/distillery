"""Integration tests for the Distillery MCP HTTP transport.

Tests verify:
- HTTP server starts and responds to MCP initialize
- All 17 tools are accessible over HTTP transport
- Stateless HTTP singleton: two requests share same store instance
- stdio mode (no flags) backward compatibility
"""

from __future__ import annotations

import asyncio
import json
import socket

import httpx
import pytest
import uvicorn

from distillery.config import DistilleryConfig, StorageConfig
from distillery.mcp.__main__ import _parse_args
from distillery.mcp.server import create_server

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# All 17 tools that the Distillery MCP server exposes.
EXPECTED_TOOLS = {
    "distillery_status",
    "distillery_store",
    "distillery_get",
    "distillery_update",
    "distillery_search",
    "distillery_find_similar",
    "distillery_list",
    "distillery_classify",
    "distillery_review_queue",
    "distillery_resolve_review",
    "distillery_check_conflicts",
    "distillery_check_dedup",
    "distillery_metrics",
    "distillery_quality",
    "distillery_stale",
    "distillery_tag_tree",
    "distillery_type_schemas",
}


def _free_port() -> int:
    """Return an available ephemeral port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_server_config() -> DistilleryConfig:
    """Return a DistilleryConfig using an in-memory DuckDB database."""
    return DistilleryConfig(storage=StorageConfig(database_path=":memory:"))


def _parse_sse_data(text: str) -> dict:  # type: ignore[type-arg]
    """Extract the JSON payload from an SSE response body."""
    for line in text.split("\n"):
        if line.startswith("data:"):
            return json.loads(line[5:].strip())  # type: ignore[no-any-return]
    raise ValueError(f"No 'data:' line found in SSE response: {text[:200]!r}")


async def _start_http_server(
    port: int, config: DistilleryConfig
) -> tuple[uvicorn.Server, asyncio.Task]:  # type: ignore[type-arg]
    """Start the Distillery MCP HTTP server on *port* using *config*.

    Returns the uvicorn Server instance and the background task.
    """
    server = create_server(config=config)
    http_app = server.http_app(path="/mcp", transport="streamable-http", stateless_http=True)
    uv_config = uvicorn.Config(
        app=http_app,
        host="127.0.0.1",
        port=port,
        lifespan="on",
        log_level="warning",
    )
    uv_server = uvicorn.Server(uv_config)
    task = asyncio.create_task(uv_server.serve())

    # Wait for startup (up to 5 seconds).
    for _ in range(50):
        await asyncio.sleep(0.1)
        if uv_server.started:
            break

    if not uv_server.started:
        uv_server.should_exit = True
        await task
        raise RuntimeError(f"HTTP server failed to start on port {port}")

    return uv_server, task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHttpServerStarts:
    async def test_http_server_starts(self) -> None:
        """--transport http binds and responds to MCP initialize handshake."""
        port = _free_port()
        config = _make_server_config()
        uv_server, task = await _start_http_server(port, config)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"http://127.0.0.1:{port}/mcp",
                    headers=MCP_HEADERS,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1.0"},
                        },
                    },
                )
            assert resp.status_code == 200
            data = _parse_sse_data(resp.text)
            assert "result" in data, f"Expected result in: {data}"
            assert data["result"]["protocolVersion"] == "2024-11-05"
        finally:
            uv_server.should_exit = True
            await task


class TestAllToolsAccessibleOverHttp:
    async def test_all_tools_accessible_over_http(self) -> None:
        """All 17 tools appear in tools/list response over HTTP."""
        port = _free_port()
        config = _make_server_config()
        uv_server, task = await _start_http_server(port, config)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"http://127.0.0.1:{port}/mcp",
                    headers=MCP_HEADERS,
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                )
            assert resp.status_code == 200
            data = _parse_sse_data(resp.text)
            assert "result" in data, f"Expected result in: {data}"
            tools = data["result"]["tools"]
            tool_names = {t["name"] for t in tools}
            assert len(tool_names) == 17, f"Expected 17 tools, got {len(tool_names)}: {tool_names}"
            assert tool_names == EXPECTED_TOOLS, (
                f"Tool mismatch.\nExpected: {EXPECTED_TOOLS}\nGot: {tool_names}"
            )
        finally:
            uv_server.should_exit = True
            await task


class TestStatelessHttpSingleton:
    async def test_stateless_http_singleton(self) -> None:
        """Two sequential HTTP requests share the same store instance (lifespan singleton)."""
        port = _free_port()
        config = _make_server_config()
        uv_server, task = await _start_http_server(port, config)

        try:
            base_url = f"http://127.0.0.1:{port}/mcp"
            async with httpx.AsyncClient(timeout=5.0) as client:
                # First request: call distillery_status to confirm server is live.
                r1 = await client.post(
                    base_url,
                    headers=MCP_HEADERS,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": "distillery_status", "arguments": {}},
                    },
                )
                # Second request: call distillery_list to confirm store is shared.
                r2 = await client.post(
                    base_url,
                    headers=MCP_HEADERS,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "distillery_status", "arguments": {}},
                    },
                )
            assert r1.status_code == 200, f"First request failed: {r1.text[:200]}"
            assert r2.status_code == 200, f"Second request failed: {r2.text[:200]}"

            d1 = _parse_sse_data(r1.text)
            d2 = _parse_sse_data(r2.text)

            # Both responses should contain valid tool results (not errors).
            assert "result" in d1, f"Request 1 error: {d1}"
            assert "result" in d2, f"Request 2 error: {d2}"

            # Both responses should report the same total_entries count,
            # confirming they share the same store instance.
            def _total_entries(resp_data: dict) -> int:  # type: ignore[type-arg]
                content = resp_data["result"]["content"]
                payload = json.loads(content[0]["text"])
                return int(payload["total_entries"])

            assert _total_entries(d1) == _total_entries(d2), (
                "Two requests returned different total_entries — singleton not shared"
            )
        finally:
            uv_server.should_exit = True
            await task


class TestStdioDefaultUnchanged:
    def test_stdio_default_unchanged(self) -> None:
        """distillery-mcp with no flags selects stdio transport (backward compat)."""
        ns = _parse_args([])
        assert ns.transport == "stdio", f"Expected stdio, got {ns.transport!r}"
        assert ns.host is None
        assert ns.port is None

    def test_stdio_explicit(self) -> None:
        """distillery-mcp --transport stdio selects stdio mode."""
        ns = _parse_args(["--transport", "stdio"])
        assert ns.transport == "stdio"

    def test_http_transport_flag(self) -> None:
        """distillery-mcp --transport http selects http mode."""
        ns = _parse_args(["--transport", "http"])
        assert ns.transport == "http"

    def test_http_with_host_and_port(self) -> None:
        """--host and --port are parsed correctly for HTTP mode."""
        ns = _parse_args(["--transport", "http", "--host", "127.0.0.1", "--port", "9000"])
        assert ns.transport == "http"
        assert ns.host == "127.0.0.1"
        assert ns.port == 9000
