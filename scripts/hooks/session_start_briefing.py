#!/usr/bin/env python3
"""Dynamic MCP transport resolution for SessionStart briefing hook.

Resolves the Distillery MCP server using this priority order:
1. DISTILLERY_MCP_URL env var -> HTTP
2. DISTILLERY_MCP_COMMAND env var -> stdio
3. .mcp.json at repo root (walk upward from cwd) -> mcpServers.*distill*
4. ~/.claude.json -> projects[<cwd>].mcpServers.*distill*
5. ~/.claude.json -> top-level mcpServers.*distill*
6. ~/.claude/plugins/**/.claude-plugin/plugin.json -> mcpServers.distillery
7. Fallback: distillery-mcp command on PATH (stdio)
8. Fallback: http://localhost:8000/mcp

No runtime dependencies beyond the Python 3.11+ stdlib.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ResolvedTransport:
    """Result of MCP transport resolution."""

    kind: str  # "http" or "stdio"
    url: str = ""
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    source: str = ""


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    """Read and parse a JSON file, returning None on failure."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _find_distillery_server(servers: Any) -> dict[str, Any] | None:
    """Find a *distill* key in an mcpServers dict."""
    if not isinstance(servers, dict):
        return None
    for key, value in servers.items():
        if "distill" in key.lower() and isinstance(value, dict):
            return value
    return None


def _server_entry_to_transport(entry: dict[str, Any], source: str) -> ResolvedTransport | None:
    """Convert an mcpServers entry to a ResolvedTransport."""
    # HTTP (url-based or type: sse/streamable-http)
    url = entry.get("url", "")
    if url:
        return ResolvedTransport(kind="http", url=url, source=source)

    # stdio (command-based)
    cmd = entry.get("command", "")
    args: list[str] = entry.get("args", [])
    env_vars: dict[str, str] = entry.get("env", {})
    if cmd:
        full_cmd = [cmd] + [str(a) for a in args]
        return ResolvedTransport(kind="stdio", command=full_cmd, env=env_vars, source=source)

    return None


def _walk_up_for_file(start: Path, filename: str) -> Path | None:
    """Walk up from start directory looking for filename."""
    current = start.resolve()
    while True:
        candidate = current / filename
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


# ---------------------------------------------------------------------------
# Resolution steps (1-8)
# ---------------------------------------------------------------------------


def resolve_env_url() -> ResolvedTransport | None:
    """Step 1: DISTILLERY_MCP_URL env var."""
    url = os.environ.get("DISTILLERY_MCP_URL", "").strip()
    if url:
        return ResolvedTransport(kind="http", url=url, source="DISTILLERY_MCP_URL")
    return None


def resolve_env_command() -> ResolvedTransport | None:
    """Step 2: DISTILLERY_MCP_COMMAND env var."""
    cmd = os.environ.get("DISTILLERY_MCP_COMMAND", "").strip()
    if cmd:
        parts = cmd.split()
        return ResolvedTransport(kind="stdio", command=parts, source="DISTILLERY_MCP_COMMAND")
    return None


def resolve_mcp_json(cwd: Path) -> ResolvedTransport | None:
    """Step 3: .mcp.json at or above cwd."""
    mcp_json_path = _walk_up_for_file(cwd, ".mcp.json")
    if mcp_json_path is None:
        return None
    data = _read_json(mcp_json_path)
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers", {})
    entry = _find_distillery_server(servers)
    if entry is not None:
        return _server_entry_to_transport(entry, f".mcp.json ({mcp_json_path})")
    return None


def resolve_claude_json_project(cwd: Path) -> ResolvedTransport | None:
    """Step 4: ~/.claude.json -> projects[<cwd>].mcpServers."""
    claude_json = Path.home() / ".claude.json"
    data = _read_json(claude_json)
    if not isinstance(data, dict):
        return None
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        return None
    cwd_str = str(cwd.resolve())
    for project_path, project_data in projects.items():
        if not isinstance(project_data, dict):
            continue
        if cwd_str == project_path or cwd_str.startswith(project_path + "/"):
            servers = project_data.get("mcpServers", {})
            entry = _find_distillery_server(servers)
            if entry is not None:
                return _server_entry_to_transport(entry, f"~/.claude.json projects[{project_path}]")
    return None


def resolve_claude_json_global() -> ResolvedTransport | None:
    """Step 5: ~/.claude.json -> top-level mcpServers."""
    claude_json = Path.home() / ".claude.json"
    data = _read_json(claude_json)
    if not isinstance(data, dict):
        return None
    servers = data.get("mcpServers", {})
    entry = _find_distillery_server(servers)
    if entry is not None:
        return _server_entry_to_transport(entry, "~/.claude.json (global)")
    return None


def resolve_plugin_json() -> ResolvedTransport | None:
    """Step 6: ~/.claude/plugins/**/.claude-plugin/plugin.json."""
    plugins_dir = Path.home() / ".claude" / "plugins"
    if not plugins_dir.is_dir():
        return None
    try:
        for plugin_json in plugins_dir.rglob(".claude-plugin/plugin.json"):
            data = _read_json(plugin_json)
            if not isinstance(data, dict):
                continue
            servers = data.get("mcpServers", {})
            if isinstance(servers, dict) and "distillery" in servers:
                entry = servers["distillery"]
                if isinstance(entry, dict):
                    return _server_entry_to_transport(entry, f"plugin ({plugin_json})")
    except OSError:
        pass
    return None


def resolve_path_command() -> ResolvedTransport | None:
    """Step 7: distillery-mcp on PATH."""
    if shutil.which("distillery-mcp") is not None:
        return ResolvedTransport(
            kind="stdio",
            command=["distillery-mcp"],
            source="distillery-mcp (PATH)",
        )
    return None


def resolve_localhost_fallback() -> ResolvedTransport:
    """Step 8: Fallback to localhost."""
    return ResolvedTransport(
        kind="http",
        url="http://localhost:8000/mcp",
        source="localhost fallback",
    )


def resolve_transport(cwd: Path | None = None) -> ResolvedTransport:
    """Run the full resolution chain, returning the first match."""
    if cwd is None:
        cwd = Path.cwd()

    resolvers = [
        lambda: resolve_env_url(),
        lambda: resolve_env_command(),
        lambda: resolve_mcp_json(cwd),
        lambda: resolve_claude_json_project(cwd),
        lambda: resolve_claude_json_global(),
        lambda: resolve_plugin_json(),
        lambda: resolve_path_command(),
    ]

    for resolver in resolvers:
        result = resolver()
        if result is not None:
            return result

    return resolve_localhost_fallback()


# ---------------------------------------------------------------------------
# Probes — verify transport is actually reachable
# ---------------------------------------------------------------------------


def _http_health_check(base_url: str, bearer_token: str = "", timeout: int = 2) -> bool:
    """GET /health on the HTTP transport."""
    health_url = base_url.rstrip("/")
    if health_url.endswith("/mcp"):
        health_url = health_url[: -len("/mcp")] + "/health"
    elif not health_url.endswith("/health"):
        health_url = health_url + "/health"

    req = urllib.request.Request(health_url, method="GET")
    if bearer_token:
        req.add_header("Authorization", f"Bearer {bearer_token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _http_call_tool(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
    bearer_token: str = "",
    timeout: int = 10,
) -> Any:
    """JSON-RPC tools/call over HTTP."""
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    ).encode()

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    if bearer_token:
        req.add_header("Authorization", f"Bearer {bearer_token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def _stdio_call_tool(
    command: list[str],
    tool_name: str,
    arguments: dict[str, Any],
    extra_env: dict[str, str] | None = None,
    timeout: int = 10,
) -> Any:
    """JSON-RPC tools/call over stdio subprocess.

    Sends initialize, then tools/call, reads responses line by line.
    """
    init_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "distillery-hook", "version": "1.0.0"},
            },
        }
    )

    call_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    )

    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None

        # Send initialize + call, each newline-delimited
        proc.stdin.write((init_msg + "\n").encode())
        proc.stdin.write((call_msg + "\n").encode())
        proc.stdin.flush()
        proc.stdin.close()

        # Read all output within timeout
        try:
            stdout_bytes, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return None

        # Parse line-delimited JSON responses, find id=1
        for line in stdout_bytes.decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if isinstance(msg, dict) and msg.get("id") == 1:
                    return msg
            except json.JSONDecodeError:
                continue

    except (OSError, ValueError):
        pass

    return None


def _stdio_health_check(
    command: list[str],
    extra_env: dict[str, str] | None = None,
    timeout: int = 3,
) -> bool:
    """Check if a stdio MCP server starts successfully via initialize handshake."""
    init_msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "distillery-hook", "version": "1.0.0"},
            },
        }
    )

    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None

        proc.stdin.write((init_msg + "\n").encode())
        proc.stdin.flush()
        proc.stdin.close()

        try:
            stdout_bytes, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return False

        for line in stdout_bytes.decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if isinstance(msg, dict) and "result" in msg:
                    return True
            except json.JSONDecodeError:
                continue

    except (OSError, ValueError):
        pass

    return False


def probe_transport(transport: ResolvedTransport, bearer_token: str = "") -> bool:
    """Verify that the resolved transport is actually reachable."""
    if transport.kind == "http":
        return _http_health_check(transport.url, bearer_token)
    elif transport.kind == "stdio":
        return _stdio_health_check(transport.command, transport.env)
    return False


def call_tool(
    transport: ResolvedTransport,
    tool_name: str,
    arguments: dict[str, Any],
    bearer_token: str = "",
) -> Any:
    """Call an MCP tool via the resolved transport."""
    if transport.kind == "http":
        return _http_call_tool(transport.url, tool_name, arguments, bearer_token)
    elif transport.kind == "stdio":
        return _stdio_call_tool(transport.command, tool_name, arguments, transport.env)
    return None


# ---------------------------------------------------------------------------
# Briefing output
# ---------------------------------------------------------------------------


def extract_text(response: Any) -> str:
    """Extract text from an MCP JSON-RPC response."""
    if not isinstance(response, dict):
        return ""
    result = response.get("result", {})
    if not isinstance(result, dict):
        return ""
    content = result.get("content", [])
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return first.get("text", "")
    return ""


def build_briefing(project: str, recent_text: str, stale_text: str) -> list[str]:
    """Build condensed briefing lines (max 20)."""
    lines: list[str] = [f"[Distillery] Project: {project}"]

    if recent_text and recent_text != "null":
        entry_count = recent_text.count('"id"')
        if entry_count > 0:
            # Extract content snippets
            snippets: list[str] = []
            for part in recent_text.split('"content":"')[1:4]:
                snippet = part.split('"')[0][:60]
                if snippet:
                    snippets.append(snippet)
            if snippets:
                lines.append(f"Recent ({entry_count}): {', '.join(snippets)}")

    if stale_text and stale_text != "null":
        stale_count = stale_text.count('"id"')
        if stale_count > 0:
            snippets = []
            for part in stale_text.split('"content":"')[1:3]:
                snippet = part.split('"')[0][:60]
                if snippet:
                    snippets.append(snippet)
            if snippets:
                lines.append(f"Stale ({stale_count}): {', '.join(snippets)}")

    return lines[:20]


def derive_project(cwd: str) -> str:
    """Derive project name from git root or cwd."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return os.path.basename(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass
    return os.path.basename(cwd)


def main() -> None:
    """Entry point for the SessionStart briefing hook."""
    # Read hook JSON from stdin
    try:
        hook_json_str = sys.stdin.read()
    except (OSError, KeyboardInterrupt):
        sys.exit(0)

    # Parse cwd from hook input
    cwd = ""
    try:
        hook_data = json.loads(hook_json_str)
        cwd = hook_data.get("cwd", "")
    except (json.JSONDecodeError, AttributeError):
        pass

    if not cwd:
        cwd = os.getcwd()

    cwd_path = Path(cwd)

    # Configuration
    bearer_token = os.environ.get("DISTILLERY_BEARER_TOKEN", "")
    limit = int(os.environ.get("DISTILLERY_BRIEFING_LIMIT", "5"))

    # Resolve transport
    transport = resolve_transport(cwd_path)

    # Probe reachability — exit silently if unreachable
    if not probe_transport(transport, bearer_token):
        sys.exit(0)

    # Derive project
    project = derive_project(cwd)

    # Fetch recent entries
    recent_resp = call_tool(
        transport,
        "distillery_list",
        {"project": project, "limit": limit},
        bearer_token,
    )
    recent_text = extract_text(recent_resp)

    # Fetch stale entries
    stale_resp = call_tool(
        transport,
        "distillery_stale",
        {"days": 30, "limit": 3},
        bearer_token,
    )
    stale_text = extract_text(stale_resp)

    # Build and output briefing
    lines = build_briefing(project, recent_text, stale_text)
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
