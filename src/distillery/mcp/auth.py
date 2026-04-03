"""GitHub OAuth authentication for the Distillery MCP HTTP transport.

Provides :func:`build_github_auth` which reads OAuth credentials from
environment variables (names configured in ``distillery.yaml``) and returns
a configured ``GitHubProvider`` instance for FastMCP.

**Authentication model:** GitHub OAuth is used as an identity gate only.
FastMCP's ``GitHubProvider`` requests the ``user`` scope (read-only profile),
verifies tokens by calling ``https://api.github.com/user``, and extracts
identity claims (``login``, ``name``, ``email``, ``avatar_url``).  The server never gains
access to the user's repositories, organizations, or other GitHub data.
Tool handlers can read the caller's identity from FastMCP's ``Context``
object but never see the raw GitHub token.

Includes a workaround for FastMCP CIMD localhost redirect validation
(see :func:`_patch_cimd_localhost_redirect`).
"""

from __future__ import annotations

import fnmatch
import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from fastmcp.server.auth.providers.github import GitHubProvider

from distillery.config import DistilleryConfig, parse_env_allowed_orgs
from distillery.mcp.org_membership import OrgMembershipChecker

logger = logging.getLogger(__name__)


class OrgRestrictedGitHubProvider(GitHubProvider):
    """GitHubProvider subclass that captures user tokens for org membership checks.

    Overrides :meth:`_extract_upstream_claims` to:
    1. Query the GitHub ``/user`` endpoint for the authenticated user's login.
    2. Embed the ``login`` claim in the FastMCP JWT so downstream middleware
       can identify the user without an extra API call.
    3. Call :meth:`OrgMembershipChecker.store_user_token` so private-org
       membership checks can use the user's own OAuth token.
    """

    def __init__(
        self,
        *,
        org_checker: OrgMembershipChecker,
        client_id: str,
        client_secret: str,
        base_url: str,
    ) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
        )
        self._org_checker = org_checker

    async def _extract_upstream_claims(self, idp_tokens: dict[str, Any]) -> dict[str, Any] | None:
        """Extract GitHub user identity and store the token for org checks."""
        access_token = idp_tokens.get("access_token")
        if not access_token or not isinstance(access_token, str):
            return None

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Failed to fetch GitHub user info during OAuth exchange: %d",
                        resp.status_code,
                    )
                    return None

                user_data = resp.json()
                login = user_data.get("login", "")
                if login:
                    self._org_checker.store_user_token(login, access_token)
                    logger.debug("Stored user token for %s", login)

                return {
                    "login": login,
                    "name": user_data.get("name"),
                    "email": user_data.get("email"),
                }
        except Exception:
            logger.warning("Error extracting upstream claims", exc_info=True)
            return None


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

    def _validate_redirect_uri(self: CIMDFetcher, doc: CIMDDocument, redirect_uri: str) -> bool:
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

    # Patch the redirect_validation.matches_allowed_pattern function used by
    # ProxyDCRClient.validate_redirect_uri (oauth_proxy/models.py line 218).
    # The CIMD document declares "http://localhost/callback" but Claude Code
    # sends "http://localhost:<port>/callback". matches_allowed_pattern does
    # exact comparison unless wildcards are present.  We wrap it to treat
    # loopback hosts as port-agnostic per RFC 8252 §7.3.
    try:
        import fastmcp.server.auth.oauth_proxy.models as proxy_models
        from fastmcp.server.auth.redirect_validation import (
            matches_allowed_pattern as _original_matches,
        )
    except ImportError:
        logger.info("Patched CIMDFetcher only (proxy models not found)")
        return

    def _patched_matches(uri: str, pattern: str) -> bool:
        if _original_matches(uri, pattern):
            return True
        # RFC 8252 §7.3: loopback — ignore port differences
        uri_parsed = urlparse(uri)
        pattern_parsed = urlparse(pattern)
        return (
            uri_parsed.hostname in _LOOPBACK_HOSTS
            and pattern_parsed.hostname in _LOOPBACK_HOSTS
            and uri_parsed.scheme == pattern_parsed.scheme
            and uri_parsed.path == pattern_parsed.path
        )

    proxy_models.matches_allowed_pattern = _patched_matches  # type: ignore[attr-defined]
    logger.info("Patched CIMD and proxy redirect validation for RFC 8252 localhost port handling")


def build_github_auth(
    config: DistilleryConfig,
    org_checker: OrgMembershipChecker | None = None,
) -> GitHubProvider:
    """Build a :class:`~fastmcp.server.auth.providers.github.GitHubProvider`.

    Reads the OAuth client ID and secret from the environment variable names
    specified in ``config.server.auth``.

    When *org_checker* is provided, returns an
    :class:`OrgRestrictedGitHubProvider` that captures user tokens during
    the OAuth exchange for private-org membership checks.

    Args:
        config: Distillery configuration with ``server.auth`` populated.
        org_checker: Optional org membership checker to wire token capture.

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

    if org_checker is not None:
        return OrgRestrictedGitHubProvider(
            org_checker=org_checker,
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
        )

    return GitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
    )


def build_org_checker(config: DistilleryConfig) -> OrgMembershipChecker | None:
    """Build an :class:`~distillery.mcp.org_membership.OrgMembershipChecker`.

    Merges ``allowed_orgs`` from the YAML config with orgs supplied via the
    ``DISTILLERY_ALLOWED_ORGS`` environment variable (comma-separated).

    Returns ``None`` when no orgs are configured (open-access mode).

    Args:
        config: Distillery configuration.

    Returns:
        A configured :class:`OrgMembershipChecker`, or ``None`` if
        ``allowed_orgs`` is empty after merging config and env.
    """
    allowed_orgs: list[str] = list(config.server.auth.allowed_orgs)

    seen = set(allowed_orgs)
    for org in parse_env_allowed_orgs():
        if org not in seen:
            allowed_orgs.append(org)
            seen.add(org)

    if not allowed_orgs:
        return None

    server_token = os.environ.get("GITHUB_ORG_CHECK_TOKEN", "").strip() or None

    logger.info(
        "Org membership restriction enabled: %s (cache_ttl=%ds)",
        allowed_orgs,
        config.server.auth.membership_cache_ttl_seconds,
    )

    return OrgMembershipChecker(
        allowed_orgs=allowed_orgs,
        cache_ttl_seconds=config.server.auth.membership_cache_ttl_seconds,
        server_token=server_token,
    )
