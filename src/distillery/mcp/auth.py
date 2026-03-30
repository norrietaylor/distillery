"""GitHub OAuth authentication for the Distillery MCP HTTP transport.

Provides :func:`build_github_auth` which reads OAuth credentials from
environment variables (names configured in ``distillery.yaml``) and returns
a configured ``GitHubProvider`` instance for FastMCP.

Includes a workaround for FastMCP CIMD localhost redirect validation
(see :func:`_patch_cimd_localhost_redirect`).
"""

from __future__ import annotations

import fnmatch
import logging
import os
from urllib.parse import urlparse

from fastmcp.server.auth.providers.github import GitHubProvider

from distillery.config import DistilleryConfig

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _patch_cimd_localhost_redirect() -> None:
    """Patch FastMCP's CIMDFetcher to allow any port on localhost redirects.

    Per RFC 8252 Section 7.3, loopback redirect URIs must match regardless of
    port.  FastMCP 3.1.1's ``CIMDFetcher.validate_redirect_uri`` does an exact
    string comparison, which fails when Claude Code requests
    ``http://localhost:<dynamic-port>/callback`` but the CIMD document declares
    ``http://localhost/callback`` (no port).

    This monkey-patch replaces ``validate_redirect_uri`` with a version that
    treats loopback hosts as port-agnostic.
    """
    try:
        from fastmcp.server.auth.cimd import CIMDDocument, CIMDFetcher
    except ImportError:
        return  # FastMCP version without CIMD support

    def _validate_redirect_uri(
        self: CIMDFetcher, doc: CIMDDocument, redirect_uri: str
    ) -> bool:
        if not doc.redirect_uris:
            return False

        redirect_uri = redirect_uri.rstrip("/")
        parsed = urlparse(redirect_uri)
        is_loopback = parsed.hostname in _LOOPBACK_HOSTS

        for allowed in doc.redirect_uris:
            allowed_str = allowed.rstrip("/")

            # Exact match
            if redirect_uri == allowed_str:
                return True

            # Wildcard match
            if "*" in allowed_str and fnmatch.fnmatch(redirect_uri, allowed_str):
                return True

            # RFC 8252 §7.3: loopback — ignore port differences
            if is_loopback:
                allowed_parsed = urlparse(allowed_str)
                if (
                    allowed_parsed.hostname in _LOOPBACK_HOSTS
                    and parsed.scheme == allowed_parsed.scheme
                    and parsed.path == allowed_parsed.path
                ):
                    return True

        return False

    CIMDFetcher.validate_redirect_uri = _validate_redirect_uri  # type: ignore[method-assign]
    logger.info("Patched CIMDFetcher.validate_redirect_uri for RFC 8252 localhost port handling")


def build_github_auth(config: DistilleryConfig) -> GitHubProvider:
    """Build a :class:`~fastmcp.server.auth.providers.github.GitHubProvider`.

    Reads the OAuth client ID and secret from the environment variable names
    specified in ``config.server.auth``.

    Args:
        config: Distillery configuration with ``server.auth`` populated.

    Returns:
        A configured :class:`GitHubProvider` instance.

    Raises:
        ValueError: If either the client ID or client secret environment
            variable is missing or empty.
    """
    auth = config.server.auth
    client_id = os.environ.get(auth.client_id_env, "").strip()
    client_secret = os.environ.get(auth.client_secret_env, "").strip()

    if not client_id:
        raise ValueError(
            f"GitHub OAuth client ID env var {auth.client_id_env!r} is not set or empty. "
            "Set the environment variable before starting the server."
        )

    if not client_secret:
        raise ValueError(
            f"GitHub OAuth client secret env var {auth.client_secret_env!r} is not set or empty. "
            "Set the environment variable before starting the server."
        )

    base_url = os.environ.get("DISTILLERY_BASE_URL", "").strip()
    if not base_url:
        raise ValueError(
            "DISTILLERY_BASE_URL env var is required when server.auth.provider is 'github'. "
            "Set it to the publicly accessible URL of the server "
            "(e.g. 'https://distillery.example.com')."
        )
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            f"DISTILLERY_BASE_URL must be a valid absolute http(s) URL, got: {base_url!r}. "
            "Example: 'https://distillery.example.com'."
        )

    # Log that auth is being configured, but NEVER log secret values.
    logger.info(
        "Configuring GitHub OAuth (client_id_env=%s, base_url=%s)",
        auth.client_id_env,
        base_url,
    )

    return GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
    )
