"""Tests for the async sync pipeline and batched storage features.

Covers:
- SyncJobTracker lifecycle (create, mark_running, mark_completed, mark_failed)
- run_sync_job_async background execution
- GitHubSyncAdapter.sync_batched page-at-a-time pipeline
- _handle_store_batch MCP tool handler
- _handle_gh_sync MCP tool handler
- _handle_sync_status MCP tool handler
- SyncResult.to_dict serialisation
- Content truncation for oversized entries
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pytest

from distillery.feeds.github_sync import (
    _MAX_CONTENT_LENGTH,
    GitHubSyncAdapter,
    SyncResult,
)
from distillery.feeds.sync_jobs import (
    SyncJobStatus,
    SyncJobTracker,
    run_sync_job_async,
)
from distillery.mcp.tools.feeds import (
    _handle_gh_sync,
    _handle_store_batch,
    _handle_sync_status,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_issue(
    number: int = 1,
    title: str = "Test issue",
    body: str | None = "Issue body",
    state: str = "open",
    is_pr: bool = False,
    labels: list[dict[str, str]] | None = None,
    assignees: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a mock GitHub issue API response."""
    issue: dict[str, Any] = {
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


def _parse_response(result: list[Any]) -> dict[str, Any]:
    """Extract the JSON payload from an MCP tool response."""
    return json.loads(result[0].text)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# SyncJobTracker unit tests
# ---------------------------------------------------------------------------


class TestSyncJobTracker:
    """Unit tests for the in-memory sync job tracker."""

    @pytest.mark.unit
    def test_create_job(self) -> None:
        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="test/repo", source_type="github")
        assert job.status == SyncJobStatus.PENDING
        assert job.source_url == "test/repo"
        assert job.source_type == "github"
        assert job.job_id

    @pytest.mark.unit
    def test_get_job(self) -> None:
        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="test/repo", source_type="github")
        found = tracker.get_job(job.job_id)
        assert found is job

    @pytest.mark.unit
    def test_get_job_not_found(self) -> None:
        tracker = SyncJobTracker()
        assert tracker.get_job("nonexistent") is None

    @pytest.mark.unit
    def test_list_jobs(self) -> None:
        tracker = SyncJobTracker()
        tracker.create_job(source_url="a/b", source_type="github")
        tracker.create_job(source_url="c/d", source_type="rss")
        jobs = tracker.list_jobs()
        assert len(jobs) == 2

    @pytest.mark.unit
    def test_list_jobs_filtered(self) -> None:
        tracker = SyncJobTracker()
        tracker.create_job(source_url="a/b", source_type="github")
        tracker.create_job(source_url="c/d", source_type="rss")
        jobs = tracker.list_jobs(source_url="a/b")
        assert len(jobs) == 1
        assert jobs[0].source_url == "a/b"

    @pytest.mark.unit
    def test_mark_running(self) -> None:
        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="test/repo", source_type="github")
        tracker.mark_running(job.job_id)
        assert job.status == SyncJobStatus.RUNNING
        assert job.started_at is not None

    @pytest.mark.unit
    def test_mark_completed(self) -> None:
        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="test/repo", source_type="github")
        tracker.mark_running(job.job_id)
        tracker.mark_completed(job.job_id, result={"created": 5})
        assert job.status == SyncJobStatus.COMPLETED
        assert job.completed_at is not None
        assert job.result == {"created": 5}

    @pytest.mark.unit
    def test_mark_failed(self) -> None:
        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="test/repo", source_type="github")
        tracker.mark_running(job.job_id)
        tracker.mark_failed(job.job_id, error="Connection refused")
        assert job.status == SyncJobStatus.FAILED
        assert job.error_message == "Connection refused"
        assert job.completed_at is not None

    @pytest.mark.unit
    def test_job_to_dict(self) -> None:
        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="test/repo", source_type="github")
        d = job.to_dict()
        assert d["job_id"] == job.job_id
        assert d["status"] == "pending"
        assert d["source_url"] == "test/repo"


# ---------------------------------------------------------------------------
# run_sync_job_async tests
# ---------------------------------------------------------------------------


class TestRunSyncJobAsync:
    """Tests for the async job runner."""

    @pytest.mark.unit
    async def test_successful_sync(self) -> None:
        from datetime import UTC, datetime

        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="test/repo", source_type="github")

        async def mock_sync() -> SyncResult:
            return SyncResult(
                repo="test/repo",
                created=3,
                updated=1,
                relations_created=2,
                sync_timestamp=datetime.now(tz=UTC),
                pages_processed=1,
            )

        await run_sync_job_async(job, tracker, mock_sync())
        assert job.status == SyncJobStatus.COMPLETED
        assert job.entries_created == 3
        assert job.entries_updated == 1
        assert job.relations_created == 2

    @pytest.mark.unit
    async def test_failed_sync(self) -> None:
        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="test/repo", source_type="github")

        async def failing_sync() -> SyncResult:
            raise RuntimeError("API down")

        await run_sync_job_async(job, tracker, failing_sync())
        assert job.status == SyncJobStatus.FAILED
        # Error message is sanitized (does not leak exception detail).
        assert job.error_message == "Sync job failed"


# ---------------------------------------------------------------------------
# SyncResult tests
# ---------------------------------------------------------------------------


class TestSyncResult:
    """Tests for the enhanced SyncResult dataclass."""

    @pytest.mark.unit
    def test_to_dict(self) -> None:
        from datetime import UTC, datetime

        result = SyncResult(
            repo="test/repo",
            created=5,
            updated=2,
            relations_created=3,
            sync_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            pages_processed=2,
            errors=["page 3 failed"],
        )
        d = result.to_dict()
        assert d["repo"] == "test/repo"
        assert d["created"] == 5
        assert d["pages_processed"] == 2
        assert d["errors"] == ["page 3 failed"]
        assert "2026" in d["sync_timestamp"]

    @pytest.mark.unit
    def test_default_fields(self) -> None:
        from datetime import UTC, datetime

        result = SyncResult(
            repo="a/b",
            created=0,
            updated=0,
            relations_created=0,
            sync_timestamp=datetime.now(tz=UTC),
        )
        assert result.pages_processed == 0
        assert result.errors == []


# ---------------------------------------------------------------------------
# GitHubSyncAdapter.sync_batched tests
# ---------------------------------------------------------------------------


class TestSyncBatched:
    """Integration tests for the batched sync pipeline."""

    @pytest.mark.integration
    async def test_sync_batched_creates_entries(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Batched sync should store entries page by page."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, title="Batched issue")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        result = await adapter.sync_batched()

        assert result.created == 1
        assert result.pages_processed == 1
        assert result.errors == []

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert len(entries) == 1
        assert "Batched issue" in entries[0].content

    @pytest.mark.integration
    async def test_sync_batched_updates_existing(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Batched sync should update existing entries."""
        # First sync.
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, title="Original")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync_batched()

        # Second sync with updated content.
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, title="Updated")],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        result = await adapter.sync_batched()
        assert result.updated == 1
        assert result.created == 0

    @pytest.mark.integration
    async def test_sync_batched_truncates_oversized_content(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Content exceeding _MAX_CONTENT_LENGTH should be truncated."""
        oversized_body = "x" * (_MAX_CONTENT_LENGTH + 1000)
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1, body=oversized_body)],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        result = await adapter.sync_batched()
        assert result.created == 1

        entries = await store.list_entries(filters={"entry_type": "github"}, limit=10, offset=0)
        assert len(entries[0].content) <= _MAX_CONTENT_LENGTH + 50  # +slack for truncation marker

    @pytest.mark.integration
    async def test_sync_batched_tracks_timestamp(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Batched sync should persist last sync timestamp."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[],
        )

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync_batched()

        last_sync = await store.get_metadata(adapter.metadata_key)
        assert last_sync is not None
        assert "T" in last_sync

    @pytest.mark.integration
    async def test_sync_batched_on_page_callback(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """The on_page callback should be called for each page processed."""
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1)],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        pages_seen: list[int] = []

        def on_page(page_num: int, created: int, updated: int) -> None:
            pages_seen.append(page_num)

        adapter = GitHubSyncAdapter(store=store, url="test/repo")
        await adapter.sync_batched(on_page=on_page)
        assert pages_seen == [1]


# ---------------------------------------------------------------------------
# MCP tool handler tests
# ---------------------------------------------------------------------------


class TestHandleStoreBatch:
    """Tests for the distillery_store_batch tool handler."""

    @pytest.mark.integration
    async def test_batch_store_success(self, store) -> None:  # type: ignore[no-untyped-def]
        entries = [
            {"content": "Entry one", "entry_type": "reference", "author": "tester"},
            {"content": "Entry two", "entry_type": "bookmark", "author": "tester"},
        ]
        result = await _handle_store_batch(store=store, arguments={"entries": entries})
        data = _parse_response(result)
        assert data["stored_count"] == 2
        assert len(data["stored_ids"]) == 2
        assert data["error_count"] == 0

    @pytest.mark.integration
    async def test_batch_store_partial_failure(self, store) -> None:  # type: ignore[no-untyped-def]
        entries = [
            {"content": "Valid entry", "entry_type": "reference"},
            {"content": "", "entry_type": "reference"},  # empty content
            {"entry_type": "reference"},  # missing content
        ]
        result = await _handle_store_batch(store=store, arguments={"entries": entries})
        data = _parse_response(result)
        assert data["stored_count"] == 1
        assert data["error_count"] == 2

    @pytest.mark.unit
    async def test_batch_store_empty_list(self, store) -> None:  # type: ignore[no-untyped-def]
        result = await _handle_store_batch(store=store, arguments={"entries": []})
        data = _parse_response(result)
        assert "error" in data or data.get("error_code")

    @pytest.mark.unit
    async def test_batch_store_invalid_type(self, store) -> None:  # type: ignore[no-untyped-def]
        result = await _handle_store_batch(store=store, arguments={"entries": "not-a-list"})
        data = _parse_response(result)
        assert "error" in data or data.get("error_code")


class TestHandleGhSync:
    """Tests for the distillery_gh_sync tool handler."""

    @pytest.mark.integration
    async def test_sync_success(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[_mock_issue(number=1)],
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/1/comments.*"),
            json=[],
        )

        result = await _handle_gh_sync(store=store, arguments={"url": "test/repo"})
        data = _parse_response(result)
        assert data["created"] == 1
        assert data["pages_processed"] == 1

    @pytest.mark.unit
    async def test_missing_url(self, store) -> None:  # type: ignore[no-untyped-def]
        result = await _handle_gh_sync(store=store, arguments={})
        data = _parse_response(result)
        assert data.get("code") == "MISSING_FIELD"

    @pytest.mark.integration
    async def test_background_mode(self, store, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=[],
        )

        result = await _handle_gh_sync(
            store=store, arguments={"url": "test/repo", "background": True}
        )
        data = _parse_response(result)
        assert "sync_job" in data
        assert data["sync_job"]["status"] == "pending"

        # Let the background task run.
        await asyncio.sleep(0.1)


class TestHandleSyncStatus:
    """Tests for the distillery_sync_status tool handler."""

    @pytest.mark.unit
    async def test_list_all_jobs(self) -> None:

        # Use a fresh tracker for isolation.
        result = await _handle_sync_status(arguments={})
        data = _parse_response(result)
        assert "jobs" in data

    @pytest.mark.unit
    async def test_job_not_found(self) -> None:
        result = await _handle_sync_status(arguments={"job_id": "nonexistent"})
        data = _parse_response(result)
        assert data.get("code") == "NOT_FOUND"
