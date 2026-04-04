from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


def _parse_sse_result(text: str) -> Any:
    """
    Parse a FastMCP streamable-HTTP SSE response.

    FastMCP emits one or more `data: {json}` lines; we return the last
    `{ "result": ... }` payload found.
    """

    last_result: Any | None = None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue

        data_str = line[5:].strip()
        if not data_str or data_str == "[DONE]":
            continue

        parsed = json.loads(data_str)
        if "error" in parsed and parsed["error"] is not None:
            err = parsed["error"]
            raise RuntimeError(
                f"MCP error: {err.get('code')}: {err.get('message')} ({err.get('data')})"
            )
        if "result" in parsed:
            last_result = parsed["result"]

    if last_result is None:
        raise RuntimeError("No MCP result found in SSE response")

    return last_result


def _unwrap_mcp_json_payload(tool_result: Any) -> Any:
    """
    FastMCP tool responses are typically shaped like:
      { "content": [ { "type": "text", "text": "<json string>" }, ... ] }

    The Distillery server returns `types.TextContent(text=json.dumps(data))`, so
    we decode the first `text` block as JSON when possible.
    """

    if not isinstance(tool_result, dict):
        return tool_result

    content = tool_result.get("content")
    if not isinstance(content, list) or not content:
        return tool_result

    first = content[0]
    if not isinstance(first, dict):
        return tool_result

    if first.get("type") != "text":
        return tool_result

    text_payload = first.get("text")
    if not isinstance(text_payload, str):
        return tool_result

    try:
        return json.loads(text_payload)
    except Exception:
        return tool_result


@dataclass
class MCPHTTPClient:
    """
    Minimal JSON-RPC 2.0 helper for Distillery's `streamable-http` MCP endpoint.

    This matches the JS client behavior in `browser-extension/src/mcp-client.js`.
    """

    server_url: str  # e.g. https://distillery-mcp.fly.dev/mcp
    auth_token: str | None = None

    _session_id: str | None = None
    _request_id: int = 0

    async def initialize(self) -> dict[str, Any]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {
                    "name": "distillery-e2e-harness",
                    "version": "0.1.0",
                },
            },
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(self.server_url, headers=headers, json=payload)

        if resp.status_code == 401:
            raise RuntimeError("MCP auth failed (401)")
        if resp.status_code >= 400:
            raise RuntimeError(f"MCP initialize HTTP {resp.status_code}: {resp.text[:200]}")

        session_id = resp.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id

        return _parse_sse_result(resp.text)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        if self._session_id is None:
            raise RuntimeError("MCP client not initialized (missing session id)")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Mcp-Session-Id": self._session_id,
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.server_url, headers=headers, json=payload)

        if resp.status_code == 401:
            raise RuntimeError("MCP auth failed (401) during tools/call")
        if resp.status_code >= 400:
            raise RuntimeError(
                f"MCP tools/call HTTP {resp.status_code}: {resp.text[:200]}"
            )

        tool_result = _parse_sse_result(resp.text)
        return _unwrap_mcp_json_payload(tool_result)

