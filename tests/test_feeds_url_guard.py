"""Tests for distillery.feeds.url_guard.

Covers:
  - validate_public_url: scheme allowlist, host resolution, IP-range checks
  - fetch_feed_bytes: redirect re-validation, size cap, HTTP error propagation
"""

from __future__ import annotations

import socket
import threading

import httpx
import pytest

from distillery.feeds.url_guard import (
    MAX_RESPONSE_BYTES,
    ResponseTooLargeError,
    UnsafeURLError,
    _ip_is_public,
    _pin_dns,
    fetch_feed_bytes,
    validate_public_url,
)

pytestmark = pytest.mark.unit

# A routable public IPv4 literal — getaddrinfo returns it without DNS.
_PUBLIC = "93.184.216.34"


# ---------------------------------------------------------------------------
# _ip_is_public
# ---------------------------------------------------------------------------


class TestIpIsPublic:
    @pytest.mark.parametrize("ip", [_PUBLIC, "1.1.1.1", "8.8.8.8"])
    def test_public_addresses_accepted(self, ip: str) -> None:
        assert _ip_is_public(ip) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1",  # loopback
            "169.254.169.254",  # link-local / cloud metadata
            "10.0.0.1",  # private
            "192.168.1.1",  # private
            "172.16.0.1",  # private
            "100.64.0.1",  # carrier-grade NAT (RFC 6598)
            "0.0.0.0",  # unspecified
            "::1",  # IPv6 loopback
            "fe80::1",  # IPv6 link-local
            "fc00::1",  # IPv6 unique-local
            "::ffff:127.0.0.1",  # IPv4-mapped loopback
        ],
    )
    def test_non_public_addresses_rejected(self, ip: str) -> None:
        assert _ip_is_public(ip) is False


# ---------------------------------------------------------------------------
# validate_public_url
# ---------------------------------------------------------------------------


class TestValidatePublicURL:
    def test_public_ip_literal_accepted(self) -> None:
        validate_public_url(f"http://{_PUBLIC}/feed.xml")

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/feed",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/feed",
            "http://192.168.0.1/feed",
            "http://100.64.0.1/feed",
            "http://[::1]/feed",
        ],
    )
    def test_internal_literal_rejected(self, url: str) -> None:
        with pytest.raises(UnsafeURLError):
            validate_public_url(url)

    @pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "gopher://x/"])
    def test_disallowed_scheme_rejected(self, url: str) -> None:
        with pytest.raises(UnsafeURLError, match="scheme"):
            validate_public_url(url)

    def test_missing_host_rejected(self) -> None:
        with pytest.raises(UnsafeURLError, match="host"):
            validate_public_url("http:///feed")

    def test_hostname_resolving_to_private_ip_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("distillery.feeds.url_guard._resolve_ips", lambda host: ["10.1.2.3"])
        with pytest.raises(UnsafeURLError, match="non-public"):
            validate_public_url("https://internal.example.com/feed")

    def test_hostname_with_mixed_addresses_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A resolver returning one public and one private address must fail.
        monkeypatch.setattr(
            "distillery.feeds.url_guard._resolve_ips", lambda host: [_PUBLIC, "127.0.0.1"]
        )
        with pytest.raises(UnsafeURLError):
            validate_public_url("https://rebind.example.com/feed")

    def test_public_hostname_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("distillery.feeds.url_guard._resolve_ips", lambda host: [_PUBLIC])
        validate_public_url("https://feeds.example.com/rss")

    def test_unresolvable_host_not_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # NXDOMAIN-class failures (EAI_NONAME / EAI_NODATA) cannot point at an
        # internal address, so the SSRF guard passes them silently;
        # reachability is checked elsewhere.
        def _boom(host: str) -> list[str]:
            raise socket.gaierror(socket.EAI_NONAME, "name resolution failed")

        monkeypatch.setattr("distillery.feeds.url_guard._resolve_ips", _boom)
        validate_public_url("https://nonexistent.invalid/feed")

    def test_transient_dns_failure_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A transient resolver outage (EAI_AGAIN) MUST fail closed: returning
        # silently would let the same hostname resolve to a private IP a
        # moment later, defeating the guard once combined with DNS pinning.
        def _boom(host: str) -> list[str]:
            raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")

        monkeypatch.setattr("distillery.feeds.url_guard._resolve_ips", _boom)
        with pytest.raises(UnsafeURLError, match="could not be resolved"):
            validate_public_url("https://flaky.example.com/feed")

    def test_unknown_oserror_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Any non-gaierror low-level resolver error must also fail closed.
        def _boom(host: str) -> list[str]:
            raise OSError("resolver crashed")

        monkeypatch.setattr("distillery.feeds.url_guard._resolve_ips", _boom)
        with pytest.raises(UnsafeURLError, match="could not be resolved"):
            validate_public_url("https://broken.example.com/feed")


# ---------------------------------------------------------------------------
# fetch_feed_bytes
# ---------------------------------------------------------------------------


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


class TestFetchFeedBytes:
    def test_simple_fetch_returns_body(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<rss/>")

        with _client(handler) as client:
            body = fetch_feed_bytes(client, f"http://{_PUBLIC}/feed", {})
        assert body == b"<rss/>"

    def test_redirect_to_public_host_followed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/feed":
                return httpx.Response(302, headers={"location": f"http://{_PUBLIC}/final"})
            return httpx.Response(200, content=b"<rss/>")

        with _client(handler) as client:
            body = fetch_feed_bytes(client, f"http://{_PUBLIC}/feed", {})
        assert body == b"<rss/>"

    def test_redirect_to_internal_host_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

        with _client(handler) as client, pytest.raises(UnsafeURLError):
            fetch_feed_bytes(client, f"http://{_PUBLIC}/feed", {})

    def test_redirect_limit_enforced(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": f"http://{_PUBLIC}/loop"})

        with _client(handler) as client, pytest.raises(UnsafeURLError, match="redirect"):
            fetch_feed_bytes(client, f"http://{_PUBLIC}/feed", {})

    def test_oversized_streamed_body_rejected(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 200)

        with _client(handler) as client, pytest.raises(ResponseTooLargeError):
            fetch_feed_bytes(client, f"http://{_PUBLIC}/feed", {}, max_bytes=100)

    def test_body_at_limit_accepted(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 100)

        with _client(handler) as client:
            body = fetch_feed_bytes(client, f"http://{_PUBLIC}/feed", {}, max_bytes=100)
        assert len(body) == 100

    def test_default_size_cap_is_five_mib(self) -> None:
        assert MAX_RESPONSE_BYTES == 5 * 1024 * 1024

    def test_six_mib_body_rejected_under_five_mib_cap(self) -> None:
        # A ~6 MiB feed (e.g. northflank.com/blog/rss, ~6.90 MB) exceeds the
        # library default of 5 MiB and must be rejected when that cap applies.
        body = b"x" * (6 * 1024 * 1024)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body)

        with _client(handler) as client, pytest.raises(ResponseTooLargeError):
            fetch_feed_bytes(client, f"http://{_PUBLIC}/feed", {}, max_bytes=5 * 1024 * 1024)

    def test_six_mib_body_accepted_under_ten_mib_cap(self) -> None:
        # The same ~6 MiB feed is accepted once the configurable cap is raised
        # to 10 MiB (the FeedsConfig default), proving the cap is honoured.
        body = b"x" * (6 * 1024 * 1024)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=body)

        with _client(handler) as client:
            fetched = fetch_feed_bytes(
                client, f"http://{_PUBLIC}/feed", {}, max_bytes=10 * 1024 * 1024
            )
        assert len(fetched) == len(body)

    def test_http_error_propagates(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        with _client(handler) as client, pytest.raises(httpx.HTTPStatusError):
            fetch_feed_bytes(client, f"http://{_PUBLIC}/feed", {})


# ---------------------------------------------------------------------------
# _pin_dns concurrency (#709)
# ---------------------------------------------------------------------------


class TestPinDnsConcurrency:
    def test_overlapping_pins_do_not_leak(self) -> None:
        """Interleaved enter/exit across threads leaves no pin behind (#709).

        Order: A enters, B enters, A exits, B exits — the sequence that used to
        leave A's stub installed on ``socket.getaddrinfo`` for good.
        """
        a_in, b_in, a_out = threading.Event(), threading.Event(), threading.Event()
        seen: dict[str, object] = {}

        def run_a() -> None:
            with _pin_dns("pin-a.invalid", "203.0.113.1"):
                a_in.set()
                assert b_in.wait(5)
                seen["a"] = socket.getaddrinfo("pin-a.invalid", 80)[0][4][0]
                seen["a_on_b"] = _lookup("pin-b.invalid")
            a_out.set()

        def run_b() -> None:
            assert a_in.wait(5)
            with _pin_dns("pin-b.invalid", "203.0.113.2"):
                b_in.set()
                assert a_out.wait(5)
                seen["b"] = socket.getaddrinfo("pin-b.invalid", 80)[0][4][0]

        threads = [threading.Thread(target=run_a), threading.Thread(target=run_b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)

        # A never sees B's pin: the lookup goes to the real resolver and fails.
        assert isinstance(seen.pop("a_on_b"), socket.gaierror)
        assert seen == {"a": "203.0.113.1", "b": "203.0.113.2"}
        resolver = socket.getaddrinfo
        with _pin_dns("pin-c.invalid", "203.0.113.3"):
            pass
        assert socket.getaddrinfo is resolver
        for host in ("pin-a.invalid", "pin-b.invalid"):
            with pytest.raises(socket.gaierror):
                socket.getaddrinfo(host, 80)


def _lookup(host: str) -> object:
    """Resolve *host*, returning the error instead of raising."""
    try:
        return socket.getaddrinfo(host, 80)
    except OSError as exc:
        return exc
