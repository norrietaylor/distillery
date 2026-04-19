"""Background sync job tracker for async feed import operations.

When a feed source is added with ``sync_history=True``, the import runs as a
background :mod:`asyncio` task instead of blocking the MCP tool response.  This
module provides a registry that tracks status, progress, and results so
callers can check on running imports.

The tracker is backed by an in-memory dict for hot reads plus (when a
:class:`~distillery.store.duckdb.DuckDBStore` is attached) write-through
persistence to the ``sync_jobs`` table. On server startup, :meth:`hydrate`
reloads recent rows and marks any ``pending`` / ``running`` jobs as
``failed`` with ``error_message="interrupted by server restart"`` — the
asyncio tasks backing them don't survive a restart.

Job lifecycle::

    pending -> running -> completed | failed
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
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


_HYDRATE_HORIZON_HOURS = 24

_INSERT_SYNC_JOB = """
INSERT INTO sync_jobs (
    job_id, source_url, source_type, status, created_at,
    started_at, completed_at,
    entries_created, entries_updated, relations_created, pages_processed,
    errors, error_message, result
) VALUES (
    ?, ?, ?, ?,
    CAST(? AS TIMESTAMPTZ),
    CAST(? AS TIMESTAMPTZ),
    CAST(? AS TIMESTAMPTZ),
    ?, ?, ?, ?, ?, ?, ?
)
ON CONFLICT (job_id) DO UPDATE SET
    status = EXCLUDED.status,
    started_at = EXCLUDED.started_at,
    completed_at = EXCLUDED.completed_at,
    entries_created = EXCLUDED.entries_created,
    entries_updated = EXCLUDED.entries_updated,
    relations_created = EXCLUDED.relations_created,
    pages_processed = EXCLUDED.pages_processed,
    errors = EXCLUDED.errors,
    error_message = EXCLUDED.error_message,
    result = EXCLUDED.result
"""

_SELECT_RECENT_SYNC_JOBS = """
SELECT job_id, source_url, source_type, status,
       strftime(created_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S+00:00'),
       strftime(started_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S+00:00'),
       strftime(completed_at AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%S+00:00'),
       entries_created, entries_updated, relations_created, pages_processed,
       errors, error_message, result
FROM sync_jobs
WHERE created_at > CAST(? AS TIMESTAMPTZ)
ORDER BY created_at DESC
"""


def _dt_to_iso(dt: datetime | None) -> str | None:
    """Format a tz-aware datetime as ISO-8601 UTC for TIMESTAMPTZ binding.

    DuckDB's Python binding for TIMESTAMPTZ requires ``pytz`` when the
    parameter is a tz-aware :class:`datetime`. Passing an ISO string and
    casting with ``CAST(? AS TIMESTAMPTZ)`` in SQL avoids the dependency.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _job_from_row(row: tuple[Any, ...]) -> SyncJob:
    """Rebuild a :class:`SyncJob` from a DuckDB row (SELECT order above)."""
    (
        job_id,
        source_url,
        source_type,
        status,
        created_at,
        started_at,
        completed_at,
        entries_created,
        entries_updated,
        relations_created,
        pages_processed,
        errors_raw,
        error_message,
        result_raw,
    ) = row

    errors: list[str] = []
    if errors_raw:
        try:
            parsed = json.loads(errors_raw)
            if isinstance(parsed, list):
                errors = [str(e) for e in parsed]
        except (TypeError, ValueError):
            errors = []

    result: dict[str, Any] | None = None
    if result_raw:
        try:
            parsed = json.loads(result_raw)
            if isinstance(parsed, dict):
                result = parsed
        except (TypeError, ValueError):
            result = None

    # TIMESTAMPTZ values are projected as ISO-8601 UTC strings by
    # ``_SELECT_RECENT_SYNC_JOBS`` to avoid the pytz dependency DuckDB's
    # Python binding requires for tz-aware datetime conversion.
    def _parse(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    return SyncJob(
        job_id=str(job_id),
        source_url=str(source_url),
        source_type=str(source_type),
        status=SyncJobStatus(str(status)),
        created_at=_parse(created_at) or datetime.now(tz=UTC),
        started_at=_parse(started_at),
        completed_at=_parse(completed_at),
        entries_created=int(entries_created or 0),
        entries_updated=int(entries_updated or 0),
        relations_created=int(relations_created or 0),
        pages_processed=int(pages_processed or 0),
        errors=errors,
        error_message=str(error_message) if error_message is not None else None,
        result=result,
    )


class SyncJobTracker:
    """Registry of background sync jobs.

    The in-memory dict is the primary hot-read surface. When a store is
    attached (via :meth:`attach_store`, or passed to the constructor),
    every state transition is mirrored to the ``sync_jobs`` table.
    Persistence failures are logged and swallowed — they never abort an
    in-memory update.

    Safe for use with asyncio tasks (cooperative concurrency on a single
    thread). DuckDB writes block the event loop briefly (<1 ms); acceptable
    for the single-row transitions here.
    """

    def __init__(self, store: Any | None = None) -> None:
        self._jobs: dict[str, SyncJob] = {}
        self._store: Any | None = store

    def attach_store(self, store: Any) -> None:
        """Attach a store for write-through persistence.

        Intended to be called from the MCP server lifespan once the
        :class:`~distillery.store.duckdb.DuckDBStore` has been initialised.
        """
        self._store = store

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
        self._persist_snapshot(job)
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
        if job is None:
            return
        job.status = SyncJobStatus.RUNNING
        job.started_at = datetime.now(tz=UTC)
        self._persist_snapshot(job)

    def mark_completed(self, job_id: str, result: dict[str, Any] | None = None) -> None:
        """Transition a job to completed status."""
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = SyncJobStatus.COMPLETED
        job.completed_at = datetime.now(tz=UTC)
        job.result = result
        self._persist_snapshot(job)

    def mark_failed(self, job_id: str, error: str) -> None:
        """Transition a job to failed status."""
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.status = SyncJobStatus.FAILED
        job.completed_at = datetime.now(tz=UTC)
        job.error_message = error
        self._persist_snapshot(job)

    def update_progress(
        self,
        job_id: str,
        pages_processed: int,
        created_delta: int,
        updated_delta: int,
    ) -> None:
        """Record per-page progress for a running job.

        Mirrors what the legacy ``_on_page`` inline callback used to do
        (absolute ``pages_processed``, accumulated ``entries_created`` /
        ``entries_updated``) but also write-throughs to the DB so restart
        hydration sees accurate intermediate progress.
        """
        job = self._jobs.get(job_id)
        if job is None:
            return
        job.pages_processed = pages_processed
        job.entries_created += created_delta
        job.entries_updated += updated_delta
        self._persist_snapshot(job)

    async def hydrate(self) -> int:
        """Load recent rows from DB into memory and reconcile dangling jobs.

        Any jobs whose persisted status is ``pending`` or ``running`` are
        stale (their asyncio task didn't survive the restart); they're
        rewritten as ``failed`` with ``error_message="interrupted by server
        restart"``.

        Returns:
            Number of jobs reconciled as interrupted. Zero when no store
            is attached.
        """
        if self._store is None:
            return 0

        store = self._store
        cutoff = datetime.now(tz=UTC) - timedelta(hours=_HYDRATE_HORIZON_HOURS)
        cutoff_iso = _dt_to_iso(cutoff)
        try:
            rows = await asyncio.to_thread(
                lambda: store.connection.execute(
                    _SELECT_RECENT_SYNC_JOBS, [cutoff_iso]
                ).fetchall()
            )
        except Exception:  # noqa: BLE001
            logger.exception("SyncJobTracker.hydrate: failed to load sync_jobs")
            return 0

        interrupted = 0
        for row in rows:
            try:
                job = _job_from_row(row)
            except Exception:  # noqa: BLE001
                logger.exception("SyncJobTracker.hydrate: skipping malformed row")
                continue
            self._jobs[job.job_id] = job
            if job.status in (SyncJobStatus.PENDING, SyncJobStatus.RUNNING):
                job.status = SyncJobStatus.FAILED
                job.completed_at = datetime.now(tz=UTC)
                job.error_message = "interrupted by server restart"
                self._persist_snapshot(job)
                interrupted += 1

        if interrupted:
            logger.info(
                "SyncJobTracker.hydrate: marked %d dangling jobs as interrupted",
                interrupted,
            )
        return interrupted

    # ------------------------------------------------------------------
    # Persistence helpers (no-ops when no store is attached)
    # ------------------------------------------------------------------

    def _persist_snapshot(self, job: SyncJob) -> None:
        """Write the full job row to DB via UPSERT. Silent on failure."""
        if self._store is None:
            return
        try:
            errors_json = json.dumps(job.errors) if job.errors else None
            result_json = json.dumps(job.result) if job.result is not None else None
            self._store.connection.execute(
                _INSERT_SYNC_JOB,
                [
                    job.job_id,
                    job.source_url,
                    job.source_type,
                    str(job.status),
                    _dt_to_iso(job.created_at),
                    _dt_to_iso(job.started_at),
                    _dt_to_iso(job.completed_at),
                    job.entries_created,
                    job.entries_updated,
                    job.relations_created,
                    job.pages_processed,
                    errors_json,
                    job.error_message,
                    result_json,
                ],
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "SyncJobTracker: failed to persist snapshot for job %s",
                job.job_id,
            )


# Module-level singleton for the MCP server process.
_tracker = SyncJobTracker()


def get_tracker() -> SyncJobTracker:
    """Return the module-level :class:`SyncJobTracker` singleton."""
    return _tracker


async def run_sync_job_async(
    job: SyncJob,
    tracker: SyncJobTracker,
    sync_coro: Any,
    store: Any | None = None,
) -> None:
    """Execute a sync coroutine as a background task and update job state.

    This function is meant to be wrapped in ``asyncio.create_task()``.

    Args:
        job: The job to track.
        tracker: The tracker to update.
        sync_coro: An awaitable that performs the actual sync and returns
            a SyncResult-like object with ``to_dict()``, ``created``,
            ``updated``, ``relations_created``, ``pages_processed``, and
            ``errors`` attributes (e.g. ``GitHubSyncAdapter.sync()`` or
            ``GitHubSyncAdapter.sync_batched()``).
        store: Optional :class:`DistilleryStore` used to record liveness
            metadata (``last_polled_at``, ``last_item_count``,
            ``last_error``) on the matching ``feed_sources`` row once the
            sync finishes.  When provided the runner mirrors what
            :meth:`FeedPoller._persist_poll_status` does for scheduled
            polls — without this call, sources that only ever backfilled
            via ``sync_history=True`` would surface as "never polled" to
            ``distillery_watch(action='list')`` (issue #334).
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
        await _record_sync_liveness(
            store,
            source_url=job.source_url,
            item_count=result.created + result.updated,
            error=result.errors[0] if result.errors else None,
        )
    except asyncio.CancelledError:
        # Preserve cancellation semantics: record the job as failed with a
        # stable "cancelled" message and re-raise so the event loop/task
        # owner can continue its teardown (e.g. lifespan shutdown).
        cancel_msg = "Sync job cancelled"
        logger.info(
            "Sync job %s cancelled (partial progress: %d created, %d updated)",
            job.job_id,
            job.entries_created,
            job.entries_updated,
        )
        tracker.mark_failed(job.job_id, cancel_msg)
        await _record_sync_liveness(
            store,
            source_url=job.source_url,
            item_count=job.entries_created + job.entries_updated,
            error=cancel_msg,
        )
        raise
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
        await _record_sync_liveness(
            store,
            source_url=job.source_url,
            item_count=job.entries_created + job.entries_updated,
            error=error_msg,
        )


async def _record_sync_liveness(
    store: Any | None,
    *,
    source_url: str,
    item_count: int,
    error: str | None,
) -> None:
    """Write poll-status liveness for a completed bulk-sync job.

    Kept separate from :func:`run_sync_job_async` so persistence failures do
    not mask sync-job state changes.  A missing ``record_poll_status`` on
    the store (older backend) or a raised exception is logged at
    ``WARNING`` and then swallowed.
    """
    if store is None:
        return
    recorder = getattr(store, "record_poll_status", None)
    if recorder is None:
        return
    try:
        await recorder(
            source_url,
            polled_at=datetime.now(tz=UTC),
            item_count=item_count,
            error=error,
        )
    except Exception:  # noqa: BLE001
        logger.warning(
            "Sync job liveness persistence failed for %s",
            source_url,
            exc_info=True,
        )
