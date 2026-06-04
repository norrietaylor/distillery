"""Regression tests for issue #363.

A single server-side DuckDB error previously left the shared connection
in an aborted-transaction state.  Every subsequent call — reads as well
as writes — failed with::

    TransactionContext Error: Current transaction is aborted (please ROLLBACK)

The fix wraps every async store operation in :meth:`DuckDBStore._run_sync`,
which issues a best-effort ``ROLLBACK`` when the wrapped sync function
raises.  Read-only operations reach the same wrapper so a connection
poisoned by a prior failure is cleared before the next call.

These tests exercise the rollback contract directly against an in-memory
store so they catch regressions without depending on server-side
behaviour.
"""

from __future__ import annotations

from unittest import mock

import duckdb
import pytest

from distillery.store.duckdb import DuckDBStore

from .conftest import make_entry

pytestmark = pytest.mark.unit


def _fatal_invalidated() -> None:
    """Sync hook that raises the terminal DuckDB invalidation fatal (issue #583)."""
    raise duckdb.FatalException(
        "FATAL Error: Failed: database has been invalidated because of a "
        "previous fatal error. The database must be restarted prior to being "
        "used again."
    )


class TestRunSyncRollback:
    """Exercise the ``_run_sync`` rollback-on-exception contract."""

    async def test_rolls_back_on_raise(self, store: DuckDBStore) -> None:
        """A failing sync fn must trigger ROLLBACK before the exception propagates."""
        rollback_calls: list[str] = []

        original_rollback = store._rollback_quietly  # type: ignore[attr-defined]

        def tracking_rollback(conn: object) -> None:
            rollback_calls.append("called")
            original_rollback(conn)

        store._rollback_quietly = tracking_rollback  # type: ignore[attr-defined,method-assign]

        def exploding() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            await store._run_sync(exploding)  # type: ignore[attr-defined]

        assert rollback_calls == ["called"]

    async def test_no_rollback_on_success(self, store: DuckDBStore) -> None:
        """A successful sync fn must not call ROLLBACK — no spurious WAL churn."""
        rollback_calls: list[str] = []
        store._rollback_quietly = lambda conn: rollback_calls.append("called")  # type: ignore[attr-defined,method-assign]

        result = await store._run_sync(lambda: 42)  # type: ignore[attr-defined]

        assert result == 42
        assert rollback_calls == []

    async def test_rollback_quietly_swallows_errors(self, store: DuckDBStore) -> None:
        """A ROLLBACK that itself fails must not mask the caller's original error."""
        import duckdb

        class DummyConn:
            def rollback(self) -> None:
                raise duckdb.Error("nothing to roll back")

        # Should not raise.
        DuckDBStore._rollback_quietly(DummyConn())  # type: ignore[arg-type]


class TestTerminalFatalInvalidation:
    """Issue #583: a FatalException carrying "has been invalidated" must
    fail fast — set ``_terminal_failure``, log CRITICAL, request a SIGTERM
    restart from the supervisor, and re-raise — instead of looping forever
    against a permanently dead connection."""

    async def test_fatal_invalidation_sets_flag_signals_sigterm_and_reraises(
        self, store: DuckDBStore, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The invalidation fatal sets the flag, kills the process, and propagates."""
        import logging
        import os

        assert store._terminal_failure is None  # type: ignore[attr-defined]

        with (
            mock.patch("distillery.store.duckdb.os.kill") as mock_kill,
            caplog.at_level(logging.CRITICAL, logger="distillery.store.duckdb"),
            pytest.raises(duckdb.FatalException, match="has been invalidated"),
        ):
            await store._run_sync(_fatal_invalidated)  # type: ignore[attr-defined]

        # Flag recorded so MCP/webhook layers can fail fast on the next call.
        assert store._terminal_failure is not None  # type: ignore[attr-defined]
        assert "has been invalidated" in str(store._terminal_failure)  # type: ignore[attr-defined]

        # Supervisor restart requested via SIGTERM to *our own* pid.
        mock_kill.assert_called_once_with(os.getpid(), __import__("signal").SIGTERM)

        # Operators get a CRITICAL log, not a silent 32 MB of stack traces.
        assert any(r.levelno >= logging.CRITICAL for r in caplog.records)

    async def test_non_invalidating_fatal_does_not_signal_or_set_flag(
        self, store: DuckDBStore
    ) -> None:
        """A FatalException without the invalidation marker must NOT fail fast.

        It rolls back like any other error and leaves the terminal flag unset
        so the supervisor is not asked to restart on a recoverable fatal.
        """

        def other_fatal() -> None:
            raise duckdb.FatalException("FATAL Error: some other transient fatal")

        with (
            mock.patch("distillery.store.duckdb.os.kill") as mock_kill,
            pytest.raises(duckdb.FatalException, match="some other transient"),
        ):
            await store._run_sync(other_fatal)  # type: ignore[attr-defined]

        mock_kill.assert_not_called()
        assert store._terminal_failure is None  # type: ignore[attr-defined]


class TestReadAfterWriteFailure:
    """The key scenario from issue #363: a failed write must not brick reads."""

    async def test_read_succeeds_after_store_failure(self, store: DuckDBStore) -> None:
        """After a store() raises, a follow-up list_entries() must succeed."""
        good_entry = make_entry(content="healthy entry")
        await store.store(good_entry)

        # Force _sync_store to raise so the connection has an opportunity to
        # enter an aborted state.  _run_sync should roll back before the
        # exception escapes, restoring the connection for subsequent reads.
        original_sync_store = store._sync_store  # type: ignore[attr-defined]

        def failing_sync_store(entry: object) -> str:
            original_sync_store(entry)  # do the write, then raise
            raise RuntimeError("simulated post-write failure")

        store._sync_store = failing_sync_store  # type: ignore[attr-defined,method-assign]
        with pytest.raises(RuntimeError, match="simulated post-write failure"):
            await store.store(make_entry(content="will-fail"))

        # Restore the real method so subsequent operations behave normally.
        store._sync_store = original_sync_store  # type: ignore[attr-defined,method-assign]

        # The canonical poison scenario: a list after a failed write used to
        # raise ``TransactionContext Error: Current transaction is aborted``.
        # With the rollback wrapper it returns the stored entries.
        entries = await store.list_entries(filters=None, limit=100, offset=0)
        assert any(e.content == "healthy entry" for e in entries)

    async def test_probe_readiness_returns_true_on_healthy_store(self, store: DuckDBStore) -> None:
        """A freshly-initialised store must report itself ready."""
        ready, err = await store.probe_readiness()
        assert ready is True
        assert err is None

    async def test_probe_readiness_reports_failure_when_uninitialised(
        self, mock_embedding_provider: object
    ) -> None:
        """A store that has never been initialised must report not-ready with a reason."""
        uninitialised = DuckDBStore(
            db_path=":memory:",
            embedding_provider=mock_embedding_provider,  # type: ignore[arg-type]
        )
        ready, err = await uninitialised.probe_readiness()
        assert ready is False
        assert err is not None
        assert "not initialized" in err

    async def test_rollback_public_method_noop_on_uninitialised(
        self, mock_embedding_provider: object
    ) -> None:
        """``await store.rollback()`` must be safe when _conn is None."""
        uninitialised = DuckDBStore(
            db_path=":memory:",
            embedding_provider=mock_embedding_provider,  # type: ignore[arg-type]
        )
        # Should not raise.
        await uninitialised.rollback()


class TestStatusDegraded:
    """``distillery_status`` must surface query failures (issue #363 follow-up)."""

    async def test_status_marks_degraded_when_count_entries_raises(
        self,
        store: DuckDBStore,
        mock_embedding_provider: object,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When ``count_entries`` raises, status must report ``degraded`` with a stable code.

        The client-facing payload must NOT contain raw exception text
        (e.g. ``DuckDB``/``RuntimeError``/paths) — only a stable generic
        code that callers can branch on.  The full exception is logged
        server-side.
        """
        import logging

        from distillery.config import DistilleryConfig
        from distillery.mcp.tools.meta import _handle_status

        from .conftest import parse_mcp_response

        async def broken_count_entries(filters: object = None, **kwargs: object) -> int:
            raise RuntimeError("DB unreadable at /private/path.db")

        store.count_entries = broken_count_entries  # type: ignore[method-assign]

        with caplog.at_level(logging.WARNING, logger="distillery.mcp.tools.meta"):
            result = await _handle_status(
                store=store,
                config=DistilleryConfig(),
                embedding_provider=mock_embedding_provider,
                tool_count=16,
                transport="http",
                started_at=None,
            )
        payload = parse_mcp_response(result)

        assert payload["status"] == "degraded"
        assert payload["store"]["entry_count"] is None
        assert payload["store"]["entry_count_error"] == "entry_count_unavailable"
        assert "entry_count_unavailable" in payload["degraded_reasons"]
        # The raw exception text must stay server-side (in logs) and never
        # reach the client-visible payload.
        serialised = result[0].text
        assert "DB unreadable" not in serialised
        assert "/private/path.db" not in serialised
        assert "RuntimeError" not in serialised
        # But it must still appear in the server-side log for operators —
        # ``logger.exception`` attaches the traceback to the record's
        # ``exc_info``; ``caplog.text`` renders it so the raw message is
        # searchable there.
        assert "DB unreadable" in caplog.text

    async def test_status_degraded_immediately_on_terminal_failure(
        self,
        store: DuckDBStore,
        mock_embedding_provider: object,
    ) -> None:
        """Issue #583: once ``_terminal_failure`` is set, status reports
        ``degraded`` from the cached flag — it must NOT depend on the readiness
        probe running (which against a dead connection would block/re-raise).
        """
        from distillery.config import DistilleryConfig
        from distillery.mcp.tools.meta import _handle_status

        from .conftest import parse_mcp_response

        # Simulate the post-fatal state recorded by ``_run_sync``.
        store._terminal_failure = duckdb.FatalException(  # type: ignore[attr-defined]
            "database has been invalidated because of a previous fatal error"
        )

        async def _fail_probe() -> tuple[bool, str | None]:
            raise AssertionError("probe_readiness must not be relied upon for terminal status")

        # Even if the probe is broken, status must already be degraded from the
        # flag.  (We do not assert the probe is never called — only that the
        # terminal reason is present regardless of probe outcome.)
        store.probe_readiness = _fail_probe  # type: ignore[method-assign]

        result = await _handle_status(
            store=store,
            config=DistilleryConfig(),
            embedding_provider=mock_embedding_provider,
            tool_count=16,
            transport="http",
            started_at=None,
        )
        payload = parse_mcp_response(result)

        assert payload["status"] == "degraded"
        assert "store_terminally_failed" in payload["degraded_reasons"]


class TestStatusLastPollAt:
    """Issue #404: ``distillery_status.last_feed_poll.last_poll_at`` must
    reflect the most recent ``feed_sources.last_polled_at`` value, not the
    ``webhook_audit:poll`` metadata row whose write was lost when the
    background task was cancelled.
    """

    async def test_last_poll_at_uses_max_feed_sources_last_polled_at(
        self, store: DuckDBStore, mock_embedding_provider: object
    ) -> None:
        """When a feed source has been polled, status reports its timestamp
        even if no ``webhook_audit:poll`` metadata row exists.
        """
        from datetime import UTC, datetime, timedelta

        from distillery.config import DistilleryConfig
        from distillery.mcp.tools.meta import _handle_status

        from .conftest import parse_mcp_response

        await store.add_feed_source(
            url="https://example.com/rss",
            source_type="rss",
            poll_interval_minutes=60,
        )
        # Persist a fresh poll outcome — this is the production code
        # path (``FeedPoller._persist_poll_status`` calls this directly).
        polled_at = datetime.now(tz=UTC) - timedelta(minutes=1)
        await store.record_poll_status(
            "https://example.com/rss",
            polled_at=polled_at,
            item_count=3,
            error=None,
        )

        # Deliberately do NOT write ``webhook_audit:poll`` — this is the
        # production scenario where the bg task was cancelled before
        # ``_record_audit`` could run.

        result = await _handle_status(
            store=store,
            config=DistilleryConfig(),
            embedding_provider=mock_embedding_provider,
            tool_count=16,
            transport="http",
            started_at=None,
        )
        payload = parse_mcp_response(result)

        last_poll_at = payload["last_feed_poll"]["last_poll_at"]
        assert isinstance(last_poll_at, str), payload
        # Tolerate sub-second formatting differences — the assertion
        # that matters is that the timestamp is fresh (within the last
        # 5 minutes) rather than ``None``.
        from datetime import datetime as _dt

        parsed = _dt.fromisoformat(last_poll_at)
        assert (datetime.now(tz=UTC) - parsed).total_seconds() < 300

    async def test_last_poll_at_falls_back_to_audit_when_no_sources_polled(
        self, store: DuckDBStore, mock_embedding_provider: object
    ) -> None:
        """When no feed source has been polled, status falls back to the
        ``webhook_audit:poll`` row (preserves the previous behaviour for
        fresh installs whose first poll-cycle write may have failed).
        """
        import json

        from distillery.config import DistilleryConfig
        from distillery.mcp.tools.meta import _handle_status

        from .conftest import parse_mcp_response

        # No feed sources, no last_polled_at anywhere — but a webhook
        # audit row was written (the deprecated path).
        audit_ts = "2026-04-23T14:16:34.768785+00:00"
        await store.set_metadata(
            "webhook_audit:poll",
            json.dumps({"timestamp": audit_ts, "status": 200, "ok": True}),
        )

        result = await _handle_status(
            store=store,
            config=DistilleryConfig(),
            embedding_provider=mock_embedding_provider,
            tool_count=16,
            transport="http",
            started_at=None,
        )
        payload = parse_mcp_response(result)

        assert payload["last_feed_poll"]["last_poll_at"] == audit_ts
