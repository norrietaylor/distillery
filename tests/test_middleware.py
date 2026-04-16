"""Unit tests for ASGI middleware classes in distillery.mcp.middleware.

Covers:
  - RateLimitMiddleware: per-IP sliding-window rate limiting, per-minute and
    per-hour windows, sliding window expiry, independent per-IP tracking,
    rate limit enforcement with 429 + Retry-After, non-HTTP scope passthrough
  - BodySizeLimitMiddleware: requests within limit pass through, oversized
    requests via Content-Length receive 413, oversized streaming bodies receive
    413, exact boundary conditions, non-HTTP scope passthrough
  - OrgMembershipMiddleware: valid org member passes, non-member rejected 403,
    missing/no-bearer auth passthrough, OAuth path bypass, GitHub API error
    handling, caching behaviour, disabled checker passthrough, non-HTTP scope
    passthrough, opaque token fail-closed
  - RequestIDMiddleware: echoes/generates X-Request-ID on responses
  - apply_http_middleware: composition of all middleware layers
  - _client_ip: extraction from scope client, X-Forwarded-For, trust_proxy
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from distillery.mcp.middleware import (
    BodySizeLimitMiddleware,
    OrgMembershipMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    _client_ip,
    apply_http_middleware,
)
from distillery.mcp.org_membership import OrgMembershipChecker

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scope(
    path: str = "/mcp",
    client: tuple[str, int] | None = ("127.0.0.1", 12345),
    headers: list[tuple[bytes, bytes]] | None = None,
    scope_type: str = "http",
) -> dict[str, Any]:
    """Build a minimal ASGI scope dict."""
    scope: dict[str, Any] = {
        "type": scope_type,
        "path": path,
        "headers": headers or [],
    }
    if client is not None:
        scope["client"] = client
    return scope


class _ResponseCapture:
    """Collect ASGI send() messages for assertions."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return m["status"]  # type: ignore[no-any-return]
        raise AssertionError("No http.response.start message found")

    @property
    def headers(self) -> dict[str, str]:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return {k.decode(): v.decode() for k, v in m.get("headers", [])}
        return {}

    @property
    def body(self) -> bytes:
        parts = []
        for m in self.messages:
            if m["type"] == "http.response.body":
                parts.append(m.get("body", b""))
        return b"".join(parts)

    @property
    def json(self) -> dict[str, Any]:
        return json.loads(self.body)  # type: ignore[no-any-return]


async def _dummy_app(scope: Any, receive: Any, send: Any) -> None:
    """Minimal ASGI app that responds 200 OK."""
    body = b'{"ok": true}'
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _body_reading_app(scope: Any, receive: Any, send: Any) -> None:
    """ASGI app that reads the full request body before responding."""
    body_parts = []
    while True:
        message = await receive()
        body_parts.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    total = sum(len(p) for p in body_parts)
    resp = json.dumps({"bytes_read": total}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(resp)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": resp})


async def _noop_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


def _make_jwt(claims: dict[str, Any]) -> str:
    """Build a fake JWT (header.payload.signature) with given claims."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
    sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}.{sig.decode()}"


# ===================================================================
# RateLimitMiddleware
# ===================================================================


class TestRateLimitMiddleware:
    """Tests for RateLimitMiddleware."""

    async def test_allows_requests_within_per_minute_limit(self) -> None:
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=5, requests_per_hour=100)
        for _ in range(5):
            cap = _ResponseCapture()
            await mw(_make_scope(), _noop_receive, cap)
            assert cap.status == 200

    async def test_rejects_exceeding_per_minute_limit(self) -> None:
        mw = RateLimitMiddleware(
            _dummy_app, requests_per_minute=3, requests_per_hour=100, loopback_exempt=False
        )
        # Use up quota
        for _ in range(3):
            cap = _ResponseCapture()
            await mw(_make_scope(), _noop_receive, cap)
            assert cap.status == 200

        # Next request should be rejected
        cap = _ResponseCapture()
        await mw(_make_scope(), _noop_receive, cap)
        assert cap.status == 429
        assert "retry-after" in cap.headers
        retry_after = int(cap.headers["retry-after"])
        assert retry_after > 0
        body = cap.json
        assert body["error"] == "Too Many Requests"
        assert body["retry_after"] > 0

    async def test_rejects_exceeding_per_hour_limit(self) -> None:
        mw = RateLimitMiddleware(
            _dummy_app, requests_per_minute=100, requests_per_hour=3, loopback_exempt=False
        )
        for _ in range(3):
            cap = _ResponseCapture()
            await mw(_make_scope(), _noop_receive, cap)
            assert cap.status == 200

        cap = _ResponseCapture()
        await mw(_make_scope(), _noop_receive, cap)
        assert cap.status == 429

    async def test_sliding_window_expires_old_counts(self) -> None:
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=2, requests_per_hour=100)
        ip = "10.0.0.1"
        scope = _make_scope(client=(ip, 1234))

        # Fill up the minute window
        for _ in range(2):
            cap = _ResponseCapture()
            await mw(scope, _noop_receive, cap)
            assert cap.status == 200

        # Should be rate-limited now
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 429

        # Simulate time passing (> 60 seconds) by manipulating the window
        window = mw._windows[ip]
        old_time = time.monotonic() - 120.0
        window.minute_times.clear()
        window.minute_times.append(old_time)
        window.hour_times.clear()
        window.hour_times.append(old_time)

        # Now prune should clear old entries and new request should pass
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200

    async def test_tracks_per_ip_independently(self) -> None:
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=2, requests_per_hour=100)

        # Exhaust IP A's quota
        for _ in range(2):
            cap = _ResponseCapture()
            await mw(_make_scope(client=("10.0.0.1", 1)), _noop_receive, cap)
            assert cap.status == 200

        # IP A is blocked
        cap = _ResponseCapture()
        await mw(_make_scope(client=("10.0.0.1", 1)), _noop_receive, cap)
        assert cap.status == 429

        # IP B should still be allowed
        cap = _ResponseCapture()
        await mw(_make_scope(client=("10.0.0.2", 1)), _noop_receive, cap)
        assert cap.status == 200

    async def test_non_http_scope_passes_through(self) -> None:
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=1, requests_per_hour=1)
        cap = _ResponseCapture()
        scope = _make_scope(scope_type="websocket")
        await mw(scope, _noop_receive, cap)
        # websocket type passes directly to app, which responds 200
        assert cap.status == 200

    async def test_loopback_127_exempt_by_default(self) -> None:
        """Requests from 127.0.0.1 bypass rate limiting when loopback_exempt=True."""
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=1, requests_per_hour=1)
        assert mw.loopback_exempt is True
        # Should allow unlimited requests from 127.0.0.1
        for _ in range(10):
            cap = _ResponseCapture()
            await mw(_make_scope(client=("127.0.0.1", 12345)), _noop_receive, cap)
            assert cap.status == 200

    async def test_loopback_ipv6_exempt_by_default(self) -> None:
        """Requests from ::1 bypass rate limiting when loopback_exempt=True."""
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=1, requests_per_hour=1)
        for _ in range(10):
            cap = _ResponseCapture()
            await mw(_make_scope(client=("::1", 12345)), _noop_receive, cap)
            assert cap.status == 200

    async def test_loopback_localhost_exempt_by_default(self) -> None:
        """Requests from 'localhost' bypass rate limiting when loopback_exempt=True."""
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=1, requests_per_hour=1)
        for _ in range(10):
            cap = _ResponseCapture()
            await mw(_make_scope(client=("localhost", 12345)), _noop_receive, cap)
            assert cap.status == 200

    async def test_loopback_exempt_disabled(self) -> None:
        """When loopback_exempt=False, 127.0.0.1 is rate-limited normally."""
        mw = RateLimitMiddleware(
            _dummy_app, requests_per_minute=2, requests_per_hour=100, loopback_exempt=False
        )
        for _ in range(2):
            cap = _ResponseCapture()
            await mw(_make_scope(client=("127.0.0.1", 12345)), _noop_receive, cap)
            assert cap.status == 200
        # Third request should be rate-limited
        cap = _ResponseCapture()
        await mw(_make_scope(client=("127.0.0.1", 12345)), _noop_receive, cap)
        assert cap.status == 429

    async def test_loopback_exempt_does_not_affect_external_ips(self) -> None:
        """External IPs are still rate-limited even when loopback_exempt=True."""
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=2, requests_per_hour=100)
        for _ in range(2):
            cap = _ResponseCapture()
            await mw(_make_scope(client=("10.0.0.1", 12345)), _noop_receive, cap)
            assert cap.status == 200
        cap = _ResponseCapture()
        await mw(_make_scope(client=("10.0.0.1", 12345)), _noop_receive, cap)
        assert cap.status == 429

    async def test_evicts_idle_ip_windows(self) -> None:
        """Windows for idle IPs are cleaned up to prevent unbounded memory."""
        mw = RateLimitMiddleware(_dummy_app, requests_per_minute=10, requests_per_hour=100)
        ip = "10.0.0.99"
        scope = _make_scope(client=(ip, 1))

        # Make one request
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200
        assert ip in mw._windows

        # Simulate all timestamps being old enough to prune
        window = mw._windows[ip]
        window.minute_times.clear()
        window.hour_times.clear()

        # Next request triggers eviction of empty window + re-creation
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200
        assert ip in mw._windows


# ===================================================================
# BodySizeLimitMiddleware
# ===================================================================


class TestBodySizeLimitMiddleware:
    """Tests for BodySizeLimitMiddleware."""

    async def test_allows_request_within_limit(self) -> None:
        max_bytes = 1024
        mw = BodySizeLimitMiddleware(_body_reading_app, max_bytes=max_bytes)

        body = b"x" * 500

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        cap = _ResponseCapture()
        scope = _make_scope(headers=[(b"content-length", str(len(body)).encode())])
        await mw(scope, receive, cap)
        assert cap.status == 200

    async def test_rejects_oversized_content_length(self) -> None:
        max_bytes = 1024
        mw = BodySizeLimitMiddleware(_dummy_app, max_bytes=max_bytes)
        cap = _ResponseCapture()
        scope = _make_scope(headers=[(b"content-length", b"2048")])
        await mw(scope, _noop_receive, cap)
        assert cap.status == 413
        body = cap.json
        assert body["error"] == "Payload Too Large"

    async def test_rejects_oversized_streaming_body(self) -> None:
        max_bytes = 100
        mw = BodySizeLimitMiddleware(_body_reading_app, max_bytes=max_bytes)

        call_count = 0

        async def receive() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"type": "http.request", "body": b"x" * 60, "more_body": True}
            else:
                return {"type": "http.request", "body": b"x" * 60, "more_body": False}

        cap = _ResponseCapture()
        # No content-length header, so fast-path doesn't reject
        await mw(_make_scope(), receive, cap)
        assert cap.status == 413

    async def test_exact_boundary_passes(self) -> None:
        max_bytes = 100
        mw = BodySizeLimitMiddleware(_body_reading_app, max_bytes=max_bytes)
        body = b"x" * 100

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        cap = _ResponseCapture()
        scope = _make_scope(headers=[(b"content-length", str(len(body)).encode())])
        await mw(scope, receive, cap)
        assert cap.status == 200

    async def test_non_http_scope_passes_through(self) -> None:
        mw = BodySizeLimitMiddleware(_dummy_app, max_bytes=1)
        cap = _ResponseCapture()
        scope = _make_scope(scope_type="websocket")
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200

    async def test_invalid_content_length_treated_as_zero(self) -> None:
        """Non-integer Content-Length is treated as 0 (not rejected)."""
        mw = BodySizeLimitMiddleware(_body_reading_app, max_bytes=1024)
        cap = _ResponseCapture()
        scope = _make_scope(headers=[(b"content-length", b"not-a-number")])

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"small", "more_body": False}

        await mw(scope, receive, cap)
        assert cap.status == 200

    async def test_no_content_length_header_uses_streaming_check(self) -> None:
        """Without Content-Length, body bytes are counted as they stream."""
        mw = BodySizeLimitMiddleware(_body_reading_app, max_bytes=50)

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"x" * 30, "more_body": False}

        cap = _ResponseCapture()
        await mw(_make_scope(), receive, cap)
        assert cap.status == 200


# ===================================================================
# OrgMembershipMiddleware
# ===================================================================


class TestOrgMembershipMiddleware:
    """Tests for OrgMembershipMiddleware."""

    def _make_checker(
        self,
        allowed_orgs: list[str] | None = None,
        is_allowed_return: bool = True,
    ) -> OrgMembershipChecker:
        """Create a mock OrgMembershipChecker."""
        checker = MagicMock(spec=OrgMembershipChecker)
        checker.enabled = bool(allowed_orgs)
        checker.allowed_orgs = allowed_orgs or []
        checker.is_allowed = AsyncMock(return_value=is_allowed_return)
        return checker  # type: ignore[return-value]

    async def test_valid_org_member_passes(self) -> None:
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=True)
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        token = _make_jwt({"login": "gooduser"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200
        checker.is_allowed.assert_awaited_once_with("gooduser")

    async def test_non_member_rejected_403(self) -> None:
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=False)
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        token = _make_jwt({"login": "baduser"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 403
        body = cap.json
        assert "forbidden" in body["error"]
        assert "baduser" in body["message"]
        assert "myorg" in body["message"]

    async def test_missing_auth_header_passes_through(self) -> None:
        """No auth header -> pass through to app (FastMCP will 401)."""
        checker = self._make_checker(allowed_orgs=["myorg"])
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        cap = _ResponseCapture()
        await mw(_make_scope(), _noop_receive, cap)
        assert cap.status == 200
        checker.is_allowed.assert_not_awaited()

    async def test_non_bearer_auth_passes_through(self) -> None:
        """Auth header without Bearer prefix -> pass through."""
        checker = self._make_checker(allowed_orgs=["myorg"])
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        scope = _make_scope(headers=[(b"authorization", b"Basic dXNlcjpwYXNz")])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200
        checker.is_allowed.assert_not_awaited()

    async def test_oauth_path_bypasses_check(self) -> None:
        """OAuth paths should always pass through regardless of auth."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=False)
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        for path in ["/oauth/callback", "/.well-known/openid-configuration", "/mcp/auth/login"]:
            cap = _ResponseCapture()
            scope = _make_scope(path=path)
            await mw(scope, _noop_receive, cap)
            assert cap.status == 200, f"Path {path} should bypass org check"

    async def test_disabled_checker_passes_through(self) -> None:
        """When checker.enabled is False, all requests pass through."""
        checker = self._make_checker(allowed_orgs=[])  # empty -> disabled
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        token = _make_jwt({"login": "anyone"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200

    async def test_non_http_scope_passes_through(self) -> None:
        checker = self._make_checker(allowed_orgs=["myorg"])
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        cap = _ResponseCapture()
        scope = _make_scope(scope_type="websocket")
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200

    async def test_opaque_token_fail_closed(self) -> None:
        """Non-JWT bearer token (no dots) -> 403 fail-closed."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=True)
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        scope = _make_scope(headers=[(b"authorization", b"Bearer opaque-token-no-dots")])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 403
        assert "<unknown>" in cap.json["message"]

    async def test_jwt_without_login_claim_fail_closed(self) -> None:
        """JWT with no login/sub claim -> 403 fail-closed."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=True)
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        token = _make_jwt({"email": "user@example.com"})  # no login or sub
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 403

    async def test_jwt_with_sub_claim_used_as_username(self) -> None:
        """JWT with 'sub' (no 'login') should use sub as username."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=True)
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        token = _make_jwt({"sub": "subuser"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200
        checker.is_allowed.assert_awaited_once_with("subuser")

    async def test_caching_via_checker(self) -> None:
        """Multiple requests with same token use the checker's cache."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=True)
        mw = OrgMembershipMiddleware(_dummy_app, checker)

        token = _make_jwt({"login": "cacheduser"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])

        for _ in range(3):
            cap = _ResponseCapture()
            await mw(scope, _noop_receive, cap)
            assert cap.status == 200

        # The checker.is_allowed is called each time by the middleware;
        # the OrgMembershipChecker itself handles caching internally.
        assert checker.is_allowed.await_count == 3

    async def test_org_denied_fires_audit_callback(self) -> None:
        """Org membership denial fires the audit callback."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=False)
        audit_cb = AsyncMock()
        mw = OrgMembershipMiddleware(_dummy_app, checker, audit_callback=audit_cb)

        token = _make_jwt({"login": "baduser"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 403

        audit_cb.assert_awaited_once_with(
            "baduser", "auth_org_denied", "", "auth_org_denied", "denied"
        )

    async def test_org_denied_unknown_user_fires_audit(self) -> None:
        """Opaque token (unknown user) denial fires audit callback."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=True)
        audit_cb = AsyncMock()
        mw = OrgMembershipMiddleware(_dummy_app, checker, audit_callback=audit_cb)

        scope = _make_scope(headers=[(b"authorization", b"Bearer opaque-token-no-dots")])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 403

        audit_cb.assert_awaited_once_with(
            "<unknown>", "auth_org_denied", "", "auth_org_denied", "denied"
        )

    async def test_audit_callback_failure_does_not_break_403(self) -> None:
        """A failing audit callback must not prevent the 403 response."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=False)
        audit_cb = AsyncMock(side_effect=RuntimeError("db down"))
        mw = OrgMembershipMiddleware(_dummy_app, checker, audit_callback=audit_cb)

        token = _make_jwt({"login": "baduser"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        # 403 is still sent despite audit failure.
        assert cap.status == 403

    async def test_no_audit_callback_on_allowed_user(self) -> None:
        """Audit callback is NOT fired when user is allowed."""
        checker = self._make_checker(allowed_orgs=["myorg"], is_allowed_return=True)
        audit_cb = AsyncMock()
        mw = OrgMembershipMiddleware(_dummy_app, checker, audit_callback=audit_cb)

        token = _make_jwt({"login": "gooduser"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200
        audit_cb.assert_not_awaited()


# ===================================================================
# _client_ip helper
# ===================================================================


class TestClientIp:
    """Tests for the _client_ip helper function."""

    def test_extracts_from_scope_client(self) -> None:
        scope = _make_scope(client=("192.168.1.1", 8080))
        assert _client_ip(scope) == "192.168.1.1"

    def test_falls_back_to_x_forwarded_for(self) -> None:
        scope = _make_scope(
            client=None,
            headers=[(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")],
        )
        assert _client_ip(scope) == "1.2.3.4"

    def test_trust_proxy_prefers_x_forwarded_for(self) -> None:
        scope = _make_scope(
            client=("127.0.0.1", 1234),
            headers=[(b"x-forwarded-for", b"203.0.113.50")],
        )
        # Without trust_proxy, uses client
        assert _client_ip(scope) == "127.0.0.1"
        # With trust_proxy, uses X-Forwarded-For
        assert _client_ip(scope, trust_proxy=True) == "203.0.113.50"

    def test_returns_unknown_when_no_client_info(self) -> None:
        scope = _make_scope(client=None)
        assert _client_ip(scope) == "unknown"

    def test_multiple_forwarded_for_uses_first(self) -> None:
        scope = _make_scope(
            client=None,
            headers=[(b"x-forwarded-for", b"10.0.0.1, 10.0.0.2, 10.0.0.3")],
        )
        assert _client_ip(scope) == "10.0.0.1"


# ===================================================================
# apply_http_middleware
# ===================================================================


class TestApplyHttpMiddleware:
    """Tests for the apply_http_middleware factory function."""

    async def test_basic_composition_without_org_checker(self) -> None:
        """Composes rate limit + body size middleware."""
        app = apply_http_middleware(_dummy_app)
        cap = _ResponseCapture()
        await app(_make_scope(), _noop_receive, cap)
        assert cap.status == 200

    async def test_composition_with_org_checker(self) -> None:
        """When org checker is provided and enabled, adds OrgMembershipMiddleware."""
        checker = MagicMock(spec=OrgMembershipChecker)
        checker.enabled = True
        checker.allowed_orgs = ["testorg"]
        checker.is_allowed = AsyncMock(return_value=True)

        app = apply_http_middleware(_dummy_app, org_checker=checker)

        token = _make_jwt({"login": "devuser"})
        scope = _make_scope(headers=[(b"authorization", f"Bearer {token}".encode())])
        cap = _ResponseCapture()
        await app(scope, _noop_receive, cap)
        assert cap.status == 200

    async def test_composition_with_disabled_org_checker(self) -> None:
        """Disabled org checker skips OrgMembershipMiddleware."""
        checker = MagicMock(spec=OrgMembershipChecker)
        checker.enabled = False

        app = apply_http_middleware(_dummy_app, org_checker=checker)
        cap = _ResponseCapture()
        await app(_make_scope(), _noop_receive, cap)
        assert cap.status == 200

    async def test_rate_limit_applies_in_composition(self) -> None:
        """Rate limiting works through the composed middleware stack."""
        app = apply_http_middleware(
            _dummy_app,
            requests_per_minute=2,
            requests_per_hour=100,
            loopback_exempt=False,
        )
        for _ in range(2):
            cap = _ResponseCapture()
            await app(_make_scope(), _noop_receive, cap)
            assert cap.status == 200

        cap = _ResponseCapture()
        await app(_make_scope(), _noop_receive, cap)
        assert cap.status == 429

    async def test_body_size_limit_applies_in_composition(self) -> None:
        """Body size limit works through the composed middleware stack."""
        app = apply_http_middleware(
            _dummy_app,
            max_body_bytes=100,
            requests_per_minute=1000,
        )
        cap = _ResponseCapture()
        scope = _make_scope(headers=[(b"content-length", b"200")])
        await app(scope, _noop_receive, cap)
        assert cap.status == 413

    async def test_loopback_exempt_in_composition(self) -> None:
        """Loopback exemption works through the composed middleware stack."""
        app = apply_http_middleware(
            _dummy_app,
            requests_per_minute=1,
            requests_per_hour=1,
            loopback_exempt=True,
        )
        # 127.0.0.1 should bypass rate limiting
        for _ in range(5):
            cap = _ResponseCapture()
            await app(_make_scope(client=("127.0.0.1", 12345)), _noop_receive, cap)
            assert cap.status == 200

    async def test_loopback_exempt_disabled_in_composition(self) -> None:
        """When loopback_exempt=False, localhost is rate-limited in composed stack."""
        app = apply_http_middleware(
            _dummy_app,
            requests_per_minute=1,
            requests_per_hour=100,
            loopback_exempt=False,
        )
        cap = _ResponseCapture()
        await app(_make_scope(client=("127.0.0.1", 12345)), _noop_receive, cap)
        assert cap.status == 200
        cap = _ResponseCapture()
        await app(_make_scope(client=("127.0.0.1", 12345)), _noop_receive, cap)
        assert cap.status == 429

    async def test_request_id_present_in_composition(self) -> None:
        """X-Request-ID header is echoed on responses from the composed stack."""
        app = apply_http_middleware(_dummy_app, requests_per_minute=1000)
        cap = _ResponseCapture()
        scope = _make_scope(headers=[(b"x-request-id", b"trace-abc123")])
        await app(scope, _noop_receive, cap)
        assert cap.status == 200
        assert cap.headers.get("x-request-id") == "trace-abc123"


# ===================================================================
# TestRequestIDMiddleware
# ===================================================================


class TestRequestIDMiddleware:
    """Tests for RequestIDMiddleware."""

    async def test_echoes_provided_request_id(self) -> None:
        """X-Request-ID from request is echoed in the response."""
        mw = RequestIDMiddleware(_dummy_app)
        cap = _ResponseCapture()
        scope = _make_scope(headers=[(b"x-request-id", b"my-trace-id")])
        await mw(scope, _noop_receive, cap)
        assert cap.status == 200
        assert cap.headers.get("x-request-id") == "my-trace-id"

    async def test_generates_id_when_absent(self) -> None:
        """A UUID4 is generated when X-Request-ID is not present."""
        import uuid

        mw = RequestIDMiddleware(_dummy_app)
        cap = _ResponseCapture()
        await mw(_make_scope(), _noop_receive, cap)
        assert cap.status == 200
        rid = cap.headers.get("x-request-id", "")
        parsed = uuid.UUID(rid)
        assert parsed.version == 4, f"Expected UUID4, got version {parsed.version}"

    async def test_non_http_scope_passthrough(self) -> None:
        """Non-HTTP scopes are passed through without modification."""
        called: list[str] = []

        async def _inner(scope: Any, receive: Any, send: Any) -> None:
            called.append(scope["type"])

        mw = RequestIDMiddleware(_inner)
        ws_scope = _make_scope(scope_type="websocket")
        await mw(ws_scope, _noop_receive, _ResponseCapture())
        assert called == ["websocket"]

    async def test_request_id_present_on_429(self) -> None:
        """X-Request-ID is included on rate-limited 429 responses."""
        import uuid

        app = apply_http_middleware(
            _dummy_app,
            requests_per_minute=1,
            requests_per_hour=100,
            loopback_exempt=False,
        )
        # First request succeeds and consumes the quota.
        cap = _ResponseCapture()
        await app(_make_scope(), _noop_receive, cap)
        assert cap.status == 200

        # Second request is rate-limited — should still carry X-Request-ID.
        cap = _ResponseCapture()
        await app(_make_scope(), _noop_receive, cap)
        assert cap.status == 429
        rid = cap.headers.get("x-request-id", "")
        parsed = uuid.UUID(rid)
        assert parsed.version == 4, f"Expected UUID4 on 429 response, got {rid!r}"
