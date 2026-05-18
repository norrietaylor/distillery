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
import hmac
import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.github import GitHubProvider

from distillery.config import DistilleryConfig, parse_env_allowed_orgs
from distillery.mcp.org_membership import OrgMembershipChecker
from distillery.mcp.types import AuditCallback

logger = logging.getLogger(__name__)


# Environment variables for the optional pre-shared machine-token auth path.
# DISTILLERY_MCP_MACHINE_TOKEN holds the token; DISTILLERY_MCP_MACHINE_IDENTITY
# is the GitHub-style login attributed to calls made with it (authorship and
# audit). The feature is off unless the token variable is set.
_MACHINE_TOKEN_ENV = "DISTILLERY_MCP_MACHINE_TOKEN"
_MACHINE_IDENTITY_ENV = "DISTILLERY_MCP_MACHINE_IDENTITY"
_DEFAULT_MACHINE_IDENTITY = "distillery-machine"


def load_machine_token_values() -> list[str]:
    """Return the configured pre-shared machine token(s), or ``[]`` when unset.

    Single source of truth for reading ``DISTILLERY_MCP_MACHINE_TOKEN``. Both
    the auth verifier (:func:`_load_machine_tokens`) and ``OrgMembershipMiddleware``
    use it — the middleware to recognise machine-token requests and exempt them
    from the org-membership gate.
    """
    raw = os.environ.get(_MACHINE_TOKEN_ENV, "").strip()
    return [raw] if raw else []


def _load_machine_tokens() -> list[tuple[str, AccessToken]]:
    """Load the optional pre-shared machine token from the environment.

    Returns an empty list when ``DISTILLERY_MCP_MACHINE_TOKEN`` is unset — the
    machine-token path is opt-in and off by default, so existing deployments
    are unaffected.

    The token authenticates non-interactive MCP clients (CI workflows) that
    cannot complete the browser-based GitHub OAuth flow. Calls made with it are
    attributed to ``DISTILLERY_MCP_MACHINE_IDENTITY`` via the ``login`` claim —
    the same claim a GitHub OAuth user carries — so authorship and audit keep
    working unchanged.

    The access token carries the ``user`` scope: distillery's GitHub OAuth
    requests that scope, and FastMCP's auth layer enforces it on every verified
    token. A machine token without it is authenticated but then rejected with
    ``403 insufficient_scope`` — so it must present the same scope an
    interactive GitHub OAuth user would.
    """
    values = load_machine_token_values()
    if not values:
        return []
    raw = values[0]
    identity = os.environ.get(_MACHINE_IDENTITY_ENV, "").strip() or _DEFAULT_MACHINE_IDENTITY
    access = AccessToken(
        token=raw,
        client_id=identity,
        scopes=["user"],
        expires_at=None,
        claims={"login": identity, "machine": True},
    )
    logger.info("Machine-token MCP auth enabled (identity=%r)", identity)
    return [(raw, access)]


class _MachineTokenGitHubProvider(GitHubProvider):
    """``GitHubProvider`` that also accepts pre-shared machine tokens.

    Interactive clients authenticate through the GitHub OAuth flow and present
    a FastMCP-issued JWT, which the ``OAuthProxy`` base verifies. Non-interactive
    clients — CI workflows that cannot run the browser OAuth flow — present a
    static pre-shared token instead.

    :meth:`verify_token` checks the configured machine tokens first, with a
    constant-time comparison, and falls through to the OAuth-proxy verification
    otherwise. A machine token is its own credential: possession authorises the
    call, so it does not pass through the GitHub OAuth flow or the
    org-membership gate.
    """

    def __init__(
        self,
        *,
        machine_tokens: list[tuple[str, AccessToken]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._machine_tokens: list[tuple[str, AccessToken]] = machine_tokens or []

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token: machine tokens first, then the OAuth proxy."""
        for candidate, access in self._machine_tokens:
            if hmac.compare_digest(token.encode(), candidate.encode()):
                logger.debug("Authenticated machine token (identity=%s)", access.client_id)
                return access
        return await super().verify_token(token)


class OrgRestrictedGitHubProvider(_MachineTokenGitHubProvider):
    """GitHubProvider subclass that captures user tokens for org membership checks.

    Overrides :meth:`_extract_upstream_claims` to:
    1. Query the GitHub ``/user`` endpoint for the authenticated user's login.
    2. Embed the ``login`` claim in the FastMCP JWT so downstream middleware
       can identify the user without an extra API call.
    3. Call :meth:`OrgMembershipChecker.store_user_token` so private-org
       membership checks can use the user's own OAuth token.

    Inherits the pre-shared machine-token path from
    :class:`_MachineTokenGitHubProvider`; machine tokens skip the OAuth flow and
    the org-membership gate by design.
    """

    def __init__(
        self,
        *,
        org_checker: OrgMembershipChecker,
        client_id: str,
        client_secret: str,
        base_url: str,
        audit_callback: AuditCallback | None = None,
        machine_tokens: list[tuple[str, AccessToken]] | None = None,
    ) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            machine_tokens=machine_tokens,
        )
        self._org_checker = org_checker
        self._audit_callback = audit_callback

    async def _extract_upstream_claims(self, idp_tokens: dict[str, Any]) -> dict[str, Any] | None:
        """Extract GitHub user identity and store the token for org checks."""
        access_token = idp_tokens.get("access_token")
        if not access_token or not isinstance(access_token, str):
            await self._audit("unknown", "auth_login_failed", "missing_or_invalid_access_token")
            return None

        try:
            async with httpx.AsyncClient(timeout=10, verify=True) as client:
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
                    await self._audit(
                        "unknown",
                        "auth_login_failed",
                        f"github_api_status_{resp.status_code}",
                    )
                    return None

                user_data = resp.json()
                login = user_data.get("login", "")
                if login:
                    self._org_checker.store_user_token(login, access_token)
                    logger.debug("Stored user token for %s", login)

                await self._audit(login or "unknown", "auth_login", "success")
                return {
                    "login": login,
                    "name": user_data.get("name"),
                    "email": user_data.get("email"),
                }
        except Exception:
            logger.warning("Error extracting upstream claims", exc_info=True)
            await self._audit("unknown", "auth_login_failed", "exception_during_claims_extraction")
            return None

    async def _audit(self, user: str, operation: str, outcome: str) -> None:
        """Fire the audit callback for an authentication event.

        Emits a best-effort audit log entry for login success or failure.
        Exceptions from the callback are caught and logged at DEBUG level
        so that audit infrastructure issues never block the auth flow.

        Args:
            user: GitHub login of the authenticating user, or ``"unknown"``
                when identity cannot be determined.
            operation: Audit operation name (e.g. ``"auth_login"``,
                ``"auth_login_failed"``).
            outcome: Free-text outcome descriptor (e.g. ``"success"``,
                ``"github_api_status_401"``).

        Note:
            Token refresh (``auth_refresh``) is handled entirely within
            FastMCP's ``OAuthProxy`` layer, which does not expose a hook
            for subclasses.  GitHub OAuth tokens are long-lived and do not
            use refresh tokens, so this event is not emitted here.
            See issue #139 for background.
        """
        if self._audit_callback is None:
            return
        try:
            await self._audit_callback(user, operation, "", operation, outcome)
        except Exception:  # noqa: BLE001
            logger.debug("auth audit_log write failed (ignored)", exc_info=True)


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


# ---------------------------------------------------------------------------
# Pre-register Claude Code as an OAuth client
# ---------------------------------------------------------------------------

# The Claude Code CIMD document at https://claude.ai/oauth/claude-code-client-metadata
# is fetched by FastMCP's CIMDFetcher during the first OAuth handshake.  On some
# Fly.io machines the egress IP is Cloudflare-challenged (HTTP 403), causing the
# fetch to fail and authentication to break.  Pre-registering the well-known
# client metadata on startup bypasses the CIMD fetch entirely.

_CLAUDE_CODE_CLIENT_METADATA = {
    "client_id": "https://claude.ai/oauth/claude-code-client-metadata",
    "client_name": "Claude Code",
    "client_uri": "https://claude.ai",
    "redirect_uris": [
        "http://localhost/callback",
        "http://127.0.0.1/callback",
    ],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
}


async def pre_register_claude_code_client(provider: GitHubProvider) -> None:
    """Seed the OAuth client store with the Claude Code CIMD metadata.

    This avoids a runtime CIMD fetch to ``claude.ai`` which can fail when
    Cloudflare challenges the server's egress IP.

    FastMCP's :meth:`GitHubProvider.register_client` does **not** upsert —
    calling it twice with the same ``client_id`` raises against a persistent
    store. This helper therefore probes the provider for an existing record
    (via :meth:`get_client` when available) and skips registration if the
    Claude Code client is already present. It also swallows the duplicate
    error from providers whose lookup hook is missing so repeated calls
    remain safe during a single process lifetime.
    """
    try:
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyHttpUrl
    except ImportError:
        logger.warning("Cannot pre-register Claude Code client: missing mcp/pydantic")
        return

    meta = _CLAUDE_CODE_CLIENT_METADATA
    client_id = "https://claude.ai/oauth/claude-code-client-metadata"
    get_client = getattr(provider, "get_client", None)
    if callable(get_client):
        try:
            existing = await get_client(client_id)
        except Exception:  # noqa: BLE001
            # A failed client-store lookup is not necessarily fatal (e.g. a
            # newly-provisioned backend or transient connectivity hiccup), but
            # we must not silently swallow it — log with traceback so operators
            # can diagnose real storage failures instead of masking them.
            logger.warning(
                "Claude Code OAuth pre-check failed to query client store; "
                "will attempt registration anyway",
                exc_info=True,
            )
            existing = None
        if existing is not None:
            logger.debug("Claude Code OAuth client already registered; skipping")
            return
    client_info = OAuthClientInformationFull(
        client_id=client_id,
        client_name="Claude Code",
        client_uri=AnyHttpUrl("https://claude.ai"),
        redirect_uris=[
            AnyHttpUrl("http://localhost/callback"),
            AnyHttpUrl("http://127.0.0.1/callback"),
        ],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )
    try:
        await provider.register_client(client_info)
    except Exception as exc:  # noqa: BLE001
        # FastMCP does not expose a stable ClientExistsError — distinguish
        # duplicate-client errors (benign no-op across restarts with a
        # persistent OAuth store) from real registration failures by
        # inspecting the exception message.
        msg = str(exc).lower()
        if any(token in msg for token in ("already exists", "duplicate", "already registered")):
            logger.debug(
                "Pre-registration of Claude Code OAuth client skipped (already exists): %s",
                exc,
            )
            return
        logger.warning(
            "Pre-registration of Claude Code OAuth client failed; "
            "Claude Code onboarding may require a live CIMD fetch",
            exc_info=True,
        )
        return
    logger.info("Pre-registered Claude Code OAuth client (%s)", meta["client_id"])


def build_github_auth(
    config: DistilleryConfig,
    org_checker: OrgMembershipChecker | None = None,
    audit_callback: AuditCallback | None = None,
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

    machine_tokens = _load_machine_tokens()

    if org_checker is not None:
        return OrgRestrictedGitHubProvider(
            org_checker=org_checker,
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            audit_callback=audit_callback,
            machine_tokens=machine_tokens,
        )

    return _MachineTokenGitHubProvider(
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        machine_tokens=machine_tokens,
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
