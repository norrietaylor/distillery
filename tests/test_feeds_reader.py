"""Unit tests for the Jina Reader client (issue #403).

Covers:
  - JinaReaderClient.fetch happy path (200 returns markdown).
  - 5xx exhausted → returns None, never raises.
  - 429 with Retry-After → retries, eventually succeeds.
  - Transport error exhausted → returns None.
  - Empty response body → returns None.
  - build_reader_client returns None when API key missing.
  - Constructor input validation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from distillery.feeds.reader import JinaReaderClient, build_reader_client

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    *,
    api_key: str = "test-key",
    max_retries: int = 2,
    concurrency: int = 5,
    timeout_seconds: float = 30.0,
) -> JinaReaderClient:
    return JinaReaderClient(
        api_key=api_key,
        max_retries=max_retries,
        concurrency=concurrency,
        timeout_seconds=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Constructor / factory
# ---------------------------------------------------------------------------


class TestJinaReaderClientInit:
    def test_empty_api_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty api_key"):
            JinaReaderClient(api_key="")

    def test_zero_concurrency_rejected(self) -> None:
        with pytest.raises(ValueError, match="concurrency must be >= 1"):
            JinaReaderClient(api_key="k", concurrency=0)

    def test_negative_max_retries_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_retries must be >= 0"):
            JinaReaderClient(api_key="k", max_retries=-1)

    def test_zero_timeout_rejected(self) -> None:
        with pytest.raises(ValueError, match="timeout_seconds must be > 0"):
            JinaReaderClient(api_key="k", timeout_seconds=0)


class TestBuildReaderClient:
    def test_missing_api_key_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JINA_API_KEY", raising=False)
        assert build_reader_client() is None

    def test_empty_api_key_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JINA_API_KEY", "")
        assert build_reader_client() is None

    def test_whitespace_only_api_key_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JINA_API_KEY", "   ")
        assert build_reader_client() is None

    def test_present_api_key_returns_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JINA_API_KEY", "real-key")
        client = build_reader_client()
        assert isinstance(client, JinaReaderClient)


# ---------------------------------------------------------------------------
# fetch behaviour
# ---------------------------------------------------------------------------


class _RecordingTransport(httpx.AsyncBaseTransport):
    """An httpx transport whose responses are scripted by the test."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.calls: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if not self._responses:
            raise AssertionError("No more scripted responses")
        return self._responses.pop(0)


class _RaisingTransport(httpx.AsyncBaseTransport):
    """Transport that raises a RequestError on every call."""

    def __init__(self, exc_factory: Any) -> None:
        self._exc_factory = exc_factory
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        raise self._exc_factory()


def _patched_async_client(transport: httpx.AsyncBaseTransport) -> Any:
    """Return a context manager that replaces httpx.AsyncClient with a transport."""
    real_async_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    return patch("distillery.feeds.reader.httpx.AsyncClient", side_effect=factory)


class TestJinaReaderClientFetch:
    async def test_empty_url_returns_none(self) -> None:
        client = _make_client()
        assert await client.fetch("") is None
        assert await client.fetch("   ") is None

    async def test_happy_path_returns_body(self) -> None:
        body = "# Hello\n\nFull article body."
        transport = _RecordingTransport(
            [httpx.Response(200, text=body)],
        )
        client = _make_client(max_retries=0)
        with _patched_async_client(transport):
            result = await client.fetch("https://example.com/post")
        assert result == body
        assert len(transport.calls) == 1
        # Verify auth + accept headers
        request = transport.calls[0]
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["Accept"] == "text/plain"
        # Verify the URL is appended (URL-encoded)
        assert "example.com" in str(request.url)

    async def test_empty_body_returns_none(self) -> None:
        transport = _RecordingTransport([httpx.Response(200, text="")])
        client = _make_client(max_retries=0)
        with _patched_async_client(transport):
            assert await client.fetch("https://example.com/post") is None

    async def test_whitespace_only_body_returns_none(self) -> None:
        transport = _RecordingTransport([httpx.Response(200, text="   \n  ")])
        client = _make_client(max_retries=0)
        with _patched_async_client(transport):
            assert await client.fetch("https://example.com/post") is None

    async def test_non_retryable_4xx_returns_none(self) -> None:
        transport = _RecordingTransport([httpx.Response(404, text="not found")])
        client = _make_client(max_retries=2)
        with _patched_async_client(transport):
            result = await client.fetch("https://example.com/post")
        assert result is None
        # No retries on 404.
        assert len(transport.calls) == 1

    async def test_5xx_exhausted_returns_none(self) -> None:
        # 3 attempts (initial + max_retries=2) all 503.
        transport = _RecordingTransport(
            [
                httpx.Response(503, text="busy"),
                httpx.Response(503, text="busy"),
                httpx.Response(503, text="busy"),
            ],
        )
        client = _make_client(max_retries=2)
        with (
            _patched_async_client(transport),
            patch("distillery.feeds.reader.asyncio.sleep") as mock_sleep,
        ):
            mock_sleep.return_value = None
            result = await client.fetch("https://example.com/post")
        assert result is None
        assert len(transport.calls) == 3

    async def test_429_retry_then_success(self) -> None:
        transport = _RecordingTransport(
            [
                httpx.Response(429, headers={"Retry-After": "1"}, text=""),
                httpx.Response(200, text="content"),
            ],
        )
        client = _make_client(max_retries=2)
        with (
            _patched_async_client(transport),
            patch("distillery.feeds.reader.asyncio.sleep") as mock_sleep,
        ):
            mock_sleep.return_value = None
            result = await client.fetch("https://example.com/post")
            # Retry-After honored: first sleep call uses 1.0s.
            assert mock_sleep.await_args_list[0].args[0] == 1.0
        assert result == "content"
        assert len(transport.calls) == 2

    async def test_transport_error_exhausted_returns_none(self) -> None:
        transport = _RaisingTransport(lambda: httpx.ConnectError("boom"))
        client = _make_client(max_retries=2)
        with (
            _patched_async_client(transport),
            patch("distillery.feeds.reader.asyncio.sleep") as mock_sleep,
        ):
            mock_sleep.return_value = None
            result = await client.fetch("https://example.com/post")
        assert result is None
        assert transport.call_count == 3  # initial + 2 retries

    async def test_transport_error_then_success(self) -> None:
        # First call raises, second succeeds.
        call_state = {"count": 0}
        success_response = httpx.Response(200, text="recovered")

        class _IntermittentTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                call_state["count"] += 1
                if call_state["count"] == 1:
                    raise httpx.ConnectError("transient")
                return success_response

        client = _make_client(max_retries=2)
        with (
            _patched_async_client(_IntermittentTransport()),
            patch("distillery.feeds.reader.asyncio.sleep") as mock_sleep,
        ):
            mock_sleep.return_value = None
            result = await client.fetch("https://example.com/post")
        assert result == "recovered"
        assert call_state["count"] == 2

    async def test_max_retries_zero_no_retry(self) -> None:
        transport = _RecordingTransport([httpx.Response(503, text="busy")])
        client = _make_client(max_retries=0)
        with _patched_async_client(transport):
            result = await client.fetch("https://example.com/post")
        assert result is None
        assert len(transport.calls) == 1
