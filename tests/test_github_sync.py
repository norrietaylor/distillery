"""Tests for GitHubSyncAdapter — GitHub issue/PR sync to knowledge base.

Uses mock HTTP responses to avoid hitting the real GitHub API.
"""

from __future__ import annotations

import re

import pytest

from distillery.feeds.github_sync import (
    _MAX_RETRIES,
    GitHubSyncAdapter,
    SyncResult,
    _build_content,
    _extract_cross_refs,
    _make_external_id,
    _parse_github_url,
)
from distillery.models import EntryType

# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------


class TestParseGitHubUrl:
    """Test URL/slug parsing."""

    @pytest.mark.unit
    def test_bare_slug(self) -> None:
        assert _parse_github_url("owner/repo") == ("owner", "repo")

    @pytest.mark.unit
    def test_https_url(self) -> None:
        assert _parse_github_url("https://github.com/owner/repo") == ("owner", "repo")

    @pytest.mark.unit
    def test_https_url_with_git_suffix(self) -> None:
        assert _parse_github_url("https://github.com/owner/repo.git") == ("owner", "repo")

    @pytest.mark.unit
    def test_api_url(self) -> None:
        assert _parse_github_url("https://api.github.com/repos/owner/repo") == ("owner", "repo")

    @pytest.mark.unit
    def test_invalid_url_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot extract"):
            _parse_github_url("not-a-valid-url")


class TestMakeExternalId:
    """Test external_id generation."""

    @pytest.mark.unit
    def test_issue_format(self) -> None:
        assert _make_external_id("owner", "repo", "issue", 42) == "owner/repo#issue-42"

    @pytest.mark.unit
    def test_pr_format(self) -> None:
        assert _make_external_id("owner", "repo", "pr", 7) == "owner/repo#pr-7"


class TestExtractCrossRefs:
    """Test cross-reference parsing."""

    @pytest.mark.unit
    def test_simple_ref(self) -> None:
        assert _extract_cross_refs("See #123 for details") == [123]

    @pytest.mark.unit
    def test_closes_ref(self) -> None:
        assert _extract_cross_refs("Closes #456") == [456]

    @pytest.mark.unit
    def test_fixes_ref(self) -> None:
        assert _extract_cross_refs("fixes #789") == [789]

    @pytest.mark.unit
    def test_resolves_ref(self) -> None:
        assert _extract_cross_refs("Resolves #10") == [10]

    @pytest.mark.unit
    def test_multiple_refs(self) -> None:
        text = "Fixes #1, closes #2, see also #3"
        assert _extract_cross_refs(text) == [1, 2, 3]

    @pytest.mark.unit
    def test_duplicate_refs_deduped(self) -> None:
        text = "#5 and also #5"
        assert _extract_cross_refs(text) == [5]

    @pytest.mark.unit
    def test_empty_text(self) -> None:
        assert _extract_cross_refs("") == []

    @pytest.mark.unit
    def test_no_refs(self) -> None:
        assert _extract_cross_refs("No references here") == []


class TestBuildContent:
    """Test content concatenation."""

    @pytest.mark.unit
    def test_title_only(self) -> None:
        result = _build_content("My Title", None, [])
        assert result == "# My Title"

    @pytest.mark.unit
    def test_title_and_body(self) -> None:
        result = _build_content("Title", "Body text", [])
        assert "# Title" in result
        assert "Body text" in result

    @pytest.mark.unit
    def test_with_comments(self) -> None:
        comments = [
            {"user": {"login": "alice"}, "body": "Comment 1"},
            {"user": {"login": "bob"}, "body": "Comment 2"},
        ]
        result = _build_content("Title", "Body", comments)
        assert "**alice**: Comment 1" in result
        assert "**bob**: Comment 2" in result

    @pytest.mark.unit
    def test_max_comments_limit(self) -> None:
        comments = [{"user": {"login": f"user{i}"}, "body": f"Comment {i}"} for i in range(15)]
        result = _build_content("Title", None, comments)
        assert "user9" in result
        assert "user10" not in result


# ---------------------------------------------------------------------------
# Mock GitHub API responses
# ---------------------------------------------------------------------------


def _mock_issue(
    number: int = 1,
    title: str = "Test issue",
    body: str | None = "Issue body",
    state: str = "open",
    is_pr: bool = False,
    labels: list[dict[str, str]] | None = None,
    assignees: list[dict[str, str]] | None = None,
) -> dict:
    """Build a mock GitHub issue API response."""
    issue: dict = {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "html_url": f"https://github.com/test/repo/issues/{number}",
        "labels": labels or [],
        "assignees": assignees or [],
        "user": {"login": "author"},
    }
    if is_pr:
        issue["pull_request"] = {"url": f"https://api.github.com/repos/test/repo/pulls/{number}"}
    return issue


def _mock_comment(author: str = "commenter", body: str = "A comment") -> dict:
    """Build a mock GitHub comment API response."""
    return {"user": {"login": author}, "body": body}


# ---------------------------------------------------------------------------
# Integration tests — GitHubSyncAdapter with mock HTTP
# ---------------------------------------------------------------------------


class TestGitHubSyncAdapterInit:
    """Test adapter initialization."""

    @pytest.mark.unit
    async def test_slug_parsing(self, store) -> None:  # type: ignore[no-untyped-def]
        adapter = GitHubSyncAdapter(store=store, url="owner/repo")
        assert adapter.owner == "owner"
        assert adapter.repo == "repo"

    @pytest.mark.unit
    async def test_metadata_key(self, store) -> None:  # type: ignore[no-untyped-def]
        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        assert adapter.metadata_key == "gh_sync_last_test/repo"


class TestGitHubSyncAdapterSync:
    """Test the sync workflow with mock API responses."""

    @pytest.mark.integration
    async def test_sync_creates_new_entries(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """New issues should create github entries."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, title="First issue")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[_mock_comment()],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo", project="test-project")
        result = await adapter.sync()

        assert isinstance(result, SyncResult)
        assert result.created == 1
        assert result.updated == 0

        # Verify entry was stored.
        entries = await store.list_entries(
            filters={"entry_type": "github"},
            limit=10,
            offset=0,
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry.entry_type == EntryType.GITHUB
        assert entry.metadata["ref_type"] == "issue"
        assert entry.metadata["ref_number"] == 1
        assert entry.metadata["external_id"] == "test/repo#issue-1"
        assert entry.project == "test-project"
        assert "First issue" in entry.content
        assert "A comment" in entry.content

    @pytest.mark.integration
    async def test_sync_creates_pr_entries(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """PRs should have ref_type=pr."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=5, title="My PR", is_pr=True)],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/5/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        result = await adapter.sync()

        assert result.created == 1
        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert entries[0].metadata["ref_type"] == "pr"
        assert entries[0].metadata["external_id"] == "test/repo#pr-5"

    @pytest.mark.integration
    async def test_sync_updates_existing_entries(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Re-syncing the same issue should update, not duplicate."""
        # First sync.
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, title="Original title")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        result1 = await adapter.sync()
        assert result1.created == 1

        # Second sync with updated title.
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, title="Updated title")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        result2 = await adapter.sync()
        assert result2.created == 0
        assert result2.updated == 1

        # Should still be exactly one entry.
        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert len(entries) == 1
        assert "Updated title" in entries[0].content

    @pytest.mark.integration
    async def test_sync_tracks_last_sync_timestamp(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Sync should persist last sync timestamp via store metadata."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        assert await store.get_metadata(adapter.metadata_key) is None

        await adapter.sync()

        last_sync = await store.get_metadata(adapter.metadata_key)
        assert last_sync is not None
        # Should be a valid ISO timestamp.
        assert "T" in last_sync

    @pytest.mark.integration
    async def test_sync_creates_cross_ref_relations(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Cross-references (#N) should create link relations."""
        # Sync issue #1 first (the target of the cross-reference).
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, title="Target issue")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync()

        # Sync issue #2 that references #1.
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=2, title="Referencing issue", body="Fixes #1")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/2/comments.*"),
            json=[],
        )

        result = await adapter.sync()
        assert result.relations_created == 1

        # Verify the relation was stored.
        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        # Find the referencing entry.
        ref_entry = next(e for e in entries if e.metadata["ref_number"] == 2)
        relations = await store.get_related(ref_entry.id, direction="outgoing")
        assert len(relations) == 1
        assert relations[0]["relation_type"] == "link"

    @pytest.mark.integration
    async def test_sync_handles_labels_as_tags(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Issue labels should become entry tags (lowercase, sanitised)."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[
                _mock_issue(
                    number=1,
                    labels=[{"name": "bug"}, {"name": "high-priority"}],
                )
            ],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync()

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert "bug" in entries[0].tags
        assert "high-priority" in entries[0].tags

    @pytest.mark.integration
    async def test_sync_skips_self_references(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """An issue referencing its own number should not create a relation."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=3, title="Self ref", body="See #3")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/3/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        result = await adapter.sync()
        assert result.relations_created == 0

    @pytest.mark.integration
    async def test_sync_result_repr(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """SyncResult should have a useful repr."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        result = await adapter.sync()
        repr_str = repr(result)
        assert "test/repo" in repr_str
        assert "created=0" in repr_str

    @pytest.mark.integration
    async def test_sync_comment_fetch_failure_graceful(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """If comment fetch fails, sync should still create the entry."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1)],
        )
        # Provide enough 500 responses for all retry attempts.
        for _ in range(_MAX_RETRIES + 1):
            httpx_mock.add_response(
                url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
                status_code=500,
            )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        result = await adapter.sync()
        assert result.created == 1
