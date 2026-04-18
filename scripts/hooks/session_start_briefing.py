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

import contextlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import warnings
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
    headers: dict[str, str] = field(default_factory=dict)
    source: str = ""


def _normalize_mcp_url(url: str) -> tuple[str, str]:
    """Normalize a base URL into canonical (mcp_url, health_url).

    The MCP endpoint always ends with ``/mcp`` (no trailing slash) and the
    health endpoint is its sibling ``/health``. If the input already ends with
    ``/mcp`` or ``/health``, the base is derived accordingly; otherwise the
    input is treated as a base and ``/mcp`` is appended.
    """
    stripped = url.rstrip("/")
    if stripped.endswith("/mcp"):
        mcp_url = stripped
        base = stripped[: -len("/mcp")]
    elif stripped.endswith("/health"):
        base = stripped[: -len("/health")]
        mcp_url = base + "/mcp"
    else:
        base = stripped
        mcp_url = stripped + "/mcp"
    return mcp_url, base + "/health"


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
        raw_headers = entry.get("headers") or {}
        headers = (
            {str(k): str(v) for k, v in raw_headers.items()}
            if isinstance(raw_headers, dict)
            else {}
        )
        return ResolvedTransport(kind="http", url=url, headers=headers, source=source)

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
        parts = shlex.split(cmd)
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
    """Step 4: ~/.claude.json -> projects[<cwd>].mcpServers.

    When cwd is nested under multiple configured project paths, the *deepest*
    (longest) matching project wins so nested subprojects override their
    parents.
    """
    claude_json = Path.home() / ".claude.json"
    data = _read_json(claude_json)
    if not isinstance(data, dict):
        return None
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        return None
    cwd_resolved = cwd.resolve()
    best: tuple[int, str, dict[str, Any]] | None = None
    for project_path, project_data in projects.items():
        if not isinstance(project_data, dict) or not isinstance(project_path, str):
            continue
        try:
            candidate = Path(project_path).resolve()
        except (OSError, ValueError):
            continue
        try:
            if not (cwd_resolved == candidate or cwd_resolved.is_relative_to(candidate)):
                continue
        except (OSError, ValueError):
            continue
        depth = len(candidate.parts)
        if best is None or depth > best[0]:
            best = (depth, project_path, project_data)
    if best is not None:
        _, project_path, project_data = best
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


def resolve_transport(cwd: Path | None = None, bearer_token: str = "") -> ResolvedTransport:
    """Run the full resolution chain, returning the first *reachable* match.

    Each resolver's candidate is probed for reachability; if it fails, the
    chain falls through to the next resolver. This matches the documented
    "first reachable wins" contract. If no candidate is reachable, the
    localhost fallback is returned (without probing, so the caller can decide
    how to report the failure).
    """
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
        try:
            result = resolver()
        except Exception:
            continue
        if result is None:
            continue
        try:
            if probe_transport(result, bearer_token):
                return result
        except Exception:
            continue

    return resolve_localhost_fallback()


# ---------------------------------------------------------------------------
# Probes — verify transport is actually reachable
# ---------------------------------------------------------------------------


def _http_health_check(
    base_url: str,
    bearer_token: str = "",
    timeout: int = 2,
    transport_headers: dict[str, str] | None = None,
) -> bool:
    """Probe an HTTP MCP transport for reachability.

    Performs ``GET /health`` first and then a minimal JSON-RPC POST to the
    ``/mcp`` endpoint. Both must succeed with a 2xx status; the JSON-RPC
    response must parse as a JSON-RPC reply (``jsonrpc``, ``id``, and either
    ``result`` or ``error``). Returns False on any failure, ensuring a healthy
    sidecar alone cannot mask a dead MCP endpoint.
    """
    mcp_url, health_url = _normalize_mcp_url(base_url)

    def _merge(call_headers: dict[str, str]) -> dict[str, str]:
        merged: dict[str, str] = {}
        if transport_headers:
            merged.update(transport_headers)
        merged.update(call_headers)
        if bearer_token and "Authorization" not in merged:
            merged["Authorization"] = f"Bearer {bearer_token}"
        return merged

    # Step 1: GET /health
    req = urllib.request.Request(health_url, method="GET")
    for name, value in _merge({}).items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) >= 400:
                return False
    except (urllib.error.URLError, OSError, ValueError):
        return False

    # Step 2: JSON-RPC POST /mcp
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }
    ).encode()
    mcp_req = urllib.request.Request(mcp_url, data=payload, method="POST")
    for name, value in _merge(
        {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
    ).items():
        mcp_req.add_header(name, value)
    try:
        with urllib.request.urlopen(mcp_req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status >= 400:
                return False
            body = resp.read()
    except (urllib.error.URLError, OSError, ValueError):
        return False

    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return False

    if not isinstance(parsed, dict):
        return False
    if parsed.get("jsonrpc") != "2.0":
        return False
    return "result" in parsed or "error" in parsed


def _http_call_tool(
    url: str,
    tool_name: str,
    arguments: dict[str, Any],
    bearer_token: str = "",
    timeout: int = 10,
    transport_headers: dict[str, str] | None = None,
) -> Any:
    """JSON-RPC tools/call over HTTP.

    ``url`` is normalized to the canonical ``/mcp`` endpoint so tool calls
    always hit the MCP handler, never the health sidecar or bare base URL.
    Per-call headers (``Content-Type``, ``Accept``, and bearer) override
    matching ``transport_headers`` defaults.
    """
    mcp_url, _ = _normalize_mcp_url(url)

    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    ).encode()

    req = urllib.request.Request(mcp_url, data=payload, method="POST")
    merged: dict[str, str] = {}
    if transport_headers:
        merged.update(transport_headers)
    merged["Content-Type"] = "application/json"
    merged.setdefault("Accept", "application/json, text/event-stream")
    if bearer_token:
        merged["Authorization"] = f"Bearer {bearer_token}"
    for name, value in merged.items():
        req.add_header(name, value)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def _build_init_msg() -> str:
    return json.dumps(
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


def _build_initialized_notification() -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
    )


def _stdio_call_tool(
    command: list[str],
    tool_name: str,
    arguments: dict[str, Any],
    extra_env: dict[str, str] | None = None,
    timeout: int = 10,
) -> Any:
    """JSON-RPC ``tools/call`` over a stdio subprocess.

    Protocol sequence: ``initialize`` request, ``notifications/initialized``
    notification (required by MCP), then the ``tools/call`` request. All
    messages are written as a single ``communicate`` input blob (stdin is
    closed *by* ``communicate``, never manually before it), so we avoid the
    "flush of closed file" ``ValueError`` that results from closing stdin and
    then calling ``communicate``.
    """
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

    payload = (
        _build_init_msg() + "\n" + _build_initialized_notification() + "\n" + call_msg + "\n"
    ).encode()

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except OSError:
        return None

    try:
        try:
            stdout_bytes, _ = proc.communicate(input=payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=1)
            return None
    except OSError:
        return None

    # Parse line-delimited JSON responses, find id=1
    for line in stdout_bytes.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("id") == 1:
            return msg

    return None


def _stdio_health_check(
    command: list[str],
    extra_env: dict[str, str] | None = None,
    timeout: int = 3,
) -> bool:
    """Verify that a stdio MCP server completes the initialize handshake.

    Writes ``initialize`` + ``notifications/initialized`` as a single input
    blob to ``communicate``, which handles stdin close safely. A successful
    handshake is signalled by a JSON-RPC reply with ``id == 0`` and a
    ``result`` field (the server's initialize response).
    """
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)

    payload = (_build_init_msg() + "\n" + _build_initialized_notification() + "\n").encode()

    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except OSError:
        return False

    try:
        try:
            stdout_bytes, _ = proc.communicate(input=payload, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=1)
            return False
    except OSError:
        return False

    for line in stdout_bytes.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("id") == 0 and "result" in msg:
            return True

    return False


def probe_transport(transport: ResolvedTransport, bearer_token: str = "") -> bool:
    """Verify that the resolved transport is actually reachable."""
    if transport.kind == "http":
        return _http_health_check(transport.url, bearer_token, transport_headers=transport.headers)
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
        return _http_call_tool(
            transport.url,
            tool_name,
            arguments,
            bearer_token,
            transport_headers=transport.headers,
        )
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


def _extract_snippets(text: str, max_items: int) -> tuple[int, list[str]]:
    """Parse JSON entries and extract content snippets, falling back to string scanning.

    Returns a (count, snippets) tuple where count is the number of entries found
    and snippets is a list of truncated content strings (up to max_items).
    """
    # Attempt JSON parsing first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            count = len(parsed)
            snippets: list[str] = []
            for item in parsed[:max_items]:
                if isinstance(item, dict):
                    content = item.get("content", "")
                    if isinstance(content, str) and content:
                        snippets.append(content[:60])
            return count, snippets
        if isinstance(parsed, dict):
            # ``distillery_list`` shape: {"entries": [...], "count": N, "total_count": M, ...}
            entries = parsed.get("entries")
            if isinstance(entries, list):
                count_raw = parsed.get("total_count", parsed.get("count", len(entries)))
                count = count_raw if isinstance(count_raw, int) else len(entries)
                entry_snippets: list[str] = []
                for item in entries[:max_items]:
                    if not isinstance(item, dict):
                        continue
                    snippet_src = (
                        item.get("content_preview")
                        or item.get("title")
                        or item.get("content")
                        or ""
                    )
                    if isinstance(snippet_src, str) and snippet_src:
                        entry_snippets.append(snippet_src[:60])
                return count, entry_snippets

            # Single entry wrapped in a dict — treat as a list of one
            count = 1
            content = parsed.get("content", "")
            snippet = [content[:60]] if isinstance(content, str) and content else []
            return count, snippet
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: brittle string scanning (preserves behaviour for non-JSON text)
    count = text.count('"id"')
    snippets = []
    for part in text.split('"content":"')[1 : max_items + 1]:
        snippet = part.split('"')[0][:60]
        if snippet:
            snippets.append(snippet)
    return count, snippets


def build_briefing(project: str, recent_text: str, stale_text: str) -> list[str]:
    """Build condensed briefing lines (max 20)."""
    lines: list[str] = [f"[Distillery] Project: {project}"]

    if recent_text and recent_text != "null":
        entry_count, snippets = _extract_snippets(recent_text, 3)
        if entry_count > 0 and snippets:
            lines.append(f"Recent ({entry_count}): {', '.join(snippets)}")

    if stale_text and stale_text != "null":
        stale_count, snippets = _extract_snippets(stale_text, 2)
        if stale_count > 0 and snippets:
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
    _limit_raw = os.environ.get("DISTILLERY_BRIEFING_LIMIT", "5")
    try:
        limit = int(_limit_raw)
    except ValueError:
        warnings.warn(
            f"DISTILLERY_BRIEFING_LIMIT={_limit_raw!r} is not a valid integer; defaulting to 5",
            stacklevel=1,
        )
        limit = 5

    # Resolve transport — probes each candidate, returning the first reachable
    # match (or the localhost fallback if none were reachable).
    transport = resolve_transport(cwd_path, bearer_token)

    # Probe reachability — exit silently if unreachable (covers the fallback
    # path where no prior candidate probed as reachable).
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

    # Fetch stale entries.
    # Issue #307: there is no ``distillery_stale`` MCP tool on the consolidated
    # surface; route via ``distillery_list`` with ``stale_days`` instead.
    stale_resp = call_tool(
        transport,
        "distillery_list",
        {"project": project, "stale_days": 30, "limit": 3},
        bearer_token,
    )
    stale_text = extract_text(stale_resp)

    # Build and output briefing
    lines = build_briefing(project, recent_text, stale_text)
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()
