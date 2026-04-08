"""GitHub repository events adapter.

Polls the GitHub REST API ``GET /repos/{owner}/{repo}/events`` endpoint and
normalises each event to a :class:`~distillery.feeds.models.FeedItem`.

The adapter tracks ``last_polled_at`` so that callers can detect stale state
and implement incremental polling (GitHub returns events in reverse-
chronological order, newest first).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from distillery.feeds.models import FeedItem

logger = logging.getLogger(__name__)

# GitHub REST API base URL.
_GITHUB_API_BASE = "https://api.github.com"

# Default per-page event limit (GitHub max is 100).
_DEFAULT_PER_PAGE = 30

# Request timeout in seconds.
_REQUEST_TIMEOUT = 30.0

# Event types that typically carry meaningful content (issue/PR bodies, comments,
# release notes, commit messages).  Low-value events like WatchEvent, ForkEvent,
# and bare CreateEvent/DeleteEvent are excluded by default because they have
# very short content that dominates BM25 keyword matching (#171).
_DEFAULT_INCLUDE_EVENT_TYPES: frozenset[str] = frozenset({
    "IssuesEvent",
    "IssueCommentEvent",
    "PullRequestEvent",
    "PullRequestReviewEvent",
    "PullRequestReviewCommentEvent",
    "PushEvent",
    "ReleaseEvent",
})

# Pattern that matches a bare "owner/repo" slug so callers may pass either
# the full URL or the short slug form.
_SLUG_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")


def _parse_github_url(url: str) -> tuple[str, str]:
    """Extract ``(owner, repo)`` from a GitHub repository URL or slug.

    Accepts all of the following forms:

    - ``owner/repo``  (bare slug)
    - ``https://github.com/owner/repo``
    - ``https://github.com/owner/repo.git``
    - ``https://api.github.com/repos/owner/repo``

    Args:
        url: GitHub repository URL or ``owner/repo`` slug.

    Returns:
        A ``(owner, repo)`` tuple with any trailing ``.git`` stripped.

    Raises:
        ValueError: If the URL does not match any recognised pattern.
    """
    stripped = url.strip().rstrip("/")
    if stripped.endswith(".git"):
        stripped = stripped[:-4]

    # Bare slug: owner/repo (no protocol)
    if _SLUG_RE.match(stripped):
        owner, repo = stripped.split("/", 1)
        return owner, repo

    # Full URL forms
    for prefix in (
        "https://api.github.com/repos/",
        "http://api.github.com/repos/",
        "https://github.com/",
        "http://github.com/",
    ):
        if stripped.startswith(prefix):
            remainder = stripped[len(prefix) :]
            parts = remainder.split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]

    raise ValueError(
        f"Cannot extract owner/repo from GitHub URL: {url!r}. "
        "Expected a URL like 'https://github.com/owner/repo' or a bare 'owner/repo' slug."
    )


def _event_to_feed_item(event: dict[str, Any], source_url: str) -> FeedItem:
    """Convert a single GitHub events API response object to a :class:`FeedItem`.

    Args:
        event: Parsed JSON object from the GitHub events endpoint.
        source_url: The canonical feed URL (used as ``FeedItem.source_url``).

    Returns:
        A normalised :class:`FeedItem`.
    """
    event_id: str = str(event.get("id", ""))
    event_type: str = str(event.get("type", "Event"))
    repo_info: dict[str, Any] = event.get("repo") or {}
    repo_name: str = str(repo_info.get("name", ""))
    actor_info: dict[str, Any] = event.get("actor") or {}
    actor_login: str = str(actor_info.get("login", ""))
    payload: dict[str, Any] = event.get("payload") or {}

    # Build a human-readable title.
    title = f"{event_type} by {actor_login} on {repo_name}" if actor_login else event_type

    # Item URL: best-effort derivation from payload.
    item_url: str | None = None
    if "issue" in payload and isinstance(payload["issue"], dict):
        item_url = payload["issue"].get("html_url")
    elif "pull_request" in payload and isinstance(payload["pull_request"], dict):
        item_url = payload["pull_request"].get("html_url")
    elif "comment" in payload and isinstance(payload["comment"], dict):
        item_url = payload["comment"].get("html_url")
    elif "release" in payload and isinstance(payload["release"], dict):
        item_url = payload["release"].get("html_url")

    if item_url is None and repo_name:
        item_url = f"https://github.com/{repo_name}"

    # Content: short summary from payload.
    content: str | None = None
    for key in ("description", "body", "message"):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate.strip():
            content = candidate.strip()
            break
    # Fallback: commits list
    if content is None:
        commits = payload.get("commits")
        if isinstance(commits, list) and commits:
            first = commits[0]
            if isinstance(first, dict):
                content = str(first.get("message", ""))

    # Published at
    published_at: datetime | None = None
    created_at_raw = event.get("created_at")
    if isinstance(created_at_raw, str):
        try:
            dt = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            published_at = dt
        except ValueError:
            pass

    return FeedItem(
        source_url=source_url,
        source_type="github",
        item_id=event_id,
        title=title,
        url=item_url,
        content=content or None,
        published_at=published_at,
        raw=event,
        extra={"event_type": event_type, "actor": actor_login, "repo": repo_name},
    )


class GitHubAdapter:
    """Feed adapter that polls GitHub repository events.

    Uses the GitHub REST API ``GET /repos/{owner}/{repo}/events`` endpoint.
    An optional personal access token (PAT) can be supplied to increase the
    rate limit from 60 to 5000 requests/hour.

    Parameters
    ----------
    url:
        Repository URL (``https://github.com/owner/repo``) or bare slug
        (``owner/repo``).
    token:
        Optional GitHub personal access token.  When omitted the adapter
        checks the ``GITHUB_TOKEN`` environment variable.
    per_page:
        Number of events to retrieve per API call (1-100).  Defaults to 30.

    Raises
    ------
    ValueError
        If *url* cannot be parsed as a valid GitHub repository reference.
    """

    def __init__(
        self,
        url: str,
        token: str | None = None,
        per_page: int = _DEFAULT_PER_PAGE,
        include_event_types: frozenset[str] | None = None,
    ) -> None:
        self._owner, self._repo = _parse_github_url(url)
        self._source_url = url
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._per_page = max(1, min(per_page, 100))
        self._include_event_types = (
            include_event_types if include_event_types is not None else _DEFAULT_INCLUDE_EVENT_TYPES
        )
        self.last_polled_at: datetime | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def source_url(self) -> str:
        """The canonical repository URL passed at construction time."""
        return self._source_url

    @property
    def owner(self) -> str:
        """Repository owner extracted from *url*."""
        return self._owner

    @property
    def repo(self) -> str:
        """Repository name extracted from *url*."""
        return self._repo

    def fetch(self) -> list[FeedItem]:
        """Poll the GitHub events endpoint and return normalised items.

        Updates :attr:`last_polled_at` on every successful call (even when
        the response is an empty list).

        Returns:
            A list of :class:`~distillery.feeds.models.FeedItem` objects,
            ordered newest-first as returned by the GitHub API.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses.
            httpx.RequestError: On network-level failures.
        """
        api_url = f"{_GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/events"
        params: dict[str, str | int] = {"per_page": self._per_page}
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        logger.debug("GitHubAdapter: fetching %s", api_url)

        with httpx.Client(timeout=_REQUEST_TIMEOUT, follow_redirects=True) as client:
            response = client.get(api_url, params=params, headers=headers)
            response.raise_for_status()

        self.last_polled_at = datetime.now(tz=UTC)

        events: list[dict[str, Any]] = response.json()
        if not isinstance(events, list):
            logger.warning("GitHubAdapter: unexpected response type %s", type(events).__name__)
            return []

        items: list[FeedItem] = []
        skipped = 0
        for event in events:
            try:
                if not isinstance(event, dict):
                    skipped += 1
                    continue
                event_type = str(event.get("type", ""))
                if self._include_event_types and event_type not in self._include_event_types:
                    skipped += 1
                    continue
                items.append(_event_to_feed_item(event, self._source_url))
            except Exception:
                logger.exception("GitHubAdapter: failed to convert event %r", event.get("id") if isinstance(event, dict) else event)
        if skipped:
            logger.debug("GitHubAdapter: skipped %d low-value events", skipped)
        return items
