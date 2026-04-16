"""Background sync job tracker for async feed import operations.

When a feed source is added with ``sync_history=True``, the import runs as a
background :mod:`asyncio` task instead of blocking the MCP tool response.  This
module provides an in-memory job registry that tracks status, progress, and
results so callers can check on running imports.

Job lifecycle::

    pending -> running -> completed | failed
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class SyncJobStatus(StrEnum):
    """Lifecycle state of a background sync job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SyncJob:
    """Tracks the state and progress of a background sync operation.

    Attributes:
        job_id: Unique identifier for this job.
        source_url: The feed source URL being synced.
        source_type: Adapter type (``"github"``, ``"rss"``).
        status: Current lifecycle state.
        created_at: When the job was created.
        started_at: When the job began running.
        completed_at: When the job finished (success or failure).
        entries_created: Number of new entries stored so far.
        entries_updated: Number of existing entries updated.
        relations_created: Number of cross-reference relations created.
        pages_processed: Number of pages fetched and committed.
        errors: List of error messages encountered.
        error_message: Top-level error message if the job failed.
        result: Final result dict (serialisable summary).
    """

    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_url: str = ""
    source_type: str = ""
    status: SyncJobStatus = SyncJobStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    entries_created: int = 0
    entries_updated: int = 0
    relations_created: int = 0
    pages_processed: int = 0
    errors: list[str] = field(default_factory=list)
    error_message: str | None = None
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise job state to a plain dict for MCP responses."""
        return {
            "job_id": self.job_id,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "status": str(self.status),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "entries_created": self.entries_created,
            "entries_updated": self.entries_updated,
            "relations_created": self.relations_created,
            "pages_processed": self.pages_processed,
            "errors": self.errors,
            "error_message": self.error_message,
            "result": self.result,
        }


class SyncJobTracker:
    """In-memory registry of background sync jobs.

    Safe for use with asyncio tasks (cooperative concurrency on a single
    thread).  Jobs are kept in memory and are lost on process restart
    (acceptable for MCP server lifecycle).
    """

    def __init__(self) -> None:
        self._jobs: dict[str, SyncJob] = {}

    def create_job(self, source_url: str, source_type: str) -> SyncJob:
        """Create and register a new pending sync job.

        Args:
            source_url: The feed source URL.
            source_type: The adapter type.

        Returns:
            The newly created :class:`SyncJob`.
        """
        job = SyncJob(source_url=source_url, source_type=source_type)
        self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str) -> SyncJob | None:
        """Look up a job by ID.

        Returns:
            The job, or ``None`` if not found.
        """
        return self._jobs.get(job_id)

    def list_jobs(self, source_url: str | None = None) -> list[SyncJob]:
        """List all tracked jobs, optionally filtered by source URL.

        Args:
            source_url: When set, only return jobs for this URL.

        Returns:
            List of jobs sorted by creation time descending.
        """
        jobs = list(self._jobs.values())
        if source_url is not None:
            jobs = [j for j in jobs if j.source_url == source_url]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def mark_running(self, job_id: str) -> None:
        """Transition a job to running status."""
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = SyncJobStatus.RUNNING
            job.started_at = datetime.now(tz=UTC)

    def mark_completed(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        """Transition a job to completed status."""
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = SyncJobStatus.COMPLETED
            job.completed_at = datetime.now(tz=UTC)
            job.result = result

    def mark_failed(self, job_id: str, error: str) -> None:
        """Transition a job to failed status."""
        job = self._jobs.get(job_id)
        if job is not None:
            job.status = SyncJobStatus.FAILED
            job.completed_at = datetime.now(tz=UTC)
            job.error_message = error


# Module-level singleton for the MCP server process.
_tracker = SyncJobTracker()


def get_tracker() -> SyncJobTracker:
    """Return the module-level :class:`SyncJobTracker` singleton."""
    return _tracker


async def run_sync_job_async(
    job: SyncJob,
    tracker: SyncJobTracker,
    sync_coro: Any,
) -> None:
    """Execute a sync coroutine as a background task and update job state.

    This function is meant to be wrapped in ``asyncio.create_task()``.

    Args:
        job: The job to track.
        tracker: The tracker to update.
        sync_coro: An awaitable that performs the actual sync and returns
            a result dict.
    """
    tracker.mark_running(job.job_id)
    try:
        result = await sync_coro
        result_dict = result.to_dict()
        job.entries_created = result.created
        job.entries_updated = result.updated
        job.relations_created = result.relations_created
        job.pages_processed = result.pages_processed
        job.errors = result.errors
        tracker.mark_completed(job.job_id, result_dict)
        logger.info(
            "Sync job %s completed: %d created, %d updated",
            job.job_id,
            job.entries_created,
            job.entries_updated,
        )
    except Exception:  # noqa: BLE001
        error_msg = "Sync job failed"
        logger.exception(
            "Sync job %s failed (partial progress: %d created, %d updated)",
            job.job_id,
            job.entries_created,
            job.entries_updated,
        )
        # Preserve any partial progress already set on the job before failure.
        # mark_failed only sets status/completed_at/error_message, so progress
        # fields (entries_created, entries_updated, etc.) are retained.
        tracker.mark_failed(job.job_id, error_msg)
