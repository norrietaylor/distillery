"""ASGI middleware for the Distillery HTTP transport.

Provides per-IP sliding-window rate limiting, request body size limiting,
and GitHub org membership enforcement for the FastMCP HTTP server.  All
middleware classes follow the standard ASGI 3.0 interface and are compatible
with Starlette's middleware stack.

Neither middleware applies to the stdio transport — they are only wired in
when ``--transport http`` is selected.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from distillery.mcp.types import AuditCallback

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from distillery.mcp.org_membership import OrgMembershipChecker

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


def _client_ip(scope: Scope, *, trust_proxy: bool = False) -> str:
    """Extract client IP from ASGI scope, falling back to ``'unknown'``.

    Args:
        scope: The ASGI connection scope.
        trust_proxy: When ``True`` (e.g. behind Fly.io / nginx), prefer the
            ``X-Forwarded-For`` header over ``scope["client"]``.  Must only be
            enabled when the app is behind a trusted reverse proxy.
    """
    if trust_proxy:
        headers = Headers(scope=scope)
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            return str(forwarded).split(",")[0].strip()

    client = scope.get("client")
    if client and isinstance(client, (list, tuple)) and len(client) >= 1:
        return str(client[0])

    if not trust_proxy:
        headers = Headers(scope=scope)
        forwarded = headers.get("x-forwarded-for")
        if forwarded:
            return str(forwarded).split(",")[0].strip()

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
        trust_proxy: Prefer ``X-Forwarded-For`` for client IP extraction.
        loopback_exempt: When ``True`` (default), skip rate limiting for
            requests originating from loopback addresses (``127.0.0.1``,
            ``::1``, ``localhost``).
    """

    _LOOPBACK_ADDRS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

    def __init__(
        self,
        app: ASGIApp,
        requests_per_minute: int = 60,
        requests_per_hour: int = 600,
        trust_proxy: bool = False,
        loopback_exempt: bool = True,
    ) -> None:
        self.app = app
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.trust_proxy = trust_proxy
        self.loopback_exempt = loopback_exempt
        # ip -> _IPWindow.  In-memory state; resets on process restart.
        self._windows: dict[str, _IPWindow] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Loopback exemption: use the raw ASGI peer address (scope["client"])
        # directly — never trust _client_ip() here, because it may fall back
        # to X-Forwarded-For which can be spoofed.
        if self.loopback_exempt:
            client = scope.get("client")
            if client and isinstance(client, (list, tuple)) and len(client) >= 1:
                peer_ip = str(client[0])
                if peer_ip in self._LOOPBACK_ADDRS:
                    await self.app(scope, receive, send)
                    return

        ip = _client_ip(scope, trust_proxy=self.trust_proxy)

        now = time.monotonic()

        was_existing = ip in self._windows
        window = self._windows.get(ip)
        if window is None:
            window = _IPWindow()
            self._windows[ip] = window

        window.prune(now)

        # Evict idle buckets to prevent unbounded memory growth — but only
        # for IPs that already had a window (not brand-new ones).
        if was_existing and window.count_minute() == 0 and window.count_hour() == 0:
            del self._windows[ip]
            # Create a fresh window so record() below persists this request.
            window = _IPWindow()
            self._windows[ip] = window

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
            message: _State = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        response_started = False

        async def _tracking_send(message: _State) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, _limited_receive, _tracking_send)
        except _BodyTooLargeError:
            if not response_started:
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
# RequestIDMiddleware
# ---------------------------------------------------------------------------


class RequestIDMiddleware:
    """ASGI middleware that propagates ``X-Request-ID`` for request tracing.

    Reads the ``X-Request-ID`` header from the incoming request.  If absent,
    generates a new UUID4.  The resolved ID is then echoed back in the
    ``X-Request-ID`` response header and logged at DEBUG level, enabling
    correlation of multi-step MCP workflows across log lines.

    Args:
        app: The wrapped ASGI application.
    """

    HEADER = b"x-request-id"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or str(uuid.uuid4())
        logger.debug("request_id=%s path=%s", request_id, scope.get("path", ""))

        request_id_bytes = request_id.encode()

        async def _send_with_id(message: _State) -> None:
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                existing.append((self.HEADER, request_id_bytes))
                message = dict(message, headers=existing)
            await send(message)

        await self.app(scope, receive, _send_with_id)


# ---------------------------------------------------------------------------
# OrgMembershipMiddleware
# ---------------------------------------------------------------------------


class OrgMembershipMiddleware:
    """ASGI middleware that enforces GitHub org membership for MCP requests.

    OAuth-related paths (``/oauth/``, ``/.well-known/``) are always passed
    through so that the auth flow itself is never blocked.  Requests without
    an ``Authorization: Bearer`` header are also passed through — FastMCP
    will reject them with 401 anyway.

    For requests bearing a JWT access token, the middleware decodes the JWT
    payload (without re-verifying the signature — FastMCP already did that)
    to extract the ``login`` claim and then calls
    :meth:`~distillery.mcp.org_membership.OrgMembershipChecker.is_allowed`.
    Non-members receive a JSON 403 response with a clear error message.

    If the token is not a JWT (e.g. an opaque token) or the JWT does not
    contain a ``login``/``sub`` claim, the middleware rejects the request
    with a 403 (fail-closed) rather than passing it through unenforced.

    Args:
        app: The wrapped ASGI application.
        checker: Configured :class:`~distillery.mcp.org_membership.OrgMembershipChecker`.
    """

    # Paths that handle the OAuth dance — never block these.
    _OAUTH_PREFIXES = (
        "/oauth/",
        "/.well-known/",
        "/mcp/auth",
    )

    def __init__(
        self,
        app: ASGIApp,
        checker: OrgMembershipChecker,
        audit_callback: AuditCallback | None = None,
    ) -> None:
        self.app = app
        self.checker = checker
        self._audit_callback = audit_callback

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.checker.enabled:
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if any(path.startswith(p) for p in self._OAUTH_PREFIXES):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            # No bearer token — pass through; FastMCP will issue 401.
            await self.app(scope, receive, send)
            return

        bearer_token = auth[7:]

        # Attempt to decode the JWT to get the GitHub login claim.
        # FastMCP 3.x may include GitHub identity claims in the JWT payload.
        from distillery.mcp.org_membership import _try_decode_jwt_claims

        claims = _try_decode_jwt_claims(bearer_token)
        if claims:
            raw = claims.get("login") or claims.get("sub") or ""
            username = raw.strip() if isinstance(raw, str) else ""
            if username:
                if not await self.checker.is_allowed(username):
                    await self._audit_org_denied(username)
                    await self._send_403(send, username, list(self.checker.allowed_orgs))
                    return
                await self.app(scope, receive, send)
                return

        # Cannot identify the user (opaque token or JWT without
        # login/sub claim) — fail closed.
        await self._audit_org_denied("<unknown>")
        await self._send_403(send, "<unknown>", list(self.checker.allowed_orgs))

    async def _audit_org_denied(self, username: str) -> None:
        """Fire the audit callback when a user is denied by org membership check.

        Emits a best-effort audit log entry with operation ``auth_org_denied``.
        Exceptions from the callback are caught and logged at DEBUG level so
        that audit infrastructure issues never block the 403 response.

        Args:
            username: GitHub login of the denied user, or ``"<unknown>"``
                when the JWT does not contain an identifiable claim.
        """
        if self._audit_callback is None:
            return
        try:
            await self._audit_callback(username, "auth_org_denied", "", "auth_org_denied", "denied")
        except Exception:  # noqa: BLE001
            logger.debug("org-denied audit_log write failed (ignored)", exc_info=True)

    @staticmethod
    async def _send_403(send: Send, username: str, orgs: list[str]) -> None:
        org_list = ", ".join(f"'{o}'" for o in orgs)
        body = json.dumps(
            {
                "error": "forbidden",
                "message": (
                    f"User '{username}' is not a member of any required GitHub org. "
                    f"Must be a member of at least one of: {org_list}."
                ),
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def apply_http_middleware(
    app: ASGIApp,
    requests_per_minute: int = 60,
    requests_per_hour: int = 600,
    max_body_bytes: int = 1_048_576,
    trust_proxy: bool = False,
    loopback_exempt: bool = True,
    org_checker: OrgMembershipChecker | None = None,
    audit_callback: AuditCallback | None = None,
) -> ASGIApp:
    """Wrap *app* with rate-limit, body-size, request-ID, and org-membership middleware.

    Middleware is applied in outermost-to-innermost order:
    1. :class:`RequestIDMiddleware` (outermost — echoes ``X-Request-ID`` on
       *all* responses, including 429/403/413 rejections)
    2. :class:`RateLimitMiddleware` (counts every request so denied requests
       still consume quota)
    3. :class:`OrgMembershipMiddleware` (when *org_checker* is provided and
       enabled — blocks non-members before body is read)
    4. :class:`BodySizeLimitMiddleware` (innermost — rejects oversized bodies)

    Args:
        app: The ASGI application to wrap.
        requests_per_minute: Per-IP minute limit (default 60).
        requests_per_hour: Per-IP hour limit (default 600).
        max_body_bytes: Maximum body size in bytes (default 1 MB).
        trust_proxy: Prefer ``X-Forwarded-For`` for client IP extraction.
        loopback_exempt: Skip rate limiting for loopback IPs (default ``True``).
        org_checker: Optional org membership checker.  When provided and
            :attr:`~distillery.mcp.org_membership.OrgMembershipChecker.enabled`
            is ``True``, :class:`OrgMembershipMiddleware` is added.
        audit_callback: Optional async callback for writing audit log entries
            when org membership checks deny access.  Signature:
            ``(user_id, operation, entry_id, action, outcome) -> Awaitable[None]``.

    Returns:
        A new ASGI app with all requested middleware layers applied.
    """
    app = BodySizeLimitMiddleware(app, max_bytes=max_body_bytes)
    if org_checker is not None and org_checker.enabled:
        app = OrgMembershipMiddleware(app, org_checker, audit_callback=audit_callback)
    app = RateLimitMiddleware(
        app,
        requests_per_minute=requests_per_minute,
        requests_per_hour=requests_per_hour,
        trust_proxy=trust_proxy,
        loopback_exempt=loopback_exempt,
    )
    app = RequestIDMiddleware(app)
    return app
