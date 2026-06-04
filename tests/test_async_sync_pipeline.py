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
from distillery.mcp.tools.crud import _handle_store_batch
from distillery.mcp.tools.feeds import (
    _handle_gh_sync,
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
# SyncJobTracker DuckDB persistence tests
# ---------------------------------------------------------------------------


def _count_sync_jobs(store: Any, job_id: str) -> int:
    """Helper: count rows in sync_jobs for a given job_id."""
    row = store.connection.execute(
        "SELECT COUNT(*) FROM sync_jobs WHERE job_id = ?", [job_id]
    ).fetchone()
    return int(row[0])


def _fetch_sync_job_row(store: Any, job_id: str) -> dict[str, Any] | None:
    """Helper: return the sync_jobs row for a given job_id as a dict."""
    row = store.connection.execute(
        """SELECT job_id, source_url, source_type, status, entries_created,
                  entries_updated, pages_processed, error_message, result, errors
           FROM sync_jobs WHERE job_id = ?""",
        [job_id],
    ).fetchone()
    if row is None:
        return None
    return {
        "job_id": row[0],
        "source_url": row[1],
        "source_type": row[2],
        "status": row[3],
        "entries_created": row[4],
        "entries_updated": row[5],
        "pages_processed": row[6],
        "error_message": row[7],
        "result": row[8],
        "errors": row[9],
    }


class TestSyncJobTrackerPersistence:
    """Write-through persistence and restart hydration."""

    @pytest.mark.integration
    async def test_create_job_writes_row(self, store) -> None:  # type: ignore[no-untyped-def]
        tracker = SyncJobTracker(store=store)
        job = tracker.create_job(source_url="owner/repo", source_type="github")
        row = _fetch_sync_job_row(store, job.job_id)
        assert row is not None
        assert row["status"] == "pending"
        assert row["source_url"] == "owner/repo"
        assert row["source_type"] == "github"

    @pytest.mark.integration
    async def test_state_transitions_persist(self, store) -> None:  # type: ignore[no-untyped-def]
        tracker = SyncJobTracker(store=store)
        job = tracker.create_job(source_url="owner/repo", source_type="github")

        tracker.mark_running(job.job_id)
        row = _fetch_sync_job_row(store, job.job_id)
        assert row is not None
        assert row["status"] == "running"

        tracker.mark_completed(job.job_id, result={"created": 3, "updated": 1})
        row = _fetch_sync_job_row(store, job.job_id)
        assert row is not None
        assert row["status"] == "completed"
        assert row["result"] is not None
        assert json.loads(row["result"])["created"] == 3

    @pytest.mark.integration
    async def test_mark_failed_persists_error(self, store) -> None:  # type: ignore[no-untyped-def]
        tracker = SyncJobTracker(store=store)
        job = tracker.create_job(source_url="owner/repo", source_type="github")
        tracker.mark_running(job.job_id)
        tracker.mark_failed(job.job_id, error="API down")
        row = _fetch_sync_job_row(store, job.job_id)
        assert row is not None
        assert row["status"] == "failed"
        assert row["error_message"] == "API down"

    @pytest.mark.integration
    async def test_update_progress_accumulates(self, store) -> None:  # type: ignore[no-untyped-def]
        tracker = SyncJobTracker(store=store)
        job = tracker.create_job(source_url="owner/repo", source_type="github")
        tracker.update_progress(job.job_id, pages_processed=1, created_delta=5, updated_delta=2)
        tracker.update_progress(job.job_id, pages_processed=2, created_delta=3, updated_delta=0)

        row = _fetch_sync_job_row(store, job.job_id)
        assert row is not None
        assert row["pages_processed"] == 2
        assert row["entries_created"] == 8  # 5 + 3
        assert row["entries_updated"] == 2  # 2 + 0

    @pytest.mark.integration
    async def test_attach_store_after_construction(self, store) -> None:  # type: ignore[no-untyped-def]
        """attach_store() after construction lights up persistence."""
        tracker = SyncJobTracker()  # no store yet
        job = tracker.create_job(source_url="a/b", source_type="github")
        assert _count_sync_jobs(store, job.job_id) == 0  # no persistence yet

        tracker.attach_store(store)
        # Subsequent transitions should persist the full snapshot.
        tracker.mark_running(job.job_id)
        row = _fetch_sync_job_row(store, job.job_id)
        assert row is not None
        assert row["status"] == "running"

    @pytest.mark.integration
    async def test_persistence_failure_is_silent(
        self,
        store,  # type: ignore[no-untyped-def]
        caplog,  # type: ignore[no-untyped-def]
    ) -> None:
        """A DB error during persistence must not abort the in-memory update."""
        tracker = SyncJobTracker(store=store)
        job = tracker.create_job(source_url="a/b", source_type="github")

        # Force a persistence error by dropping the table between transitions.
        store.connection.execute("DROP TABLE sync_jobs")
        caplog.clear()
        # Should not raise — in-memory state still updates.
        tracker.mark_running(job.job_id)
        assert tracker.get_job(job.job_id).status == SyncJobStatus.RUNNING  # type: ignore[union-attr]
        assert any("failed to persist snapshot" in rec.message.lower() for rec in caplog.records)

    @pytest.mark.integration
    async def test_hydrate_no_op_without_store(self) -> None:
        tracker = SyncJobTracker()
        interrupted = await tracker.hydrate()
        assert interrupted == 0

    @pytest.mark.integration
    async def test_hydrate_marks_running_as_interrupted(self, store) -> None:  # type: ignore[no-untyped-def]
        """Jobs with status=running at hydrate-time are reconciled as failed."""
        # Seed the DB directly to simulate a pre-restart running job.
        from datetime import UTC, datetime

        job_id = "seeded-running-job"
        store.connection.execute(
            """INSERT INTO sync_jobs
               (job_id, source_url, source_type, status, created_at,
                started_at, entries_created, entries_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                job_id,
                "owner/repo",
                "github",
                "running",
                datetime.now(tz=UTC),
                datetime.now(tz=UTC),
                2,
                0,
            ],
        )

        tracker = SyncJobTracker(store=store)
        interrupted = await tracker.hydrate()
        assert interrupted == 1

        # Verify both the in-memory copy and the persisted row are updated.
        job = tracker.get_job(job_id)
        assert job is not None
        assert job.status == SyncJobStatus.FAILED
        assert job.error_message == "interrupted by server restart"
        assert job.entries_created == 2  # preserved partial progress

        row = _fetch_sync_job_row(store, job_id)
        assert row is not None
        assert row["status"] == "failed"
        assert row["error_message"] == "interrupted by server restart"

    @pytest.mark.integration
    async def test_hydrate_preserves_completed_jobs(self, store) -> None:  # type: ignore[no-untyped-def]
        """Completed jobs survive hydration unchanged and are visible via get_job."""
        from datetime import UTC, datetime

        job_id = "seeded-completed-job"
        store.connection.execute(
            """INSERT INTO sync_jobs
               (job_id, source_url, source_type, status, created_at,
                completed_at, entries_created, entries_updated, result)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                job_id,
                "owner/repo",
                "github",
                "completed",
                datetime.now(tz=UTC),
                datetime.now(tz=UTC),
                7,
                2,
                json.dumps({"created": 7, "updated": 2}),
            ],
        )

        tracker = SyncJobTracker(store=store)
        interrupted = await tracker.hydrate()
        assert interrupted == 0

        job = tracker.get_job(job_id)
        assert job is not None
        assert job.status == SyncJobStatus.COMPLETED
        assert job.entries_created == 7
        assert job.result == {"created": 7, "updated": 2}


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

    @pytest.mark.unit
    async def test_successful_sync_records_liveness_on_store(self) -> None:
        """After a successful bulk sync the store receives ``record_poll_status``.

        Regression test for issue #334: feeds added with ``sync_history=True``
        were never reaching ``FeedPoller.poll`` so ``last_polled_at`` stayed
        ``NULL``.  ``run_sync_job_async`` now writes liveness directly when a
        store is provided.
        """
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock

        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="owner/repo", source_type="github")
        store = AsyncMock()

        async def mock_sync() -> SyncResult:
            return SyncResult(
                repo="owner/repo",
                created=5,
                updated=2,
                relations_created=1,
                sync_timestamp=datetime.now(tz=UTC),
                pages_processed=1,
            )

        await run_sync_job_async(job, tracker, mock_sync(), store)
        store.record_poll_status.assert_awaited_once()
        call = store.record_poll_status.call_args
        assert call.args[0] == "owner/repo"
        # Liveness item_count sums created + updated: the source is alive so
        # long as it produced any activity.
        assert call.kwargs["item_count"] == 7
        assert call.kwargs["error"] is None

    @pytest.mark.unit
    async def test_failed_sync_records_liveness_error(self) -> None:
        """A failed bulk sync must still update ``last_error`` on the store."""
        from unittest.mock import AsyncMock

        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="owner/repo", source_type="github")
        store = AsyncMock()

        async def failing_sync() -> SyncResult:
            raise RuntimeError("API down")

        await run_sync_job_async(job, tracker, failing_sync(), store)
        store.record_poll_status.assert_awaited_once()
        call = store.record_poll_status.call_args
        assert call.args[0] == "owner/repo"
        assert call.kwargs["error"] == "Sync job failed"

    @pytest.mark.unit
    async def test_liveness_persistence_failure_is_swallowed(self) -> None:
        """A failing ``record_poll_status`` must not mask sync-job completion."""
        from datetime import UTC, datetime
        from unittest.mock import AsyncMock

        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="owner/repo", source_type="github")
        store = AsyncMock()
        store.record_poll_status.side_effect = RuntimeError("DB unreachable")

        async def mock_sync() -> SyncResult:
            return SyncResult(
                repo="owner/repo",
                created=1,
                updated=0,
                relations_created=0,
                sync_timestamp=datetime.now(tz=UTC),
                pages_processed=1,
            )

        await run_sync_job_async(job, tracker, mock_sync(), store)
        # Job still transitions to COMPLETED despite the liveness failure.
        assert job.status == SyncJobStatus.COMPLETED

    @pytest.mark.unit
    async def test_no_store_skips_liveness_call(self) -> None:
        """Backwards-compat: calls without a store argument must still succeed."""
        from datetime import UTC, datetime

        tracker = SyncJobTracker()
        job = tracker.create_job(source_url="owner/repo", source_type="github")

        async def mock_sync() -> SyncResult:
            return SyncResult(
                repo="owner/repo",
                created=1,
                updated=0,
                relations_created=0,
                sync_timestamp=datetime.now(tz=UTC),
                pages_processed=1,
            )

        # No store argument — must not raise.
        await run_sync_job_async(job, tracker, mock_sync())
        assert job.status == SyncJobStatus.COMPLETED


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
        assert data["count"] == 2
        assert len(data["entry_ids"]) == 2

    @pytest.mark.unit
    async def test_batch_store_missing_author(self, store) -> None:  # type: ignore[no-untyped-def]
        # crud._handle_store_batch validates per-item (issue #364); missing
        # author surfaces as a per-item error in ``results`` rather than a
        # top-level failure that aborts the batch.
        entries = [
            {"content": "Valid entry", "entry_type": "reference"},  # missing author
        ]
        result = await _handle_store_batch(store=store, arguments={"entries": entries})
        data = _parse_response(result)
        assert data.get("count") == 0
        assert data["results"][0]["persisted"] is False
        assert data["results"][0]["error"]["code"] == "INVALID_PARAMS"

    @pytest.mark.unit
    async def test_batch_store_empty_list(self, store) -> None:  # type: ignore[no-untyped-def]
        # crud._handle_store_batch accepts an empty list and returns count=0.
        result = await _handle_store_batch(store=store, arguments={"entries": []})
        data = _parse_response(result)
        assert data.get("count") == 0 or "error" in data or data.get("error_code")

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
        assert data.get("code") == "INVALID_PARAMS"

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


class TestDecoupledGhSync:
    """Tests for the decoupled-store background sync path (issue #588).

    Stateless HTTP closes the request-scoped store as soon as the tool
    response returns, so ``background=True`` must run against a dedicated
    store the job owns for its full lifetime (own connect/close). These
    tests prove the job survives the request store's ``close()`` with no
    use-after-close and no WAL/checkpoint corruption.
    """

    @pytest.mark.integration
    async def test_background_decoupled_store_runs_after_request_close(
        self,
        tmp_path,  # type: ignore[no-untyped-def]
        mock_embedding_provider,  # type: ignore[no-untyped-def]
        httpx_mock,  # type: ignore[no-untyped-def]
    ) -> None:
        """A cold backfill completes on its own connection after the request
        store is closed, and ``distillery_sync_status`` reports the counts."""
        from distillery.feeds.sync_jobs import SyncJobStatus, get_tracker
        from distillery.store.duckdb import DuckDBStore

        db_path = str(tmp_path / "decoupled.duckdb")

        # Cold backfill: an empty store with a page of PRs to ingest. Fewer
        # than _DEFAULT_PER_PAGE (100) items terminates pagination after one
        # page, so no second issues request is needed.
        issues = [_mock_issue(number=n, title=f"PR {n}", is_pr=True) for n in range(1, 8)]
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues\?.*"),
            json=issues,
        )
        httpx_mock.add_response(
            url=re.compile(r".*/repos/test/repo/issues/\d+/comments.*"),
            json=[],
            is_reusable=True,
        )

        # The request-scoped store: closed immediately after the tool returns,
        # mirroring stateless HTTP lifespan teardown.
        request_store = DuckDBStore(db_path=db_path, embedding_provider=mock_embedding_provider)
        await request_store.initialize()

        # Reset the singleton tracker for isolation and wire it to the request
        # store the way the lifespan does — proving sync_status still works in
        # process even though persistence is routed through the owned store.
        tracker = get_tracker()
        tracker._jobs.clear()
        tracker.attach_store(request_store)

        # The factory the background job uses to open its OWN store on the same
        # database file (own connect/close, decoupled from the request).
        async def _store_factory() -> DuckDBStore:
            owned = DuckDBStore(db_path=db_path, embedding_provider=mock_embedding_provider)
            await owned.initialize()
            return owned

        result = await _handle_gh_sync(
            store=request_store,
            arguments={"url": "test/repo", "background": True},
            store_factory=_store_factory,
        )
        data = _parse_response(result)

        # Acceptance: a job_id is returned immediately, no INVALID_PARAMS.
        assert "error" not in data
        assert data.get("code") != "INVALID_PARAMS"
        job_id = data["sync_job"]["job_id"]
        assert job_id
        assert data["sync_job"]["status"] == "pending"

        # The request returns: close the request store right away. The detached
        # job must not touch this connection again.
        await request_store.close()

        # Drive the background task to completion against its own connection.
        for _ in range(200):
            await asyncio.sleep(0.02)
            job = tracker.get_job(job_id)
            assert job is not None
            if job.status in (SyncJobStatus.COMPLETED, SyncJobStatus.FAILED):
                break

        job = tracker.get_job(job_id)
        assert job is not None
        # No use-after-close: the job reaches COMPLETED, not FAILED.
        assert job.status == SyncJobStatus.COMPLETED
        assert job.entries_created == 7
        assert job.entries_updated == 0

        # Acceptance: distillery_sync_status reports completed + correct counts.
        status = _parse_response(await _handle_sync_status(arguments={"job_id": job_id}))
        assert status["status"] == "completed"
        assert status["entries_created"] == 7

        # Acceptance: no WAL/checkpoint corruption. Reopen the file with a
        # fresh connection and verify the synced entries persisted intact.
        verify_store = DuckDBStore(db_path=db_path, embedding_provider=mock_embedding_provider)
        await verify_store.initialize()
        try:
            entries = await verify_store.list_entries(
                filters={"entry_type": "github"}, limit=100, offset=0
            )
            assert len(entries) == 7
            # The sync_jobs row was persisted through the owned connection and
            # is readable after a clean checkpoint.
            row = verify_store.connection.execute(
                "SELECT status, entries_created FROM sync_jobs WHERE job_id = ?",
                [job_id],
            ).fetchone()
            assert row is not None
            assert row[0] == "completed"
            assert row[1] == 7
        finally:
            await verify_store.close()
            tracker.attach_store(None)
            tracker._jobs.clear()

    @pytest.mark.integration
    async def test_build_background_store_factory_opens_independent_store(
        self,
        tmp_path,  # type: ignore[no-untyped-def]
    ) -> None:
        """The server's factory yields an initialised store on its own
        connection that survives an independent store's close (issue #588)."""
        from distillery.config import (
            DistilleryConfig,
            EmbeddingConfig,
            StorageConfig,
        )
        from distillery.mcp.server import (
            _build_background_store_factory,
            _create_embedding_provider,
        )
        from distillery.store.duckdb import DuckDBStore

        db_path = str(tmp_path / "factory.duckdb")
        config = DistilleryConfig(
            storage=StorageConfig(database_path=db_path),
            embedding=EmbeddingConfig(provider="mock", dimensions=8),
        )

        # A "request" store opens the file, then closes (as on response return).
        request_store = DuckDBStore(
            db_path=db_path,
            embedding_provider=_create_embedding_provider(config),
        )
        await request_store.initialize()

        factory = _build_background_store_factory(config)
        owned = await factory()
        try:
            await request_store.close()
            # The owned store is still usable after the request store closed.
            owned.connection.execute("SELECT COUNT(*) FROM entries").fetchone()
        finally:
            await owned.close()

    @pytest.mark.integration
    async def test_background_decoupled_store_factory_failure_marks_job_failed(
        self,
        store,  # type: ignore[no-untyped-def]
    ) -> None:
        """If the dedicated store cannot be opened, the job is marked failed
        rather than silently dropped — sync_status can still surface it."""
        from distillery.feeds.sync_jobs import SyncJobStatus, get_tracker

        tracker = get_tracker()
        tracker._jobs.clear()

        async def _failing_factory() -> Any:
            raise RuntimeError("cannot open store")

        result = await _handle_gh_sync(
            store=store,
            arguments={"url": "test/repo", "background": True},
            store_factory=_failing_factory,
        )
        data = _parse_response(result)
        job_id = data["sync_job"]["job_id"]

        for _ in range(100):
            await asyncio.sleep(0.01)
            job = tracker.get_job(job_id)
            assert job is not None
            if job.status == SyncJobStatus.FAILED:
                break

        job = tracker.get_job(job_id)
        assert job is not None
        assert job.status == SyncJobStatus.FAILED
        tracker._jobs.clear()


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
