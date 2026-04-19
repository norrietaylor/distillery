"""Tests for the SessionStart briefing hook script (issue #307).

The SessionStart hook dispatches to a Python script
(``scripts/hooks/session_start_briefing.py``) that calls Distillery MCP tools
to render recent + stale briefing sections.  If the hook names a tool that
does not exist in the MCP catalog, the JSON-RPC response is an error and
the section is silently dropped.

These tests parse the Python script to extract every tool name used in a
``call_tool(...)`` invocation and verify that each one is actually registered
on the MCP surface.  The stale-section assertion pins the fix for #307:
the hook must use ``distillery_list`` (with ``stale_days``) rather than
the removed ``distillery_stale`` tool.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from distillery.config import DistilleryConfig, EmbeddingConfig, StorageConfig
from distillery.mcp.server import create_server

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK_SCRIPT = REPO_ROOT / "scripts" / "hooks" / "session_start_briefing.py"

# Matches the positional tool-name argument in a ``call_tool(transport, "name", ...)``
# invocation in the Python hook.
_CALL_TOOL_RE = re.compile(r'call_tool\(\s*[^,]+,\s*"(?P<name>[A-Za-z0-9_]+)"')


def _hook_tool_names() -> list[str]:
    """Return every tool name referenced by a ``call_tool`` invocation."""
    text = HOOK_SCRIPT.read_text(encoding="utf-8")
    return _CALL_TOOL_RE.findall(text)


async def _registered_tool_names() -> set[str]:
    """Return the set of tool names currently registered on the MCP server."""
    config = DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
    )
    server = create_server(config)
    tools = await server.list_tools()
    return {t.name for t in tools}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSessionStartBriefingHook:
    def test_hook_script_exists(self) -> None:
        assert HOOK_SCRIPT.is_file(), f"Expected hook at {HOOK_SCRIPT}"

    def test_hook_references_call_tool(self) -> None:
        """Sanity: the hook must actually invoke call_tool at least twice."""
        names = _hook_tool_names()
        # One call for the recent section, one for the stale section.
        assert len(names) >= 2, f"Expected >=2 call_tool invocations in the hook, found {names}"

    async def test_every_hook_tool_is_registered(self) -> None:
        """Every tool name the hook calls must exist in the MCP catalog."""
        registered = await _registered_tool_names()
        for name in _hook_tool_names():
            assert name in registered, (
                f"Hook calls tool {name!r} but it is not registered on the MCP "
                f"server. Registered tools: {sorted(registered)}"
            )

    def test_hook_does_not_call_removed_distillery_stale(self) -> None:
        """Pin fix for #307: distillery_stale was removed from the MCP catalog."""
        names = _hook_tool_names()
        assert "distillery_stale" not in names, (
            "scripts/hooks/session_start_briefing.py still calls "
            "'distillery_stale', which no longer exists on the MCP surface. "
            "Use distillery_list with stale_days instead (issue #307)."
        )

    def test_hook_stale_section_uses_distillery_list_with_stale_days(self) -> None:
        """The stale section must call distillery_list with a stale_days param."""
        text = HOOK_SCRIPT.read_text(encoding="utf-8")
        # Locate the block from the "Fetch stale entries" comment through the
        # end of the ``call_tool`` invocation (its closing paren).
        match = re.search(
            r"Fetch stale entries.*?call_tool\(\s*[^,]+,\s*\"(?P<name>[A-Za-z0-9_]+)\""
            r"(?P<params>[^)]*)",
            text,
            re.DOTALL,
        )
        assert match is not None, "Could not locate stale-section call_tool block"
        assert match.group("name") == "distillery_list", (
            f"Stale section must call 'distillery_list', got {match.group('name')!r}"
        )
        # ``stale_days`` must appear as an actual param key in the call, not
        # merely as text in an adjacent comment.
        params = match.group("params")
        assert "stale_days" in params, (
            "Stale section must pass a 'stale_days' argument to distillery_list; "
            f"captured params: {params!r}"
        )
