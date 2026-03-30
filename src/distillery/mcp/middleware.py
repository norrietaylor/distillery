"""ASGI middleware for the Distillery HTTP transport.

Provides per-IP sliding-window rate limiting and request body size limiting
for the FastMCP HTTP server.  Both middleware classes follow the standard
ASGI 3.0 interface and are compatible with Starlette's middleware stack.

Neither middleware applies to the stdio transport — they are only wired in
when ``--transport http`` is selected.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import MutableMapping
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

_State = MutableMapping[str, Any]

# ---------------------------------------------------------------------------
# Sliding-window rate limiter state
# ---------------------------------------------------------------------------


class _IPWindow:
    """Per-IP sliding-window counters for minute and hour buckets."""

    __slots__ = ("minute_times", "hour_times")

    def __init__(self) -> None:
        self.minute_times: deque[float] = deque()
        self.hour_times: deque[float] = deque()

    def record(self, now: float) -> None:
        """Record a new request at *now*."""
        self.minute_times.append(now)
        self.hour_times.append(now)

    def prune(self, now: float) -> None:
        """Remove timestamps older than 1 minute / 1 hour."""
        minute_cutoff = now - 60.0
        while self.minute_times and self.minute_times[0] < minute_cutoff:
            self.minute_times.popleft()
        hour_cutoff = now - 3600.0
        while self.hour_times and self.hour_times[0] < hour_cutoff:
            self.hour_times.popleft()

    def count_minute(self) -> int:
        return len(self.minute_times)

    def count_hour(self) -> int:
        return len(self.hour_times)

    def retry_after_minute(self, now: float) -> int:
        """Seconds until the oldest minute-bucket entry expires."""
        if not self.minute_times:
            return 1
        return max(1, int(self.minute_times[0] + 60.0 - now) + 1)

    def retry_after_hour(self, now: float) -> int:
        """Seconds until the oldest hour-bucket entry expires."""
        if not self.hour_times:
            return 1
        return max(1, int(self.hour_times[0] + 3600.0 - now) + 1)


def _client_ip(scope: Scope) -> str:
    """Extract client IP from ASGI scope, falling back to ``'unknown'``."""
    client = scope.get("client")
    if client and isinstance(client, (list, tuple)) and len(client) >= 1:
        return str(client[0])
    # Check X-Forwarded-For header (set by reverse proxies).
    headers = Headers(scope=scope)
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return "unknown"


# ---------------------------------------------------------------------------
# RateLimitMiddleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware:
    """ASGI middleware that enforces per-IP sliding-window rate limits.

    Responds with HTTP 429 (Too Many Requests) and a ``Retry-After`` header
    when either the per-minute or per-hour threshold is exceeded.

    Args:
        app: The wrapped ASGI application.
        requests_per_minute: Maximum requests per IP per 60-second window.
        requests_per_hour: Maximum requests per IP per 3600-second window.
    """

    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 60,
        requests_per_hour: int = 600,
    ) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        # ip -> _IPWindow.  In-memory state; resets on process restart.
        self._windows: dict[str, _IPWindow] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        ip = _client_ip(scope)
        now = time.monotonic()

        window = self._windows.get(ip)
        if window is None:
            window = _IPWindow()
            self._windows[ip] = window

        window.prune(now)

        minute_count = window.count_minute()
        hour_count = window.count_hour()

        if minute_count >= self.requests_per_minute:
            retry_after = window.retry_after_minute(now)
            await self._send_429(send, retry_after)
            return

        if hour_count >= self.requests_per_hour:
            retry_after = window.retry_after_hour(now)
            await self._send_429(send, retry_after)
            return

        window.record(now)
        await self.app(scope, receive, send)

    @staticmethod
    async def _send_429(send: Send, retry_after: int) -> None:
        body = b'{"error": "Too Many Requests", "retry_after": ' + str(retry_after).encode() + b"}"
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(retry_after).encode()),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# BodySizeLimitMiddleware
# ---------------------------------------------------------------------------


class BodySizeLimitMiddleware:
    """ASGI middleware that rejects requests whose body exceeds *max_bytes*.

    Responds with HTTP 413 (Payload Too Large) when the ``Content-Length``
    header exceeds the limit, or when the cumulative body bytes streamed
    through ``receive`` exceed the limit.

    Args:
        app: The wrapped ASGI application.
        max_bytes: Maximum request body size in bytes (default: 1 MB).
    """

    def __init__(self, app: ASGIApp, max_bytes: int = 1_048_576) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast-path: reject based on Content-Length header alone.
        headers = Headers(scope=scope)
        content_length_raw = headers.get("content-length")
        if content_length_raw is not None:
            try:
                content_length = int(content_length_raw)
            except ValueError:
                content_length = 0
            if content_length > self.max_bytes:
                await self._send_413(send)
                return

        # Slow-path: count bytes as they stream in.
        total: int = 0

        async def _limited_receive() -> _State:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        try:
            await self.app(scope, _limited_receive, send)
        except _BodyTooLargeError:
            await self._send_413(send)

    @staticmethod
    async def _send_413(send: Send) -> None:
        body = b'{"error": "Payload Too Large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _BodyTooLargeError(Exception):
    """Internal sentinel raised when the body size limit is exceeded."""


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def apply_http_middleware(
    app: ASGIApp,
    requests_per_minute: int = 60,
    requests_per_hour: int = 600,
    max_body_bytes: int = 1_048_576,
) -> ASGIApp:
    """Wrap *app* with body-size and rate-limit middleware.

    Middleware is applied in outermost-to-innermost order:
    1. :class:`BodySizeLimitMiddleware` (outermost — reject oversized bodies first)
    2. :class:`RateLimitMiddleware` (innermost — count only body-OK requests)

    Args:
        app: The ASGI application to wrap.
        requests_per_minute: Per-IP minute limit (default 60).
        requests_per_hour: Per-IP hour limit (default 600).
        max_body_bytes: Maximum body size in bytes (default 1 MB).

    Returns:
        A new ASGI app with both middleware layers applied.
    """
    app = RateLimitMiddleware(
        app,
        requests_per_minute=requests_per_minute,
        requests_per_hour=requests_per_hour,
    )
    app = BodySizeLimitMiddleware(app, max_bytes=max_body_bytes)
    return app
