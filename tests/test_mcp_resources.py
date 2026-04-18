"""Tests for ``ui://`` resource registration (MCP Apps widgets).

Verifies that each registered widget resource returns self-contained HTML (or
the fallback page when the Vite build has not run), and that the companion
tool-to-resource binding is wired via ``meta.ui.resourceUri``.
"""

from __future__ import annotations

import re

import pytest

from distillery.config import DistilleryConfig, EmbeddingConfig, StorageConfig
from distillery.mcp.server import create_server

# (slug, expected_tool_name) pairs — extend as new widgets are added.
_WIDGET_TOOL_BINDINGS: list[tuple[str, str]] = [
    ("dashboard", "distillery_dashboard"),
    ("recall", "distillery_recall"),
]


def _make_config() -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
    )


@pytest.mark.parametrize(("slug", "_tool"), _WIDGET_TOOL_BINDINGS)
async def test_widget_resource_registered(slug: str, _tool: str) -> None:
    """Each widget slug must be registered as ``ui://distillery/<slug>``."""
    server = create_server(_make_config())
    resources = await server.list_resources()
    uris = {str(r.uri) for r in resources}
    assert f"ui://distillery/{slug}" in uris, (
        f"ui://distillery/{slug} not registered. Got: {sorted(uris)}"
    )


@pytest.mark.parametrize(("slug", "_tool"), _WIDGET_TOOL_BINDINGS)
async def test_widget_resource_returns_html(slug: str, _tool: str) -> None:
    """Reading a widget resource must return an HTML document.

    When the Vite build has not run (``dashboard/dist/<slug>.html`` missing),
    the resource returns a fallback page — still valid HTML.
    """
    server = create_server(_make_config())
    raw_list = await server.read_resource(f"ui://distillery/{slug}")
    # ``read_resource`` returns a list of ReadResourceContents with .content.
    if isinstance(raw_list, list):
        raw = raw_list[0].content if raw_list else ""
    elif hasattr(raw_list, "contents"):
        raw = raw_list.contents[0].content
    else:
        raw = str(raw_list)
    assert isinstance(raw, str)
    assert raw.lstrip().lower().startswith("<!doctype html>")
    # Self-contained: no unresolved references to built asset files. The
    # fallback page has no /assets/ references either, so this holds in both
    # built and unbuilt modes.
    unresolved = re.findall(r'["\'](/assets/[^"\']+)["\']', raw)
    assert not unresolved, (
        f"{slug} resource has unresolved asset references: {unresolved}"
    )


@pytest.mark.parametrize(("slug", "tool"), _WIDGET_TOOL_BINDINGS)
async def test_widget_tool_binds_resource_uri(slug: str, tool: str) -> None:
    """Each widget-bound tool must advertise ``meta.ui.resourceUri``."""
    server = create_server(_make_config())
    function_tool = await server.get_tool(tool)
    assert function_tool is not None, f"tool {tool} not registered"
    meta = getattr(function_tool, "meta", None) or {}
    ui = meta.get("ui") if isinstance(meta, dict) else None
    assert isinstance(ui, dict), f"{tool} missing meta.ui object; got meta={meta!r}"
    assert ui.get("resourceUri") == f"ui://distillery/{slug}", (
        f"{tool} meta.ui.resourceUri mismatch: {ui!r}"
    )
