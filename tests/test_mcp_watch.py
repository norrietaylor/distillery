"""Tests for the URL validation and reachability probe in distillery_watch.

Covers the fix for issue #308: the ``distillery_watch(action="add", ...)``
handler must reject syntactically invalid URLs and warn when a URL is
unreachable, rather than silently persisting a broken source.

Structure mirrors the rest of the MCP unit-test suite:
  - ``FakeSourceStore`` holds sources in memory.
  - ``pytest-httpx``'s ``httpx_mock`` fixture controls probe responses.
  - Probe behaviour is exercised directly through ``_handle_watch``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from distillery.mcp.tools.feeds import _handle_watch

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeSourceStore:
    """In-memory feed source store used by the watch handler tests."""

    def __init__(self) -> None:
        self._sources: list[dict[str, Any]] = []

    async def list_feed_sources(self) -> list[dict[str, Any]]:
        return list(self._sources)

    async def add_feed_source(
        self,
        url: str,
        source_type: str,
        label: str = "",
        poll_interval_minutes: int = 60,
        trust_weight: float = 1.0,
    ) -> dict[str, Any]:
        if any(s["url"] == url for s in self._sources):
            raise ValueError(f"Feed source with URL {url!r} already exists.")
        entry: dict[str, Any] = {
            "url": url,
            "source_type": source_type,
            "label": label,
            "poll_interval_minutes": poll_interval_minutes,
            "trust_weight": trust_weight,
        }
        self._sources.append(entry)
        return entry

    async def remove_feed_source(self, url: str) -> bool:
        before = len(self._sources)
        self._sources = [s for s in self._sources if s["url"] != url]
        return len(self._sources) < before


def _parse(result: list[Any]) -> dict[str, Any]:
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# URL syntax validation
# ---------------------------------------------------------------------------


class TestInvalidUrlRejected:
    """Syntactically invalid URLs must return INVALID_URL without persisting."""

    async def test_missing_scheme_returns_invalid_url(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "not-a-url",
                "source_type": "rss",
                "probe": False,
            },
        )
        data = _parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_URL"
        assert await store.list_feed_sources() == []

    async def test_ftp_scheme_returns_invalid_url(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "ftp://example.com/feed",
                "source_type": "rss",
                "probe": False,
            },
        )
        data = _parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_URL"
        assert await store.list_feed_sources() == []

    async def test_missing_host_returns_invalid_url(self) -> None:
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://",
                "source_type": "rss",
                "probe": False,
            },
        )
        data = _parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_URL"

    async def test_github_bare_slug_accepted(self) -> None:
        """GitHub adapter accepts owner/repo slugs; probe is skipped."""
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "owner/repo",
                "source_type": "github",
            },
        )
        data = _parse(result)
        assert "error" not in data
        assert data["added"]["url"] == "owner/repo"

    async def test_rss_bare_slug_rejected(self) -> None:
        """A slug is not a URL for RSS sources."""
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "owner/repo",
                "source_type": "rss",
                "probe": False,
            },
        )
        data = _parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_URL"


# ---------------------------------------------------------------------------
# Reachability probe
# ---------------------------------------------------------------------------


class TestReachabilityProbe:
    """When probe=True (default) an unreachable URL must not persist."""

    async def test_reachable_url_persists(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(method="HEAD", url="https://example.com/rss", status_code=200)
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
            },
        )
        data = _parse(result)
        assert "error" not in data
        assert data["added"]["url"] == "https://example.com/rss"
        assert len(await store.list_feed_sources()) == 1

    async def test_unreachable_url_returns_warning_and_does_not_persist(
        self, httpx_mock: HTTPXMock
    ) -> None:
        # ConnectError is raised for both HEAD and the GET fallback.
        httpx_mock.add_exception(httpx.ConnectError("host not found"))
        httpx_mock.add_exception(httpx.ConnectError("host not found"))
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://this-domain-does-not-exist-xyz123.example",
                "source_type": "rss",
            },
        )
        data = _parse(result)
        assert data["error"] is True
        assert data["code"] == "UNREACHABLE_URL"
        assert "last_error" in data.get("details", {})
        assert await store.list_feed_sources() == []

    async def test_server_error_status_returns_unreachable(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(method="HEAD", url="https://example.com/rss", status_code=503)
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
            },
        )
        data = _parse(result)
        assert data["error"] is True
        assert data["code"] == "UNREACHABLE_URL"
        assert await store.list_feed_sources() == []

    async def test_head_fallback_to_get(self, httpx_mock: HTTPXMock) -> None:
        """Some hosts 405 HEAD; the handler falls back to GET."""
        httpx_mock.add_exception(
            httpx.HTTPStatusError(
                "Method Not Allowed",
                request=httpx.Request("HEAD", "https://example.com/rss"),
                response=httpx.Response(405),
            ),
            method="HEAD",
        )
        httpx_mock.add_response(method="GET", url="https://example.com/rss", status_code=200)
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://example.com/rss",
                "source_type": "rss",
            },
        )
        data = _parse(result)
        assert "error" not in data
        assert len(await store.list_feed_sources()) == 1

    async def test_probe_false_skips_probe(self) -> None:
        """Passing probe=False must not trigger any HTTP call."""
        store = FakeSourceStore()
        # No httpx_mock fixture: if the handler probed, pytest-httpx's default
        # strict mode would not matter here because no httpx call is made.
        with patch(
            "distillery.mcp.tools.feeds._probe_url",
            side_effect=AssertionError("probe must not run"),
        ):
            result = await _handle_watch(
                store=store,
                arguments={
                    "action": "add",
                    "url": "https://example.com/rss",
                    "source_type": "rss",
                    "probe": False,
                },
            )
        data = _parse(result)
        assert "error" not in data
        assert len(await store.list_feed_sources()) == 1

    async def test_force_persists_despite_probe_failure(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.ConnectError("host not found"))
        httpx_mock.add_exception(httpx.ConnectError("host not found"))
        store = FakeSourceStore()
        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "https://dead.example",
                "source_type": "rss",
                "force": True,
            },
        )
        data = _parse(result)
        assert "error" not in data
        assert data["added"]["url"] == "https://dead.example"
        assert len(await store.list_feed_sources()) == 1

    async def test_github_slug_skips_probe(self) -> None:
        """GitHub owner/repo slugs are not URLs and must not be probed."""
        store = FakeSourceStore()
        with patch(
            "distillery.mcp.tools.feeds._probe_url",
            side_effect=AssertionError("probe must not run for github slug"),
        ):
            result = await _handle_watch(
                store=store,
                arguments={
                    "action": "add",
                    "url": "owner/repo",
                    "source_type": "github",
                },
            )
        data = _parse(result)
        assert "error" not in data
        assert len(await store.list_feed_sources()) == 1
