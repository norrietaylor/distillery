"""Outbound-fetch guard for the feed poller.

Feed source URLs are operator- and user-supplied via ``distillery_watch``.
The poller later issues HTTP requests against them, so this module restricts
those requests to publicly-routable hosts and re-checks the target at every
redirect hop. It also caps the response body so a single feed cannot exhaust
server memory.

Two entry points:

- :func:`validate_public_url` — call before persisting a feed source.
- :func:`fetch_feed_bytes` — redirect-aware fetch that re-validates each hop
  and streams the body under a hard size cap.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# Schemes the poller is permitted to fetch.
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Maximum redirect hops followed before a fetch is abandoned.
MAX_REDIRECTS = 5

# Hard cap on a feed response body. Feeds are small XML documents; a larger
# body is rejected before it is fully buffered.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MiB

# Carrier-grade NAT range (RFC 6598). ``ipaddress.is_private`` only covers
# this on newer Python versions, so it is checked explicitly.
_CGNAT_V4 = ipaddress.ip_network("100.64.0.0/10")


class UnsafeURLError(ValueError):
    """Raised when a URL targets a non-public or otherwise disallowed host."""


class ResponseTooLargeError(ValueError):
    """Raised when a feed response body exceeds :data:`MAX_RESPONSE_BYTES`."""


def _resolve_ips(host: str) -> list[str]:
    """Return every IP address *host* resolves to.

    Wraps :func:`socket.getaddrinfo`; kept as a module-level function so tests
    can substitute a deterministic resolver.
    """
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def _ip_is_public(raw_ip: str) -> bool:
    """Return ``True`` only for a globally-routable unicast address.

    Loopback, link-local (incl. the cloud metadata address ``169.254.169.254``),
    private, CGNAT, multicast, reserved, and unspecified addresses all return
    ``False``.
    """
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address = ipaddress.ip_address(raw_ip)
    # IPv4-mapped IPv6 (``::ffff:a.b.c.d``) — evaluate the embedded v4 address.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    # Carrier-grade NAT (RFC 6598) is not flagged by ``is_private`` on every
    # supported Python version, so it is checked explicitly.
    return not (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_V4)


def validate_public_url(url: str) -> None:
    """Validate that *url* is an ``http(s)`` URL whose host is publicly routable.

    A host that does not resolve at all is *not* rejected: it cannot point at
    an internal address, so it is not an SSRF concern, and reachability is the
    caller's responsibility (the ``distillery_watch`` probe / the poller fetch).

    Args:
        url: The candidate URL.

    Raises:
        UnsafeURLError: If the scheme is not ``http``/``https``, the host is
            missing, or any resolved address is loopback, link-local, private,
            CGNAT, or otherwise non-public.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"url must use the http or https scheme, got: {scheme!r}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError(f"url is missing a host: {url!r}")

    try:
        addresses = _resolve_ips(host)
    except OSError:
        # Resolution failed — no resolved address can point at an internal
        # host, so there is nothing to block here.
        return

    for raw_ip in addresses:
        try:
            public = _ip_is_public(raw_ip)
        except ValueError as exc:  # malformed address from the resolver
            raise UnsafeURLError(f"host {host!r} resolved to an invalid address") from exc
        if not public:
            raise UnsafeURLError(f"host {host!r} resolves to a non-public address")


def fetch_feed_bytes(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    *,
    max_redirects: int = MAX_REDIRECTS,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> bytes:
    """Fetch *url* with *client*, validating the host at every redirect hop.

    Redirects are followed manually so each ``Location`` target is re-validated
    by :func:`validate_public_url` before another request is issued. The
    response body is streamed and rejected once it exceeds *max_bytes*.

    Args:
        client: An :class:`httpx.Client`. Per-request ``follow_redirects`` is
            forced off regardless of the client's default.
        url: The URL to fetch.
        headers: Request headers (e.g. ``User-Agent``).
        max_redirects: Maximum redirect hops to follow.
        max_bytes: Maximum accepted response body size in bytes.

    Returns:
        The response body bytes.

    Raises:
        UnsafeURLError: If *url* or any redirect target is not a public host,
            or the redirect limit is exceeded.
        ResponseTooLargeError: If the body exceeds *max_bytes*.
        httpx.HTTPStatusError: On a non-2xx, non-redirect response.
        httpx.HTTPError: On a network-level failure.
    """
    current = url
    for _ in range(max_redirects + 1):
        validate_public_url(current)
        with client.stream("GET", current, headers=headers, follow_redirects=False) as response:
            if response.is_redirect:
                # ``is_redirect`` guarantees a Location header is present.
                current = urljoin(current, response.headers["location"])
                continue
            response.raise_for_status()

            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > max_bytes:
                raise ResponseTooLargeError(
                    f"feed response declares {declared} bytes, exceeding the {max_bytes}-byte limit"
                )

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise ResponseTooLargeError(
                        f"feed response exceeded the {max_bytes}-byte limit"
                    )
                chunks.append(chunk)
            return b"".join(chunks)

    raise UnsafeURLError(f"feed URL exceeded {max_redirects} redirects: {url!r}")
