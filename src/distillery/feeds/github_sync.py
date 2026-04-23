"""GitHub issue/PR sync adapter for Distillery knowledge capture.

Fetches issues and pull requests from the GitHub REST API and stores them as
``entry_type=github`` entries in the Distillery knowledge base.  Uses
``external_id`` metadata for deduplication, ``store.set_metadata`` for tracking
last sync timestamps, and parses cross-references (``#123``, ``Closes #123``,
``Fixes #123``) to create ``link`` relations between entries.

Unlike :class:`~distillery.feeds.github.GitHubAdapter` which polls the events
stream for ambient monitoring, this adapter performs structured synchronisation
of issue/PR content suitable for deep knowledge capture.

Supports two sync modes:

- :meth:`GitHubSyncAdapter.sync` — original all-at-once sync (retained for
  backward compatibility).
- :meth:`GitHubSyncAdapter.sync_batched` — page-at-a-time pipeline where each
  page of issues is fetched, stored, and cross-referenced independently so that
  partial progress survives failures and long imports do not risk timeouts.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from distillery.models import Entry, EntrySource, EntryStatus, EntryType
from distillery.store.protocol import DistilleryStore

logger = logging.getLogger(__name__)

# GitHub REST API base URL.
_GITHUB_API_BASE = "https://api.github.com"

# Request timeout in seconds.
_REQUEST_TIMEOUT = 30.0

# Maximum comments to include in entry content.
_MAX_COMMENTS = 10

# Per-page limit for the issues endpoint (GitHub max is 100).
_DEFAULT_PER_PAGE = 100

# Maximum total items to fetch across all pages (safety cap).
_MAX_FETCH_ITEMS = 1000

# Maximum retries for transient errors (429 / 5xx).
_MAX_RETRIES = 3

# Maximum content length before truncation (characters).  Oversized entries
# are truncated to avoid exceeding embedding model input limits.
_MAX_CONTENT_LENGTH = 8000

# Pattern for GitHub cross-references in issue/PR bodies and comments.
# Matches: #123, Closes #123, Fixes #123, Resolves #123, closes #123, etc.
_XREF_PATTERN = re.compile(
    r"(?:(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+)?#(\d+)",
    re.IGNORECASE,
)

# Slug pattern for owner/repo.
_SLUG_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")

# Default author attribution when the GitHub payload omits ``user.login``.
_DEFAULT_GH_AUTHOR = "gh-sync"

# Allowed values for the ``state/*`` tag — keeps vocabulary bounded.
_STATE_TAG_VALUES = frozenset({"open", "closed", "merged"})

# Pattern each slash-separated tag segment must satisfy (see models.validate_tag).
_TAG_CHAR_RE = re.compile(r"[^a-z0-9\-]")


def _sanitize_tag_segment(raw: str) -> str:
    """Return a tag segment that satisfies ``[a-z0-9][a-z0-9\\-]*``.

    Lowercases, replaces ``_`` and ``.`` (and any other disallowed characters)
    with ``-``, collapses runs of ``-``, and trims leading/trailing hyphens.
    Digits are permitted in any position (including as the leading character)
    because the tag schema accepts ``[a-z0-9]`` at the start.  Returns an
    empty string when the input cannot be coerced to a valid segment.
    """
    if not raw:
        return ""
    lowered = raw.strip().lower()
    # Replace any disallowed character with a hyphen.
    replaced = _TAG_CHAR_RE.sub("-", lowered)
    # Collapse runs of hyphens and strip leading/trailing hyphens.
    collapsed = re.sub(r"-+", "-", replaced).strip("-")
    return collapsed


def _derive_state_tag_value(issue: dict[str, Any]) -> str | None:
    """Return ``"merged"``/``"closed"``/``"open"`` for the issue, or ``None``.

    For pull requests with ``pull_request.merged_at`` set, returns ``"merged"``.
    Otherwise falls back to the issue's ``state`` field when it is one of
    ``open`` or ``closed``.  Unknown states return ``None``.
    """
    pr_info = issue.get("pull_request")
    if isinstance(pr_info, dict) and pr_info.get("merged_at"):
        return "merged"
    state = issue.get("state")
    if isinstance(state, str) and state.lower() in _STATE_TAG_VALUES:
        return state.lower()
    return None


def _build_github_tags(
    *,
    repo: str,
    ref_type: str,
    issue: dict[str, Any],
    labels: list[str],
) -> list[str]:
    """Assemble the canonical tag list for a GitHub-sourced entry.

    Always includes:
      - ``source/github``
      - ``repo/<sanitised repo>`` (only when the sanitised name is non-empty)
      - ``ref-type/<issue|pr>``
      - ``state/<open|closed|merged>`` (only when resolvable)

    Also appends sanitised GitHub labels (``bug``, ``high-priority``) that
    pass tag-validation; anything that cannot be coerced is silently dropped.
    """
    tags: list[str] = ["source/github"]
    repo_seg = _sanitize_tag_segment(repo)
    if repo_seg:
        tags.append(f"repo/{repo_seg}")
    if ref_type in {"issue", "pr"}:
        tags.append(f"ref-type/{ref_type}")
    state_value = _derive_state_tag_value(issue)
    if state_value is not None:
        tags.append(f"state/{state_value}")
    for label in labels:
        sanitised = _sanitize_tag_segment(label)
        if sanitised:
            tags.append(sanitised)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            unique.append(tag)
    return unique


def _parse_github_url(url: str) -> tuple[str, str]:
    """Extract ``(owner, repo)`` from a GitHub repository URL or slug.

    Accepts:
    - ``owner/repo`` (bare slug)
    - ``https://github.com/owner/repo``
    - ``https://github.com/owner/repo.git``
    - ``https://api.github.com/repos/owner/repo``

    Raises:
        ValueError: If the URL does not match any recognised pattern.
    """
    stripped = url.strip().rstrip("/")
    if stripped.endswith(".git"):
        stripped = stripped[:-4]

    if _SLUG_RE.match(stripped):
        owner, repo = stripped.split("/", 1)
        return owner, repo

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
        "Expected 'https://github.com/owner/repo' or 'owner/repo'."
    )


def _make_external_id(owner: str, repo: str, ref_type: str, number: int) -> str:
    """Build a canonical external_id for deduplication.

    Format: ``{owner}/{repo}#{ref_type}-{number}``
    Example: ``norrietaylor/distillery#issue-42``
    """
    return f"{owner}/{repo}#{ref_type}-{number}"


def _extract_cross_refs(text: str) -> list[int]:
    """Extract unique cross-reference issue/PR numbers from text.

    Parses patterns like ``#123``, ``Closes #456``, ``fixes #789``.

    Returns:
        Sorted list of unique issue/PR numbers found.
    """
    if not text:
        return []
    numbers = {int(m.group(1)) for m in _XREF_PATTERN.finditer(text)}
    return sorted(numbers)


def _build_content(
    title: str,
    body: str | None,
    comments: list[dict[str, Any]],
) -> str:
    """Concatenate title, body, and first 10 comments (chronological order) into entry content."""
    parts = [f"# {title}"]
    if body and body.strip():
        parts.append(body.strip())
    for comment in comments[:_MAX_COMMENTS]:
        author = comment.get("user", {}).get("login", "unknown")
        comment_body = comment.get("body", "")
        if comment_body and comment_body.strip():
            parts.append(f"**{author}**: {comment_body.strip()}")
    return "\n\n".join(parts)


class GitHubSyncAdapter:
    """Structured sync adapter for GitHub issues and pull requests.

    Fetches issues/PRs from the GitHub REST API, converts them to Distillery
    entries with ``entry_type=github``, and stores them using the provided
    :class:`DistilleryStore`.  Tracks sync state via ``store.set_metadata``
    and creates ``link`` relations for cross-references.

    Parameters
    ----------
    store:
        The Distillery store instance for persistence.
    url:
        Repository URL or ``owner/repo`` slug.
    token:
        Optional GitHub PAT.  Falls back to ``GITHUB_TOKEN`` env var.
    author:
        Optional override for the entry author.  When ``None`` (the default)
        each entry's author is derived from the GitHub payload's
        ``user.login`` field, falling back to ``"gh-sync"``.
    project:
        Optional project name for scoping entries.  When ``None`` the adapter
        uses the bare repository name (e.g. ``"distillery"``) so synced
        entries are filterable by the same project value that ``/distill``
        and friends assign via ``basename $(git rev-parse --show-toplevel)``.
    """

    def __init__(
        self,
        store: DistilleryStore,
        url: str,
        token: str | None = None,
        author: str | None = None,
        project: str | None = None,
    ) -> None:
        self._store = store
        self._owner, self._repo = _parse_github_url(url)
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._author_override = author
        # Default project to the bare repo name so git-derived filters line up
        # with entries created via /distill, /bookmark, etc.
        self._project = project if project is not None else self._repo
        self._metadata_key = f"gh_sync_last_{self._owner}/{self._repo}"

    @property
    def owner(self) -> str:
        """Repository owner."""
        return self._owner

    @property
    def repo(self) -> str:
        """Repository name."""
        return self._repo

    @property
    def metadata_key(self) -> str:
        """Store metadata key used to track last sync timestamp."""
        return self._metadata_key

    def _headers(self) -> dict[str, str]:
        """Build HTTP headers for GitHub API requests."""
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str | int],
    ) -> httpx.Response:
        """GET with retry on rate-limit (403/429) and transient 5xx errors."""
        for attempt in range(_MAX_RETRIES + 1):
            response = await client.get(url, params=params, headers=self._headers())
            if response.status_code == 429 or (
                response.status_code == 403 and "rate limit" in response.text.lower()
            ):
                retry_after = response.headers.get("Retry-After")
                reset = response.headers.get("X-RateLimit-Reset")
                if retry_after:
                    wait = float(retry_after)
                elif reset:
                    wait = max(0.0, float(reset) - datetime.now(UTC).timestamp())
                else:
                    wait = 2.0**attempt
                wait = min(wait, 60.0)
                logger.warning(
                    "GitHub rate limited (attempt %d/%d), waiting %.0fs",
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    wait,
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(wait)
                    continue
            if response.status_code >= 500 and attempt < _MAX_RETRIES:
                wait = 2.0**attempt
                logger.warning(
                    "GitHub %d (attempt %d/%d), retrying in %.0fs",
                    response.status_code,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            return response
        # Unreachable, but satisfies type checker.
        response.raise_for_status()
        return response  # pragma: no cover

    async def _fetch_issues(
        self,
        since: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch issues (includes PRs) from the GitHub REST API.

        Parameters
        ----------
        since:
            ISO 8601 timestamp for incremental sync.  Only issues updated
            after this time are returned.
        client:
            Optional pre-built httpx client (for testing).
        """
        api_url = f"{_GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/issues"
        params: dict[str, str | int] = {
            "state": "all",
            "per_page": _DEFAULT_PER_PAGE,
            "sort": "updated",
            "direction": "desc",
        }
        if since:
            params["since"] = since

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True, verify=True)
        try:
            all_issues: list[dict[str, Any]] = []
            page = 1
            while len(all_issues) < _MAX_FETCH_ITEMS:
                params["page"] = page
                response = await self._request_with_retry(client, api_url, params)
                batch: list[dict[str, Any]] = response.json()
                if not isinstance(batch, list):
                    break
                all_issues.extend(batch)
                if len(batch) < _DEFAULT_PER_PAGE:
                    break
                page += 1
            return all_issues[:_MAX_FETCH_ITEMS]
        finally:
            if should_close:
                await client.aclose()

    async def _fetch_comments(
        self,
        number: int,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch comments for a specific issue/PR.

        Parameters
        ----------
        number:
            Issue or PR number.
        client:
            Optional pre-built httpx client (for testing).
        """
        api_url = f"{_GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/issues/{number}/comments"
        params: dict[str, str | int] = {"per_page": _MAX_COMMENTS}

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True, verify=True)
        try:
            response = await self._request_with_retry(client, api_url, params)
            result: list[dict[str, Any]] = response.json()
            return result if isinstance(result, list) else []
        finally:
            if should_close:
                await client.aclose()

    def _issue_to_entry(
        self,
        issue: dict[str, Any],
        comments: list[dict[str, Any]],
    ) -> Entry:
        """Convert a GitHub issue/PR API response to an Entry.

        Parameters
        ----------
        issue:
            Parsed JSON from the GitHub issues endpoint.
        comments:
            List of comment objects for this issue/PR.

        Returns
        -------
        Entry
            A Distillery entry with ``entry_type=github``.
        """
        is_pr = "pull_request" in issue
        ref_type = "pr" if is_pr else "issue"
        number: int = issue.get("number", 0)
        title: str = issue.get("title", "")
        body: str | None = issue.get("body")
        state: str = issue.get("state", "unknown")
        html_url: str = issue.get("html_url", "")
        labels = [
            lbl.get("name", "") for lbl in (issue.get("labels") or []) if isinstance(lbl, dict)
        ]
        assignees = [
            a.get("login", "") for a in (issue.get("assignees") or []) if isinstance(a, dict)
        ]

        external_id = _make_external_id(self._owner, self._repo, ref_type, number)
        content = _build_content(title, body, comments)

        # Canonical tag set (source/github, repo/<repo>, ref-type/<type>,
        # state/<state>) plus any sanitised GitHub labels.
        tags = _build_github_tags(
            repo=self._repo,
            ref_type=ref_type,
            issue=issue,
            labels=labels,
        )

        # Derive author from the GitHub payload when the caller hasn't pinned
        # an override — otherwise gh-sync entries show up with no attribution.
        # Treat null, empty, and whitespace-only logins as missing so we fall
        # back to the configured sync-tool author instead of persisting junk.
        # Capture the raw GitHub login separately so metadata["user_login"]
        # always reflects the payload author (not an override), which lets
        # ``_compute_backfill_updates`` recover attribution later.
        gh_login: str | None = None
        user = issue.get("user")
        if isinstance(user, dict):
            raw_login = user.get("login")
            if isinstance(raw_login, str) and raw_login.strip():
                gh_login = raw_login.strip()

        author = self._author_override or gh_login
        if not author:
            author = _DEFAULT_GH_AUTHOR

        # Merged-at timestamp (PRs only) — preserved so _compute_backfill_updates
        # can detect merged PRs during backfill and keep the state/merged tag.
        merged_at: str | None = None
        if isinstance(pr_info := issue.get("pull_request"), dict):
            pr_merged = pr_info.get("merged_at")
            if isinstance(pr_merged, str) and pr_merged:
                merged_at = pr_merged
        if merged_at is None:
            top_merged = issue.get("merged_at")
            if isinstance(top_merged, str) and top_merged:
                merged_at = top_merged

        metadata: dict[str, Any] = {
            "repo": f"{self._owner}/{self._repo}",
            "ref_type": ref_type,
            "ref_number": number,
            "title": title,
            "url": html_url,
            "state": state,
            "labels": labels,
            "assignees": assignees,
            "external_id": external_id,
            "imported_by": "gh-sync",
            # Convenience duplicates requested by #312 — some downstream
            # consumers (UI, digests) look for these specific keys rather
            # than ref_number / url.
            "gh_number": number,
            "gh_url": html_url,
            "merged_at": merged_at,
            # Persisted so ``_compute_backfill_updates`` can heal older entries
            # that lost author attribution (see legacy_authors branch below).
            # Store the raw GitHub login (or ``None`` when missing) so an
            # ``author_override`` cannot permanently overwrite the payload
            # author in metadata.
            "user_login": gh_login,
        }

        return Entry(
            content=content,
            entry_type=EntryType.GITHUB,
            source=EntrySource.IMPORT,
            author=author,
            project=self._project,
            tags=tags,
            status=EntryStatus.ACTIVE,
            metadata=metadata,
        )

    async def _find_existing(self, external_id: str) -> Entry | None:
        """Look up an existing entry by external_id metadata.

        Returns the first matching entry, or None.
        """
        entries = await self._store.list_entries(
            filters={"entry_type": "github", "metadata.external_id": external_id},
            limit=1,
            offset=0,
        )
        return entries[0] if entries else None

    async def _create_cross_ref_relations(
        self,
        entry_id: str,
        cross_refs: list[int],
    ) -> list[str]:
        """Create link relations for cross-referenced issues/PRs.

        For each referenced issue number, looks up the corresponding entry
        by external_id and creates a ``link`` relation if found.

        Returns:
            List of created relation IDs.
        """
        relation_ids: list[str] = []
        for ref_number in cross_refs:
            # Try both issue and PR external IDs.
            for ref_type in ("issue", "pr"):
                ext_id = _make_external_id(self._owner, self._repo, ref_type, ref_number)
                target = await self._find_existing(ext_id)
                if target is not None:
                    try:
                        rel_id = await self._store.add_relation(
                            from_id=entry_id,
                            to_id=target.id,
                            relation_type="link",
                        )
                        relation_ids.append(rel_id)
                        logger.debug(
                            "Created link relation %s -> %s (ref #%d)",
                            entry_id,
                            target.id,
                            ref_number,
                        )
                    except ValueError:
                        logger.warning(
                            "Failed to create relation %s -> %s",
                            entry_id,
                            target.id,
                        )
                    break  # Found it, no need to check other ref_type.
        return relation_ids

    async def sync(
        self,
        client: httpx.AsyncClient | None = None,
    ) -> SyncResult:
        """Synchronise issues and PRs from GitHub to the knowledge base.

        Performs incremental sync using the last sync timestamp stored in
        the metadata table.  New issues/PRs are created as entries; existing
        ones (matched by external_id) are updated.

        Parameters
        ----------
        client:
            Optional pre-built httpx client (for testing/injection).

        Returns
        -------
        SyncResult
            Summary of the sync operation.
        """
        # Determine last sync time.
        last_sync = await self._store.get_metadata(self._metadata_key)
        sync_start = datetime.now(tz=UTC)

        issues = await self._fetch_issues(since=last_sync, client=client)
        logger.info(
            "GitHubSyncAdapter: fetched %d issues/PRs for %s/%s",
            len(issues),
            self._owner,
            self._repo,
        )

        created = 0
        updated = 0
        relations_created: list[str] = []
        # Collect pending cross-refs to resolve after all items are stored.
        pending_xrefs: list[tuple[str, list[int]]] = []

        for issue in issues:
            number = issue.get("number", 0)
            is_pr = "pull_request" in issue
            ref_type = "pr" if is_pr else "issue"
            external_id = _make_external_id(self._owner, self._repo, ref_type, number)

            # Fetch comments.
            try:
                comments = await self._fetch_comments(number, client=client)
            except httpx.HTTPError:
                logger.warning("Failed to fetch comments for %s #%d", external_id, number)
                comments = []

            entry = self._issue_to_entry(issue, comments)

            # Apply the same content cap used by sync_batched() so oversized
            # issue bodies don't bypass the embedding-model input limit here.
            if len(entry.content) > _MAX_CONTENT_LENGTH:
                marker = "\n\n[truncated]"
                cutoff = max(0, _MAX_CONTENT_LENGTH - len(marker))
                entry.content = entry.content[:cutoff] + marker

            # Check for existing entry.
            existing = await self._find_existing(external_id)

            if existing is not None:
                # Update existing entry.  Also backfill project/author so
                # previously-synced items pick up the real payload author
                # (#302) and the canonical project/tags (#312) on the next
                # sync cycle even without a one-off backfill run.
                await self._store.update(
                    existing.id,
                    {
                        "content": entry.content,
                        "author": entry.author,
                        "metadata": entry.metadata,
                        "tags": entry.tags,
                        "project": entry.project,
                    },
                )
                entry_id = existing.id
                updated += 1
            else:
                # Store new entry.
                entry_id = await self._store.store(entry)
                created += 1

            # Parse cross-references; defer resolution until all items stored.
            all_text = entry.content
            cross_refs = _extract_cross_refs(all_text)
            # Exclude self-references.
            cross_refs = [r for r in cross_refs if r != number]
            if cross_refs:
                pending_xrefs.append((entry_id, cross_refs))

        # Second pass: resolve cross-references now that all items are stored.
        for entry_id, cross_refs in pending_xrefs:
            new_rels = await self._create_cross_ref_relations(entry_id, cross_refs)
            relations_created.extend(new_rels)

        # Update last sync timestamp.
        await self._store.set_metadata(self._metadata_key, sync_start.isoformat())

        result = SyncResult(
            repo=f"{self._owner}/{self._repo}",
            created=created,
            updated=updated,
            relations_created=len(relations_created),
            sync_timestamp=sync_start,
        )
        logger.info("GitHubSyncAdapter: sync complete — %s", result)
        return result

    async def _fetch_issues_page(
        self,
        page: int,
        since: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch a single page of issues from the GitHub REST API.

        Parameters
        ----------
        page:
            1-based page number.
        since:
            ISO 8601 timestamp for incremental sync.
        client:
            Optional pre-built httpx client.

        Returns
        -------
        list[dict[str, Any]]
            A list of issue dicts (may be empty if no more pages).
        """
        api_url = f"{_GITHUB_API_BASE}/repos/{self._owner}/{self._repo}/issues"
        params: dict[str, str | int] = {
            "state": "all",
            "per_page": _DEFAULT_PER_PAGE,
            "sort": "updated",
            "direction": "desc",
            "page": page,
        }
        if since:
            params["since"] = since

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True, verify=True)
        try:
            response = await self._request_with_retry(client, api_url, params)
            batch: list[dict[str, Any]] = response.json()
            if not isinstance(batch, list):
                return []
            return batch
        finally:
            if should_close:
                await client.aclose()

    async def _process_issue_batch(
        self,
        issues: list[dict[str, Any]],
        client: httpx.AsyncClient | None = None,
    ) -> tuple[int, int, list[tuple[str, list[int]]]]:
        """Store or update a batch of issues and return (created, updated, pending_xrefs).

        Each issue in the batch is processed individually: comments are
        fetched, the content is truncated if oversized, and the entry is
        created or updated.

        Returns
        -------
        tuple[int, int, list[tuple[str, list[int]]]]
            ``(created_count, updated_count, pending_xref_pairs)``
        """
        created = 0
        updated = 0
        pending_xrefs: list[tuple[str, list[int]]] = []

        for issue in issues:
            number = issue.get("number", 0)
            is_pr = "pull_request" in issue
            ref_type = "pr" if is_pr else "issue"
            external_id = _make_external_id(self._owner, self._repo, ref_type, number)

            try:
                comments = await self._fetch_comments(number, client=client)
            except httpx.HTTPError:
                logger.warning("Failed to fetch comments for %s #%d", external_id, number)
                comments = []

            entry = self._issue_to_entry(issue, comments)

            # Truncate oversized content before embedding. Reserve space for
            # the truncation marker so the final length never exceeds the cap.
            if len(entry.content) > _MAX_CONTENT_LENGTH:
                marker = "\n\n[truncated]"
                cutoff = max(0, _MAX_CONTENT_LENGTH - len(marker))
                entry.content = entry.content[:cutoff] + marker

            existing = await self._find_existing(external_id)

            if existing is not None:
                # Include ``author`` and ``project`` on update so re-syncs
                # correct stale tool-authored entries (#302) and pick up the
                # canonical project/tag backfill (#312) without a one-off run.
                await self._store.update(
                    existing.id,
                    {
                        "content": entry.content,
                        "author": entry.author,
                        "metadata": entry.metadata,
                        "tags": entry.tags,
                        "project": entry.project,
                    },
                )
                entry_id = existing.id
                updated += 1
            else:
                entry_id = await self._store.store(entry)
                created += 1

            cross_refs = _extract_cross_refs(entry.content)
            cross_refs = [r for r in cross_refs if r != number]
            if cross_refs:
                pending_xrefs.append((entry_id, cross_refs))

        return created, updated, pending_xrefs

    async def sync_batched(
        self,
        client: httpx.AsyncClient | None = None,
        on_page: Any | None = None,
    ) -> SyncResult:
        """Synchronise issues/PRs using a page-at-a-time batched pipeline.

        Each page of issues (up to 100 items) is fetched, stored, and
        cross-referenced independently.  This means partial progress
        survives failures and long imports do not risk MCP timeouts.

        Parameters
        ----------
        client:
            Optional pre-built httpx client (for testing/injection).
        on_page:
            Optional callback ``(page_num: int, created: int, updated: int) -> None``
            called after each page is committed.  Used by the sync job tracker
            to update progress.

        Returns
        -------
        SyncResult
            Summary of the batched sync operation.
        """
        last_sync = await self._store.get_metadata(self._metadata_key)
        sync_start = datetime.now(tz=UTC)

        total_created = 0
        total_updated = 0
        all_pending_xrefs: list[tuple[str, list[int]]] = []
        all_relations: list[str] = []
        pages_processed = 0
        errors: list[str] = []

        should_close = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True, verify=True)

        try:
            page = 1
            total_fetched = 0
            while total_fetched < _MAX_FETCH_ITEMS:
                try:
                    batch = await self._fetch_issues_page(page, since=last_sync, client=client)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Page {page} fetch failed: {exc}")
                    logger.warning("GitHubSyncAdapter: page %d fetch failed: %s", page, exc)
                    break

                if not batch:
                    break

                total_fetched += len(batch)

                try:
                    created, updated, pending_xrefs = await self._process_issue_batch(
                        batch, client=client
                    )
                    total_created += created
                    total_updated += updated
                    all_pending_xrefs.extend(pending_xrefs)
                    pages_processed += 1

                    if on_page is not None:
                        on_page(page, created, updated)

                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Page {page} processing failed: {exc}")
                    logger.warning("GitHubSyncAdapter: page %d processing failed: %s", page, exc)

                if len(batch) < _DEFAULT_PER_PAGE:
                    break
                page += 1

            # Second pass: resolve cross-references.
            for entry_id, cross_refs in all_pending_xrefs:
                try:
                    new_rels = await self._create_cross_ref_relations(entry_id, cross_refs)
                    all_relations.extend(new_rels)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Cross-ref resolution failed for {entry_id}: {exc}")
        finally:
            if should_close:
                await client.aclose()

        # Only advance the sync cursor when the run completed cleanly. If any
        # page fetch, batch processing, or cross-ref resolution recorded an
        # error, preserve the previous cursor so older items on failed pages
        # are retried on the next incremental run.
        if not errors:
            await self._store.set_metadata(self._metadata_key, sync_start.isoformat())

        result = SyncResult(
            repo=f"{self._owner}/{self._repo}",
            created=total_created,
            updated=total_updated,
            relations_created=len(all_relations),
            sync_timestamp=sync_start,
            pages_processed=pages_processed,
            errors=errors,
        )
        logger.info("GitHubSyncAdapter: batched sync complete — %s", result)
        return result


@dataclass
class SyncResult:
    """Summary of a GitHub sync operation."""

    repo: str
    """The ``owner/repo`` string."""
    created: int
    """Number of new entries created."""
    updated: int
    """Number of existing entries updated."""
    relations_created: int
    """Number of cross-reference link relations created."""
    sync_timestamp: datetime
    """UTC timestamp when the sync started."""
    pages_processed: int = 0
    """Number of pages fetched and committed (batched mode only)."""
    errors: list[str] = field(default_factory=list)
    """Error messages encountered during sync."""

    def __repr__(self) -> str:
        return (
            f"SyncResult(repo={self.repo!r}, created={self.created}, "
            f"updated={self.updated}, relations={self.relations_created})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for job tracking and MCP responses."""
        return {
            "repo": self.repo,
            "created": self.created,
            "updated": self.updated,
            "relations_created": self.relations_created,
            "sync_timestamp": self.sync_timestamp.isoformat(),
            "pages_processed": self.pages_processed,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Backfill helper (#312)
# ---------------------------------------------------------------------------


# How many entries to scan per page when walking the store.
_BACKFILL_PAGE_SIZE = 200


def _infer_repo_slug(metadata: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(owner, repo)`` inferred from entry metadata, or ``(None, None)``.

    Tries ``metadata["repo"]`` first (stored as ``owner/repo``), then falls
    back to ``metadata["external_id"]`` which has the form
    ``owner/repo#issue-42``.
    """
    repo_raw = metadata.get("repo")
    if isinstance(repo_raw, str) and "/" in repo_raw:
        owner, _, repo = repo_raw.partition("/")
        if owner and repo:
            return owner, repo.split("#", 1)[0]

    external_id = metadata.get("external_id")
    if isinstance(external_id, str) and "/" in external_id:
        slug, _, _ = external_id.partition("#")
        owner, _, repo = slug.partition("/")
        if owner and repo:
            return owner, repo

    return None, None


async def backfill_github_metadata(
    store: DistilleryStore,
    *,
    page_size: int = _BACKFILL_PAGE_SIZE,
    dry_run: bool = False,
) -> int:
    """Backfill project/tags/author/metadata on existing ``github`` entries.

    Scans all entries with ``entry_type=github`` and fills in the canonical
    metadata added in #312 without re-fetching from GitHub:

    - ``project`` defaults to the bare repo name (``distillery``) when unset
      or empty.
    - ``tags`` are replaced with the canonical set
      (``source/github``, ``repo/<name>``, ``ref-type/<type>``,
      ``state/<state>``) plus any existing sanitised labels, when the entry's
      current tag list is empty or missing any canonical tag.
    - ``author`` is populated from the entry's own metadata when the stored
      author is empty or the legacy ``"gh-sync"`` placeholder and we can
      recover a real GitHub login.
    - ``metadata.gh_number`` and ``metadata.gh_url`` are populated from the
      existing ``ref_number`` / ``url`` fields when absent.

    The helper does *not* call GitHub; all source-of-truth data must already
    be present on the entry.  Entries without recoverable repo/ref_type
    metadata are skipped.

    Args:
        store: The Distillery store to scan and update.
        page_size: Number of entries to fetch per ``list_entries`` call.
        dry_run: When ``True`` no writes are performed; the function still
            returns the number of entries that *would* have been updated.

    Returns:
        The number of entries that were updated (or would be, for dry runs).
    """
    if page_size <= 0:
        raise ValueError(f"page_size must be positive, got {page_size}")

    updated = 0
    offset = 0
    while True:
        batch = await store.list_entries(
            filters={"entry_type": EntryType.GITHUB.value},
            limit=page_size,
            offset=offset,
        )
        if not batch:
            break

        for entry in batch:
            updates = _compute_backfill_updates(entry)
            if not updates:
                continue
            updated += 1
            if not dry_run:
                await store.update(entry.id, updates)

        if len(batch) < page_size:
            break
        offset += len(batch)

    return updated


def _compute_backfill_updates(entry: Entry) -> dict[str, Any]:
    """Return the update dict needed to bring *entry* up to the #312 schema.

    Returns an empty dict when no changes are needed.  Splitting this logic
    out keeps :func:`backfill_github_metadata` easy to reason about and
    lets tests exercise the per-entry decisions without a store.
    """
    metadata = dict(entry.metadata or {})
    owner, repo = _infer_repo_slug(metadata)

    # Without repo info we cannot build canonical tags reliably.  Leave the
    # entry alone rather than guessing.
    if owner is None or repo is None:
        return {}

    ref_type_raw = metadata.get("ref_type")
    ref_type = ref_type_raw if isinstance(ref_type_raw, str) else ""

    updates: dict[str, Any] = {}

    # ``project`` — prefer the repo name when the stored value is empty.
    if not entry.project:
        updates["project"] = repo

    # ``author`` — only replace when the existing value is empty or the
    # legacy placeholder, and only when metadata gives us a real login.
    legacy_authors = {"", _DEFAULT_GH_AUTHOR}
    if entry.author in legacy_authors:
        stored_login = metadata.get("user_login")
        if isinstance(stored_login, str) and stored_login.strip():
            updates["author"] = stored_login.strip()

    # ``metadata.gh_number`` / ``metadata.gh_url`` — copy from the legacy
    # ``ref_number`` / ``url`` keys when missing.
    metadata_changed = False
    if "gh_number" not in metadata and isinstance(metadata.get("ref_number"), int):
        metadata["gh_number"] = metadata["ref_number"]
        metadata_changed = True
    if "gh_url" not in metadata and isinstance(metadata.get("url"), str):
        metadata["gh_url"] = metadata["url"]
        metadata_changed = True

    # ``tags`` — rebuild the canonical set.  We preserve any existing
    # non-canonical tags (hand-authored labels, etc.) by merging them in.
    issue_like: dict[str, Any] = {
        "state": metadata.get("state"),
    }
    # Re-create the ``pull_request.merged_at`` signal for PR entries that
    # were already closed at sync time.
    if ref_type == "pr" and isinstance(metadata.get("merged_at"), str):
        issue_like["pull_request"] = {"merged_at": metadata["merged_at"]}
    stored_labels_raw = metadata.get("labels") or []
    stored_labels = [lbl for lbl in stored_labels_raw if isinstance(lbl, str)]

    canonical_tags = _build_github_tags(
        repo=repo,
        ref_type=ref_type,
        issue=issue_like,
        labels=stored_labels,
    )
    # Merge with any existing tags we don't already know about.
    existing_tags = list(entry.tags or [])
    seen: set[str] = set(canonical_tags)
    merged_tags = list(canonical_tags)
    for tag in existing_tags:
        if tag not in seen:
            seen.add(tag)
            merged_tags.append(tag)
    if merged_tags != existing_tags:
        updates["tags"] = merged_tags

    if metadata_changed:
        updates["metadata"] = metadata

    return updates
