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

import pytest

from distillery.store.duckdb import DuckDBStore

from .conftest import make_entry

pytestmark = pytest.mark.unit


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
