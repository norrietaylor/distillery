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
        Author field for created entries.  Defaults to ``"gh-sync"``.
    project:
        Optional project name for scoping entries.
    """

    def __init__(
        self,
        store: DistilleryStore,
        url: str,
        token: str | None = None,
        author: str = "gh-sync",
        project: str | None = None,
    ) -> None:
        self._store = store
        self._owner, self._repo = _parse_github_url(url)
        self._token = token or os.environ.get("GITHUB_TOKEN", "")
        self._author = author
        self._project = project
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

        # Build tags from labels using shared sanitiser.
        from distillery.feeds.tags import sanitise_label

        tags: list[str] = [t for lbl in labels if (t := sanitise_label(lbl)) is not None]

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
        }

        return Entry(
            content=content,
            entry_type=EntryType.GITHUB,
            source=EntrySource.IMPORT,
            author=self._author,
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

            # Check for existing entry.
            existing = await self._find_existing(external_id)

            if existing is not None:
                # Update existing entry.
                await self._store.update(
                    existing.id,
                    {
                        "content": entry.content,
                        "metadata": entry.metadata,
                        "tags": entry.tags,
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
            client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True)
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

            # Truncate oversized content before embedding.
            if len(entry.content) > _MAX_CONTENT_LENGTH:
                entry.content = entry.content[:_MAX_CONTENT_LENGTH] + "\n\n[truncated]"

            existing = await self._find_existing(external_id)

            if existing is not None:
                await self._store.update(
                    existing.id,
                    {
                        "content": entry.content,
                        "metadata": entry.metadata,
                        "tags": entry.tags,
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
            client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, follow_redirects=True)

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
