"""GitLab OIDC authentication for the Distillery MCP HTTP transport.

Provides :func:`build_gitlab_auth`, which returns a :class:`GitLabProvider` —
a FastMCP ``OIDCProxy`` configured against a GitLab instance's OpenID Connect
(OIDC) discovery document. Works with self-hosted GitLab and gitlab.com.

**Authentication model:** GitLab is an identity gate only, exactly like the
GitHub provider. Scopes ``openid profile email`` are requested; the server
never accesses the user's GitLab projects or other resources.

**Group gating (ADR-0001):** authorization reads the ``groups`` claim from
GitLab's userinfo endpoint once, at login, and bakes the allowed/denied
result into the FastMCP-issued token — there is no GitLab equivalent of
``OrgMembershipChecker`` and no per-request GitLab API call. A user matching
no allowed group gets no identity claims embedded, and :meth:`verify_token`
fails closed on every request. Group removal therefore takes effect at token
expiry; the fastest lockout lever is blocking the user in GitLab, which
prevents new logins and token refresh (nothing revokes an issued token
instantly).

GitLab OAuth access tokens are opaque (not JWTs), so the proxy verifies the
OIDC ``id_token`` against the instance's JWKS instead
(``verify_id_token=True``).
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.oidc_proxy import OIDCProxy

from distillery.config import DistilleryConfig
from distillery.mcp.auth import _load_machine_tokens, match_machine_token
from distillery.mcp.types import AuditCallback

logger = logging.getLogger(__name__)

_OIDC_SCOPES = ["openid", "profile", "email"]


def matches_allowed_groups(user_groups: list[str], allowed_groups: list[str]) -> bool:
    """Return ``True`` if any user group falls inside an allowed group's subtree.

    Matching is by path segment: allowed group ``acme`` matches ``acme`` and
    ``acme/dev`` but not ``acme-corp``. An empty *allowed_groups* means open
    access (instance login is the boundary) and always matches.
    """
    if not allowed_groups:
        return True
    for group in user_groups:
        norm = group.strip().strip("/")
        for allowed in allowed_groups:
            if norm == allowed or norm.startswith(allowed + "/"):
                return True
    return False


class GitLabProvider(OIDCProxy):
    """OIDC proxy for a GitLab instance with claim-based group gating.

    Overrides :meth:`_extract_upstream_claims` to fetch the userinfo endpoint,
    map GitLab's ``nickname`` (username) onto the ``login`` claim — the single
    identity namespace shared with the GitHub provider — and evaluate the
    ``groups`` claim against *allowed_groups* with subtree matching.

    A group-mismatched login is audited and gets **no** claims embedded;
    :meth:`verify_token` then rejects every request carrying that token
    because it has no ``login`` (fail closed).

    Also accepts pre-shared machine tokens, identical to the GitHub path.
    """

    def __init__(
        self,
        *,
        instance_url: str,
        client_id: str,
        client_secret: str,
        base_url: str,
        allowed_groups: list[str] | None = None,
        audit_callback: AuditCallback | None = None,
        machine_tokens: list[tuple[str, AccessToken]] | None = None,
    ) -> None:
        super().__init__(
            config_url=f"{instance_url.rstrip('/')}/.well-known/openid-configuration",
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            # GitLab access tokens are opaque; verify the id_token via JWKS.
            verify_id_token=True,
            required_scopes=_OIDC_SCOPES,
        )
        self._instance_url = instance_url.rstrip("/")
        self._allowed_groups = list(allowed_groups or [])
        self._audit_callback = audit_callback
        self._machine_tokens: list[tuple[str, AccessToken]] = machine_tokens or []

    async def _extract_upstream_claims(self, idp_tokens: dict[str, Any]) -> dict[str, Any] | None:
        """Fetch GitLab userinfo, gate on groups, and map identity claims."""
        access_token = idp_tokens.get("access_token")
        if not access_token or not isinstance(access_token, str):
            await self._audit("unknown", "auth_login_failed", "missing_or_invalid_access_token")
            return None

        userinfo_url = (
            str(self.oidc_config.userinfo_endpoint)
            if self.oidc_config.userinfo_endpoint
            else f"{self._instance_url}/oauth/userinfo"
        )
        try:
            async with httpx.AsyncClient(timeout=10, verify=True) as client:
                resp = await client.get(
                    userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if resp.status_code != 200:
                logger.warning(
                    "Failed to fetch GitLab userinfo during OAuth exchange: %d",
                    resp.status_code,
                )
                await self._audit(
                    "unknown", "auth_login_failed", f"gitlab_userinfo_status_{resp.status_code}"
                )
                return None

            user_data = resp.json()
            login = str(user_data.get("nickname") or "")
            raw_groups = user_data.get("groups") or []
            groups = [str(g) for g in raw_groups if isinstance(g, str)]

            if not login:
                await self._audit("unknown", "auth_login_failed", "missing_nickname_claim")
                return None

            if not matches_allowed_groups(groups, self._allowed_groups):
                logger.info(
                    "GitLab login denied for %s: no membership in allowed groups %s",
                    login,
                    self._allowed_groups,
                )
                await self._audit(login, "auth_group_denied", "denied")
                # No claims embedded -> verify_token fails closed on every
                # request made with this token.
                return None

            await self._audit(login, "auth_login", "success")
            return {
                "login": login,
                "name": user_data.get("name"),
                "email": user_data.get("email"),
                "groups": groups,
            }
        except Exception:
            logger.warning("Error extracting GitLab upstream claims", exc_info=True)
            await self._audit("unknown", "auth_login_failed", "exception_during_claims_extraction")
            return None

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify a bearer token: machine tokens, then OIDC proxy, then the gate.

        The OIDC proxy nests the claims from
        :meth:`_extract_upstream_claims` under ``claims["upstream_claims"]``;
        the rest of the codebase (middleware, tool handlers) reads ``login``
        at the top level, so promote them. A verified token without a
        ``login`` claim — including one issued to a group-denied user — is
        rejected.
        """
        machine_access = match_machine_token(self._machine_tokens, token)
        if machine_access is not None:
            return machine_access

        access = await super().verify_token(token)
        if access is None:
            return None

        claims = access.claims or {}
        upstream = claims.get("upstream_claims")
        if isinstance(upstream, dict):
            claims = {**upstream, **{k: v for k, v in claims.items() if k != "upstream_claims"}}
            access.claims = claims

        login = claims.get("login")
        if not (isinstance(login, str) and login.strip()):
            logger.debug("Rejecting verified GitLab token without login claim (fail closed)")
            return None
        return access

    async def _audit(self, user: str, operation: str, outcome: str) -> None:
        """Fire the audit callback for an authentication event (best-effort)."""
        if self._audit_callback is None:
            return
        try:
            await self._audit_callback(user, operation, "", operation, outcome)
        except Exception:  # noqa: BLE001
            logger.debug("auth audit_log write failed (ignored)", exc_info=True)


def build_gitlab_auth(
    config: DistilleryConfig,
    audit_callback: AuditCallback | None = None,
) -> GitLabProvider:
    """Build a :class:`GitLabProvider` from config and environment.

    Reads the OAuth application ID and secret from the environment variable
    names in ``config.server.auth`` (same keys the GitHub path uses), the
    GitLab instance from ``config.server.auth.instance_url``, and the public
    server URL from ``DISTILLERY_BASE_URL``.

    Raises:
        ValueError: If a required environment variable is missing or invalid.
    """
    auth = config.server.auth
    client_id = os.environ.get(auth.client_id_env, "").strip()
    client_secret = os.environ.get(auth.client_secret_env, "").strip()

    if not client_id:
        raise ValueError(
            f"GitLab OAuth application ID env var {auth.client_id_env!r} is not set or empty. "
            "Set the environment variable before starting the server."
        )
    if not client_secret:
        raise ValueError(
            f"GitLab OAuth secret env var {auth.client_secret_env!r} is not set or empty. "
            "Set the environment variable before starting the server."
        )

    base_url = os.environ.get("DISTILLERY_BASE_URL", "").strip()
    if not base_url:
        raise ValueError(
            "DISTILLERY_BASE_URL env var is required when server.auth.provider is 'gitlab'. "
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
        "Configuring GitLab OIDC (instance_url=%s, client_id_env=%s, base_url=%s, "
        "allowed_groups=%s)",
        auth.instance_url,
        auth.client_id_env,
        base_url,
        auth.allowed_groups or "<open: instance login>",
    )

    return GitLabProvider(
        instance_url=auth.instance_url,
        client_id=client_id,
        client_secret=client_secret,
        base_url=base_url,
        allowed_groups=auth.allowed_groups,
        audit_callback=audit_callback,
        machine_tokens=_load_machine_tokens(),
    )
