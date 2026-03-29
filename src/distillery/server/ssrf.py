"""SSRF protection — blocks requests to private/loopback addresses."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# RFC-1918 and other non-routable ranges
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
]

_ALLOWED_SCHEMES = {"http", "https"}


class SSRFError(ValueError):
    """Raised when a URL is blocked by SSRF protection."""


def validate_url(url: str) -> None:
    """Raise SSRFError if the URL points to a private/loopback address or disallowed scheme.

    Note: This validates the URL scheme and hostname, but DNS rebinding attacks are possible.
    Use create_ssrf_safe_client() for connection-time validation.
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise SSRFError(f"Scheme '{parsed.scheme}' is not allowed. Use http or https.")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("URL has no hostname.")

    # Resolve hostname to IP
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFError(f"Cannot resolve hostname '{hostname}': {exc}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addr_info:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for network in _BLOCKED_NETWORKS:
            if ip in network:
                raise SSRFError(
                    f"URL resolves to a private/loopback address ({ip}) which is not allowed."
                )


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address is in a blocked network."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    for network in _BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


class SSRFSafeTransport(httpx.AsyncHTTPTransport):
    """Custom transport that validates connection targets at connection time."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Validate target IP before making request."""
        # Extract hostname from request
        hostname = request.url.host
        if not hostname:
            raise SSRFError("Request has no hostname")

        # Resolve hostname at connection time
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise SSRFError(f"Cannot resolve hostname '{hostname}': {exc}") from exc

        # Check all resolved IPs
        for _family, _type, _proto, _canonname, sockaddr in addr_info:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                raise SSRFError(
                    f"Hostname '{hostname}' resolves to private/loopback address ({ip_str})"
                )

        # All checks passed, proceed with request
        return await super().handle_async_request(request)


def create_ssrf_safe_client(**kwargs: object) -> httpx.AsyncClient:
    """Create an httpx client with SSRF protection at connection time.

    This defends against DNS rebinding attacks by validating the resolved IP
    at connection time, not just during initial URL validation.
    """
    return httpx.AsyncClient(transport=SSRFSafeTransport(), **kwargs)
