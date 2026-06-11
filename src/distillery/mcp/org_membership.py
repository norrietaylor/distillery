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
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# Hard cap on the membership and user-token caches. Both caches are keyed by
# request-supplied values, so a fixed cap with oldest-first eviction keeps
# memory bounded regardless of how many distinct keys are seen.
_MAX_CACHE_ENTRIES = 1024


# ---------------------------------------------------------------------------
# JWT helper
# ---------------------------------------------------------------------------


def _try_decode_jwt_claims(token: str) -> dict[str, Any] | None:
    """Attempt to decode a JWT payload without signature verification.

    Returns the claims dict when *token* is a well-formed JWT, ``None``
    otherwise.  Used to extract the ``login`` claim from a FastMCP access
    token so that the ASGI middleware can identify the requesting user without
    a round-trip to GitHub.

    Security note: this function does **not** verify the JWT signature, and in
    the current ASGI wiring it runs *before* FastMCP verifies the token. The
    ``login`` / ``sub`` claim it returns is therefore caller-controlled and
    must only feed lookups whose results are bounded and fail-closed — never be
    treated as a trusted identity. FastMCP performs the authoritative signature
    check at the inner layer, so request handlers never run for an unverified
    token.
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


class _IndeterminateMembershipError(Exception):
    """Raised when membership cannot be determined (transient/unknown error).

    Distinguishes a *definitive* "not a member" (GitHub 404) from a
    fail-closed denial caused by a transient condition — a network error or
    an unexpected status such as 5xx / rate-limit.  The caller treats both as
    "deny" for the current request, but only definitive results are cached:
    caching a transient denial would lock a legitimate member out for the
    full TTL after GitHub recovers.
    """


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
        # (username, org) -> CacheEntry. Bounded at _MAX_CACHE_ENTRIES with
        # oldest-first eviction so caller-supplied usernames cannot grow it
        # without limit.
        self._cache: OrderedDict[tuple[str, str], _CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        # username -> (github_token, stored_at_monotonic). Bounded the same way.
        self._user_tokens: OrderedDict[str, tuple[str, float]] = OrderedDict()

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
        self._user_tokens.move_to_end(username)
        while len(self._user_tokens) > _MAX_CACHE_ENTRIES:
            self._user_tokens.popitem(last=False)

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
        key = (username, org)
        async with self._lock:
            entry = self._cache.get(key)
            if entry is not None and now < entry.expires_at:
                self._cache.move_to_end(key)
                logger.debug(
                    "Membership cache hit: %s in %s -> %s",
                    username,
                    org,
                    entry.is_member,
                )
                return entry.is_member

        # Fetch outside the lock to avoid blocking other coroutines.  A
        # transient/unknown error fails closed (deny) for *this* request but
        # must NOT be cached — otherwise a momentary GitHub blip would lock a
        # legitimate member out for the full TTL.
        try:
            result = await self._fetch_membership(token, username, org)
        except _IndeterminateMembershipError:
            return False

        async with self._lock:
            self._cache[key] = _CacheEntry(
                is_member=result,
                expires_at=now + self._ttl,
            )
            self._cache.move_to_end(key)
            # Evict oldest entries once the cache exceeds its hard cap.
            while len(self._cache) > _MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False)

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
        * 302 — the token is not seen as an org member, so GitHub will only
          answer the public-membership endpoint; follow there via
          :meth:`_fetch_public_member`.
        * anything else / network error — indeterminate; raise
          :class:`_IndeterminateMembershipError` so the caller fails closed for
          this request *without* caching the denial.
        """
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(
                timeout=10.0, follow_redirects=False, verify=True
            ) as client:
                resp = await client.get(
                    f"{GITHUB_API}/orgs/{org}/members/{username}",
                    headers=headers,
                )
            if resp.status_code == 204:
                return True
            if resp.status_code == 404:
                return False
            if resp.status_code == 302:
                # The token lacks org-member context, so GitHub redirects to
                # the public-membership endpoint. Follow there — a public
                # member resolves with no token scope at all.
                return await self._fetch_public_member(username, org)
            logger.warning(
                "Unexpected GitHub API status %s checking %s in %s",
                resp.status_code,
                username,
                org,
            )
            raise _IndeterminateMembershipError
        except httpx.HTTPError as exc:
            logger.error(
                "GitHub membership API error for %s in %s: %s",
                username,
                org,
                exc,
            )
            raise _IndeterminateMembershipError from exc

    async def _fetch_public_member(self, username: str, org: str) -> bool:
        """Call ``GET /orgs/{org}/public_members/{username}``.

        Reached when ``GET /orgs/{org}/members/{username}`` returns 302 — the
        token is not seen as an org member, so GitHub will only confirm
        *public* membership. This endpoint needs no token or scope.

        * 204 — the user is a public member of the org.
        * 404 — not a public member. A *private* membership is invisible
          here; to gate private members, set ``GITHUB_ORG_CHECK_TOKEN`` (a
          ``read:org`` PAT) so the members endpoint answers 204/404 directly.
        * anything else / network error — indeterminate; raise
          :class:`_IndeterminateMembershipError` so the caller fails closed for
          this request *without* caching the denial.
        """
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            async with httpx.AsyncClient(
                timeout=10.0, follow_redirects=False, verify=True
            ) as client:
                resp = await client.get(
                    f"{GITHUB_API}/orgs/{org}/public_members/{username}",
                    headers=headers,
                )
            if resp.status_code == 204:
                return True
            if resp.status_code == 404:
                return False
            logger.warning(
                "Unexpected GitHub API status %s on public_members for %s in %s",
                resp.status_code,
                username,
                org,
            )
            raise _IndeterminateMembershipError
        except httpx.HTTPError as exc:
            logger.error(
                "GitHub public_members API error for %s in %s: %s",
                username,
                org,
                exc,
            )
            raise _IndeterminateMembershipError from exc
