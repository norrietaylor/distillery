"""GitHub org membership checking with TTL cache.

Used by the HTTP transport to restrict access to members of one or more
GitHub organisations after the OAuth flow completes.

Token resolution order for API calls (most- to least-preferred):
1. Token stored via :meth:`OrgMembershipChecker.store_user_token` — captured
   during the OAuth callback so the user's own token is used (handles private
   orgs with ``read:org`` scope).
2. *server_token* passed at construction (env-var ``GITHUB_ORG_CHECK_TOKEN``)
   — a server-side PAT with ``read:org`` scope.
3. Unauthenticated — works only for **public** org membership.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# JWT helper
# ---------------------------------------------------------------------------


def _try_decode_jwt_claims(token: str) -> dict[str, Any] | None:
    """Attempt to decode a JWT payload without signature verification.

    Returns the claims dict when *token* is a well-formed JWT, ``None``
    otherwise.  Used to extract the ``login`` claim from a FastMCP access
    token so that the ASGI middleware can identify the requesting user without
    a round-trip to GitHub.

    Security note: this function does **not** verify the signature.
    FastMCP has already verified the token before the middleware sees it;
    we are only reading the claims that FastMCP put there.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # Add base64 padding if necessary.
        payload_b64 = parts[1]
        padding = (4 - len(payload_b64) % 4) % 4
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * padding))
        if isinstance(payload, dict):
            return payload
        return None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    is_member: bool
    expires_at: float  # monotonic timestamp


# ---------------------------------------------------------------------------
# OrgMembershipChecker
# ---------------------------------------------------------------------------


class OrgMembershipChecker:
    """Checks GitHub org membership, caching results with a configurable TTL.

    Args:
        allowed_orgs: GitHub organisation login names (slugs) to check.
            A user must be a member of **at least one** to be allowed.
            Empty list means open access (checker is disabled).
        cache_ttl_seconds: How long to cache membership results (seconds).
            Default is 3600 (1 hour).
        server_token: Optional server-side GitHub PAT with ``read:org``
            scope, used when no user token is available.  Falls back to
            unauthenticated API calls if ``None``.
    """

    def __init__(
        self,
        allowed_orgs: list[str],
        cache_ttl_seconds: int = 3600,
        server_token: str | None = None,
    ) -> None:
        # Deduplicate while preserving insertion order.
        self._allowed_orgs: list[str] = list(dict.fromkeys(allowed_orgs))
        self._ttl = cache_ttl_seconds
        self._server_token = server_token
        # (username, org) -> CacheEntry
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._lock = asyncio.Lock()
        # username -> (github_token, stored_at_monotonic)
        self._user_tokens: dict[str, tuple[str, float]] = {}

    @property
    def enabled(self) -> bool:
        """``True`` when org restrictions are configured."""
        return bool(self._allowed_orgs)

    @property
    def allowed_orgs(self) -> list[str]:
        """Return the list of allowed GitHub org slugs (read-only copy)."""
        return list(self._allowed_orgs)

    # ------------------------------------------------------------------
    # User-token store
    # ------------------------------------------------------------------

    def store_user_token(self, username: str, github_token: str) -> None:
        """Cache the user's own GitHub OAuth token.

        Called by :class:`OrgRestrictedGitHubProvider` after the OAuth
        callback so that per-request membership checks can use the user's
        token (required for private-org membership visibility).
        """
        self._user_tokens[username] = (github_token, time.monotonic())

    def _resolve_token(self, username: str, hint_token: str | None) -> str | None:
        """Return the best available GitHub token for *username*.

        Priority:
        1. *hint_token* (explicit caller-supplied token — e.g. extracted
           from the current Bearer header when FastMCP uses token passthrough).
        2. Stored user token (not yet expired).
        3. Server token (*server_token* constructor arg).
        4. ``None`` — unauthenticated; only public org membership visible.
        """
        if hint_token:
            return hint_token

        entry = self._user_tokens.get(username)
        if entry is not None:
            token, stored_at = entry
            if time.monotonic() - stored_at <= self._ttl:
                return token
            del self._user_tokens[username]

        return self._server_token  # may be None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def is_allowed(self, username: str, hint_token: str | None = None) -> bool:
        """Return ``True`` if *username* is a member of at least one allowed org.

        Short-circuits on the first positive match across ``allowed_orgs``.
        Always returns ``True`` when ``allowed_orgs`` is empty (open-access mode).

        Args:
            username: GitHub login name.
            hint_token: Optional GitHub token to use for this check.
                Falls back to stored user token then server token.
        """
        if not self._allowed_orgs:
            return True

        token = self._resolve_token(username, hint_token)
        now = time.monotonic()

        for org in self._allowed_orgs:
            if await self._check_org(token, username, org, now):
                return True
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _check_org(
        self,
        token: str | None,
        username: str,
        org: str,
        now: float,
    ) -> bool:
        """Return cached or freshly-fetched membership result for one org."""
        async with self._lock:
            key = (username, org)
            entry = self._cache.get(key)
            if entry is not None and now < entry.expires_at:
                logger.debug(
                    "Membership cache hit: %s in %s -> %s",
                    username,
                    org,
                    entry.is_member,
                )
                return entry.is_member

        # Fetch outside the lock to avoid blocking other coroutines.
        result = await self._fetch_membership(token, username, org)

        async with self._lock:
            self._cache[(username, org)] = _CacheEntry(
                is_member=result,
                expires_at=now + self._ttl,
            )

        logger.info(
            "Org membership check: %s in %s -> %s (cached %ds)",
            username,
            org,
            result,
            self._ttl,
        )
        return result

    async def _fetch_membership(
        self,
        token: str | None,
        username: str,
        org: str,
    ) -> bool:
        """Call ``GET /orgs/{org}/members/{username}``.

        Response codes:
        * 204 — member.
        * 404 — not a member (or org does not exist).
        * 302 — org is private and the token cannot see it; fall back to
          ``GET /user/orgs`` if a token is available.
        * anything else / network error — fail closed (deny).
        """
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                resp = await client.get(
                    f"{GITHUB_API}/orgs/{org}/members/{username}",
                    headers=headers,
                )
            if resp.status_code == 204:
                return True
            if resp.status_code == 404:
                return False
            if resp.status_code == 302:
                if token:
                    return await self._fetch_via_user_orgs(token, org)
                logger.warning(
                    "Org %r is private but no GitHub token is available for the "
                    "/user/orgs fallback. Set GITHUB_ORG_CHECK_TOKEN or enable "
                    "read:org scope on the OAuth app.",
                    org,
                )
                return False
            logger.warning(
                "Unexpected GitHub API status %s checking %s in %s",
                resp.status_code,
                username,
                org,
            )
            return False
        except httpx.HTTPError as exc:
            logger.error(
                "GitHub membership API error for %s in %s: %s",
                username,
                org,
                exc,
            )
            return False

    async def _fetch_via_user_orgs(self, token: str, org: str) -> bool:
        """Fallback: ``GET /user/orgs`` — lists all orgs the user belongs to.

        Used when ``GET /orgs/{org}/members/{username}`` returns 302 (private
        org; token cannot see direct member list).  The user's own token with
        ``read:org`` scope *can* list their private org memberships here.
        """
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{GITHUB_API}/user/orgs",
                    headers=headers,
                    params={"per_page": 100},
                )
            if resp.status_code != 200:
                logger.warning("GET /user/orgs returned %s", resp.status_code)
                return False
            orgs: list[dict[str, Any]] = resp.json()
            return any(o.get("login", "").lower() == org.lower() for o in orgs)
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("GitHub /user/orgs API error: %s", exc)
            return False
