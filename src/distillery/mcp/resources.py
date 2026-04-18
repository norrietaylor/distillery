"""MCP Apps ``ui://`` resource registration for Distillery skill widgets.

Each registered resource serves a built Svelte entry (``dashboard/dist/<slug>.html``)
as a self-contained HTML page.  The CSS and JS assets from ``dashboard/dist/assets/``
are inlined so the MCP client can render the UI from a single resource read.

Phase 1 registers two resources:

* ``ui://distillery/dashboard`` — legacy monolithic dashboard (to be removed).
* ``ui://distillery/recall`` — per-skill recall widget (prototype).

Phase 2 adds one resource per remaining UX-candidate skill and removes the
legacy dashboard.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Default location of dashboard build output relative to the repo root.
_DEFAULT_DIST_DIR = Path(__file__).resolve().parents[3] / "dashboard" / "dist"


def _find_dist_dir() -> Path:
    """Resolve the dashboard dist directory.

    Checks ``DISTILLERY_DASHBOARD_DIR`` env-var first, then falls back to
    the default ``dashboard/dist/`` relative to the repository root.
    """
    override = os.environ.get("DISTILLERY_DASHBOARD_DIR")
    if override:
        return Path(override)
    return _DEFAULT_DIST_DIR


def _literal_replacer(text: str) -> Callable[[re.Match[str]], str]:
    """Return a callable for ``re.sub`` that always returns *text* literally."""

    def _repl(_match: re.Match[str]) -> str:
        return text

    return _repl


def _build_inline_html(dist_dir: Path, entry: str = "index") -> str:
    """Read ``dist/<entry>.html`` and inline all CSS/JS assets.

    The Vite build produces one HTML entry per widget that references JS and
    CSS via ``<script>`` and ``<link>`` tags pointing at ``/assets/…``.  MCP
    Apps resources deliver content as a single blob, so we replace those tags
    with inline ``<style>`` and ``<script>`` blocks.

    Args:
        dist_dir: The ``dashboard/dist/`` directory.
        entry: The HTML entry stem (e.g. ``"index"``, ``"recall"``).  The
            actual file read is ``dist_dir / f"{entry}.html"``.

    Returns:
        The fully self-contained HTML string.

    Raises:
        FileNotFoundError: If the dist directory or entry HTML is missing.
    """
    entry_path = dist_dir / f"{entry}.html"
    if not entry_path.exists():
        raise FileNotFoundError(
            f"Widget entry not built: {entry_path} not found. "
            "Run 'make dashboard' to build the Svelte app."
        )

    html = entry_path.read_text(encoding="utf-8")
    assets_dir = dist_dir / "assets"

    # Inline CSS: replace <link rel="stylesheet" ... href="/assets/X.css">
    #
    # Note: the replacement argument to re.sub() is parsed for regex
    # escape sequences (\1, \g<name>, etc.), and unrecognised
    # backslash-letter sequences — including \u — raise
    # `re.PatternError: bad escape \u`. CSS and JS bundles routinely
    # contain Unicode escape sequences like `content: "\u2605"`, so
    # passing raw bundle text as a replacement string is unsafe.
    # Using a lambda as the replacement avoids escape parsing
    # entirely — the function's return value is substituted literally.
    if assets_dir.exists():
        for css_file in sorted(assets_dir.glob("*.css")):
            css_content = css_file.read_text(encoding="utf-8")
            # Replace the link tag referencing this file with an inline style block
            link_tag_fragment = css_file.name
            if link_tag_fragment in html:
                # Find the full <link> tag and replace it
                safe_css = css_content.replace("</style>", "<\\/style>")
                pattern = rf'<link[^>]*href="/assets/{re.escape(css_file.name)}"[^>]*/?\s*>'
                replacement = f"<style>{safe_css}</style>"
                html = re.sub(pattern, _literal_replacer(replacement), html, flags=re.IGNORECASE)

        # Inline JS: replace <script type="module" ... src="/assets/X.js">
        for js_file in sorted(assets_dir.glob("*.js")):
            js_content = js_file.read_text(encoding="utf-8")
            js_name = js_file.name
            if js_name in html:
                safe_js = js_content.replace("</script>", "<\\/script>")
                pattern = rf'<script[^>]*src="/assets/{re.escape(js_name)}"[^>]*>\s*</script>'
                replacement = f'<script type="module">{safe_js}</script>'
                html = re.sub(pattern, _literal_replacer(replacement), html, flags=re.IGNORECASE)

    return html


# MCP Apps UI resource marker, reused across every widget registration.
#
# We intentionally pass an empty dict as ``_meta.ui`` instead of
# ``app=True``. FastMCP's ``app=True`` sugar emits ``_meta.ui = True``
# (a JSON boolean), but the MCP Apps extension spec defines ``_meta.ui``
# on a resource as an ``McpUiResourceMeta`` *object* (see
# ``dashboard/node_modules/@modelcontextprotocol/ext-apps/dist/
# src/generated/schema.json::McpUiResourceMeta`` — ``"type": "object"``,
# ``"additionalProperties": false``, all fields optional). Hosts that
# Zod-validate the wire response reject a boolean here with::
#
#     [{"expected":"object","code":"invalid_type","path":[],
#       "message":"Invalid input"}]
#
# which manifests as a "Failed to load the MCP app / Unable to reach
# {server}" banner even though the tool call itself returns normally —
# the resource read fires before the iframe mounts. An empty object is
# a valid ``McpUiResourceMeta`` and still signals "this is an MCP App
# resource" to hosts that key off the presence of ``_meta.ui``. The
# ``text/html;profile=mcp-app`` mime type is still auto-applied by
# FastMCP's ``resolve_ui_mime_type`` because the URI starts with
# ``ui://``, so we don't lose the mime signal either.
#
# Drop this override once FastMCP ships a release where ``app=True`` on
# resources emits ``{}`` instead of ``True`` — track upstream.
_UI_META: dict[str, dict[str, object]] = {"ui": {}}


def register_widget_resource(
    server: FastMCP,
    slug: str,
    title: str,
    description: str,
    *,
    entry: str | None = None,
) -> None:
    """Register a ``ui://distillery/<slug>`` MCP Apps resource.

    The resource serves the built Svelte widget entry as inline HTML.  If the
    widget has not been built (``dashboard/dist/<entry>.html`` missing), the
    resource returns a helpful fallback page instead of raising.

    Args:
        server: The FastMCP server instance to register the resource on.
        slug: The widget slug used both in the resource URI and — unless
            ``entry`` overrides it — the Vite build entry filename.
        title: Human-readable title for the resource.
        description: One-line description of the widget.
        entry: Optional override for the Vite build entry stem.  Defaults to
            ``slug`` so ``ui://distillery/recall`` reads
            ``dashboard/dist/recall.html``.
    """
    entry_stem = entry if entry is not None else slug

    @server.resource(
        f"ui://distillery/{slug}",
        name=f"distillery_{slug}",
        title=title,
        description=description,
        meta=_UI_META,
    )
    def widget_resource() -> str:
        """Serve the widget as a self-contained HTML page."""
        try:
            return _build_inline_html(_find_dist_dir(), entry=entry_stem)
        except FileNotFoundError:
            logger.warning(
                "Widget assets not found at %s (entry=%s) — serving fallback page",
                _find_dist_dir(),
                entry_stem,
            )
            return _fallback_html(slug)


def register_dashboard_resource(server: FastMCP) -> None:
    """Register the legacy ``ui://distillery/dashboard`` resource.

    Thin compatibility wrapper around :func:`register_widget_resource` while
    the monolithic dashboard coexists with the new per-skill widgets.  Delete
    once all widgets have landed and the ``distillery_dashboard`` tool is
    retired.
    """
    register_widget_resource(
        server,
        slug="dashboard",
        title="Distillery Dashboard",
        description=(
            "Interactive knowledge-base dashboard with briefing stats, "
            "radar feed, and entry management."
        ),
    )


def _fallback_html(slug: str = "dashboard") -> str:
    """Return a minimal HTML page shown when widget assets are not built."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Distillery Widget — {slug}</title>
  <style>
    body {{
      font-family: system-ui, -apple-system, sans-serif;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0;
      background: #f9fafb; color: #374151;
    }}
    .msg {{ text-align: center; max-width: 480px; padding: 2rem; }}
    h1 {{ font-size: 1.25rem; margin-bottom: 0.5rem; }}
    p {{ color: #6b7280; }}
    code {{ background: #e5e7eb; padding: 0.125rem 0.375rem; border-radius: 0.25rem; font-size: 0.875rem; }}
  </style>
</head>
<body>
  <div class="msg">
    <h1>Widget Not Built</h1>
    <p>Run <code>make dashboard</code> in the repository root to build the <strong>{slug}</strong> widget, then reload this resource.</p>
  </div>
</body>
</html>"""
