"""MCP Apps ``ui://`` resource registration for the Distillery dashboard.

Registers a ``ui://distillery/dashboard`` resource that serves the built
Svelte dashboard as a self-contained HTML page.  The CSS and JS assets from
``dashboard/dist/`` are inlined into the HTML so the MCP client can render
the entire UI from a single resource read.
"""

from __future__ import annotations

import logging
import os
import re
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


def _build_inline_html(dist_dir: Path) -> str:
    """Read ``dist/index.html`` and inline all CSS/JS assets.

    The Vite build produces an ``index.html`` that references JS and CSS via
    ``<script>`` and ``<link>`` tags pointing at ``/assets/…``.  MCP Apps
    resources deliver content as a single blob, so we replace those tags with
    inline ``<style>`` and ``<script>`` blocks.

    Returns the fully self-contained HTML string.

    Raises:
        FileNotFoundError: If the dist directory or index.html is missing.
    """
    index_path = dist_dir / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(
            f"Dashboard not built: {index_path} not found. "
            "Run 'make dashboard' to build the Svelte app."
        )

    html = index_path.read_text(encoding="utf-8")
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
                html = re.sub(pattern, lambda _m, r=replacement: r, html, flags=re.IGNORECASE)

        # Inline JS: replace <script type="module" ... src="/assets/X.js">
        for js_file in sorted(assets_dir.glob("*.js")):
            js_content = js_file.read_text(encoding="utf-8")
            js_name = js_file.name
            if js_name in html:
                safe_js = js_content.replace("</script>", "<\\/script>")
                pattern = rf'<script[^>]*src="/assets/{re.escape(js_name)}"[^>]*>\s*</script>'
                replacement = f'<script type="module">{safe_js}</script>'
                html = re.sub(pattern, lambda _m, r=replacement: r, html, flags=re.IGNORECASE)

    return html


def register_dashboard_resource(server: FastMCP) -> None:
    """Register the ``ui://distillery/dashboard`` MCP Apps resource.

    The resource serves the built Svelte dashboard as inline HTML.  If the
    dashboard has not been built (``dashboard/dist/`` missing), the resource
    returns a helpful error page instead of raising.

    Args:
        server: The FastMCP server instance to register the resource on.
    """

    @server.resource(
        "ui://distillery/dashboard",
        name="distillery_dashboard",
        title="Distillery Dashboard",
        description="Interactive knowledge-base dashboard with briefing stats, radar feed, and entry management.",
        app=True,
    )
    def dashboard_resource() -> str:
        """Serve the Distillery dashboard as a self-contained HTML page."""
        try:
            dist_dir = _find_dist_dir()
            return _build_inline_html(dist_dir)
        except FileNotFoundError:
            logger.warning(
                "Dashboard assets not found at %s — serving fallback page",
                _find_dist_dir(),
            )
            return _fallback_html()


def _fallback_html() -> str:
    """Return a minimal HTML page shown when dashboard assets are not built."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Distillery Dashboard</title>
  <style>
    body {
      font-family: system-ui, -apple-system, sans-serif;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0;
      background: #f9fafb; color: #374151;
    }
    .msg { text-align: center; max-width: 480px; padding: 2rem; }
    h1 { font-size: 1.25rem; margin-bottom: 0.5rem; }
    p { color: #6b7280; }
    code { background: #e5e7eb; padding: 0.125rem 0.375rem; border-radius: 0.25rem; font-size: 0.875rem; }
  </style>
</head>
<body>
  <div class="msg">
    <h1>Dashboard Not Built</h1>
    <p>Run <code>make dashboard</code> in the repository root to build the Svelte frontend, then reload this resource.</p>
  </div>
</body>
</html>"""
