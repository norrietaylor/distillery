"""Regression tests for issue #346 — delayed ghost entry_ids.

These tests verify that writes survive ungraceful process termination.
Historically, ``store()`` / ``update()`` / ``delete()`` wrote only to the
DuckDB WAL without an explicit ``CHECKPOINT``.  On abrupt termination
(SIGKILL, OOM, crash, scale-to-zero timeout) the writes lived only in the
WAL.  If the next startup hit an FTS-related WAL replay issue, the
``_sync_initialize`` recovery path would then delete the WAL entirely,
silently losing the writes.  The user-visible symptom was entries that
returned ``persisted: true`` then vanished between creation and later
mutation.

The fixes verified here:

1. :meth:`DuckDBStore._checkpoint_after_write` is invoked after every
   successful ``store`` / ``store_batch`` / ``update`` / ``delete``, so
   writes are durably flushed to the main database file rather than
   sitting in the WAL.
2. The WAL recovery path in :meth:`DuckDBStore._sync_initialize` renames
   the WAL to ``<db>.wal.corrupt.<timestamp>`` instead of unlinking it,
   so any bytes that did end up stranded are preserved for offline
   forensics.

A note on simulating a crash.  Python's ``conn.close()`` and GC both
implicitly flush writes inside DuckDB, which means that closing the
connection in-process isn't actually equivalent to a SIGKILL.  To
reproduce the real ungraceful-termination semantics these tests run the
write path in a subprocess and exit via :func:`os._exit`, which bypasses
DuckDB's Python-level cleanup and leaves behind exactly the on-disk
state a crashed process would.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import duckdb
import pytest

from distillery.models import EntryStatus
from distillery.store.duckdb import DuckDBStore
from tests.conftest import make_entry

pytestmark = pytest.mark.integration


def _run_writer_subprocess(db_path: str, write_code: str, install_root: str) -> None:
    """Run a Distillery writer in a subprocess, then ``os._exit`` without cleanup.

    The subprocess imports DuckDBStore, runs *write_code* (which is
    responsible for performing writes against an already-initialised
    ``store`` local), and exits via :func:`os._exit` from *inside* the
    coroutine.  Exiting from inside the coroutine is essential — if we
    let ``asyncio.run()`` return normally the DuckDB Python binding's
    connection destructor runs during stack unwind and flushes the WAL,
    which masks the bug we're trying to reproduce.  Exiting in-place
    leaves the on-disk state exactly as it would be after a SIGKILL:
    any writes since the last ``CHECKPOINT`` live only in the ``.wal``
    sidecar.
    """
    script = textwrap.dedent(
        f"""\
        import asyncio
        import os
        import sys

        sys.path.insert(0, {install_root!r})

        from distillery.store.duckdb import DuckDBStore

        class _Embed:
            _DIMS = 4

            def _vec(self, text):
                import math
                h = hash(text) & 0xFFFFFFFF
                parts = [(h >> (8 * i)) & 0xFF for i in range(self._DIMS)]
                floats = [float(p) + 1.0 for p in parts]
                mag = math.sqrt(sum(x * x for x in floats))
                return [x / mag for x in floats]

            def embed(self, text):
                return self._vec(text)

            def embed_batch(self, texts):
                return [self._vec(t) for t in texts]

            @property
            def dimensions(self):
                return self._DIMS

            @property
            def model_name(self):
                return "crash-4d"

        async def _run():
            store = DuckDBStore(db_path={db_path!r}, embedding_provider=_Embed())
            await store.initialize()
            from distillery.models import Entry, EntrySource, EntryStatus, EntryType
            {write_code}
            # Exit from INSIDE the coroutine so the connection is never
            # torn down cleanly — matches SIGKILL on-disk state.
            os._exit(0)

        asyncio.run(_run())
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        timeout=30,
        check=False,
    )
    # ``os._exit(0)`` inside the coroutine bypasses asyncio teardown, so
    # returncode 0 is still expected.  Any non-zero code indicates a real
    # problem (import error, write failure, etc.) before the exit.
    assert result.returncode == 0, (
        f"writer subprocess exited with code {result.returncode}: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Durability after ungraceful termination
# ---------------------------------------------------------------------------


class TestEntriesSurviveUngracefulTermination:
    """Writes must land in the main DB file, not only the WAL.

    The failure mode from issue #346 is:

    1. store an entry inside a long-running server process;
    2. the server is SIGKILL'd (scale-to-zero timeout, OOM, crash) before
       DuckDB's Python-level cleanup can flush the WAL to the main DB
       file — the row now lives only in the ``.wal`` sidecar;
    3. the next boot hits an FTS-related WAL replay failure and the
       historical recovery path ``unlink``'d the WAL outright, wiping
       the row.

    With the post-write CHECKPOINT added in this fix, the row is in the
    main database file before step 2, so even a total WAL wipe in step 3
    cannot lose it.

    To faithfully reproduce step 2 the writes run in a subprocess that
    exits via :func:`os._exit` — an in-process ``conn.close()`` (or GC)
    would flush the WAL implicitly and mask the bug.
    """

    _INSTALL_ROOT = str(Path(__file__).resolve().parents[1] / "src")

    @staticmethod
    def _wipe_wal(db_path: str) -> None:
        """Remove the WAL sidecar, simulating DuckDB's historical recovery path.

        Before this fix, ``_sync_initialize`` would ``unlink`` the WAL
        whenever opening the database raised an FTS-related error.  Here
        we emulate that wipe to prove writes survive even when the WAL
        is destroyed — i.e. the main database file carries the row.
        """
        wal = Path(db_path + ".wal")
        if wal.exists():
            wal.unlink()

    def test_stored_entry_survives_crash_and_wal_wipe(self) -> None:
        """An entry stored before an ungraceful exit survives a later WAL wipe."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "ghost.db")
            entry_id = "1fba7293-409b-441b-866e-3c3bbc1d2f64"

            _run_writer_subprocess(
                db_path,
                f"""
            entry = Entry(
                id={entry_id!r},
                content="reference entry for staging-uxtest",
                entry_type=EntryType.REFERENCE,
                source=EntrySource.CLAUDE_CODE,
                author="uxtest-a2",
            )
            await store.store(entry)
        """,
                self._INSTALL_ROOT,
            )

            # Simulate the FTS-related WAL recovery path deleting the WAL
            # file before the next boot is able to replay it.
            self._wipe_wal(db_path)

            conn = duckdb.connect(db_path, read_only=True)
            try:
                row = conn.execute(
                    "SELECT id FROM entries WHERE id = ?", [entry_id]
                ).fetchone()
            finally:
                conn.close()

            assert row is not None, (
                f"Ghost entry: id={entry_id!r} vanished after an ungraceful "
                "exit + WAL wipe. Issue #346 reproduction."
            )
            assert row[0] == entry_id

    def test_updated_entry_survives_crash_and_wal_wipe(self) -> None:
        """An archive-via-update() survives an ungraceful exit + WAL wipe."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "ghost.db")
            entry_id = "23c0a7df-958e-4362-930b-6f34abb1f55d"

            _run_writer_subprocess(
                db_path,
                f"""
            entry = Entry(
                id={entry_id!r},
                content="store then archive",
                entry_type=EntryType.REFERENCE,
                source=EntrySource.CLAUDE_CODE,
                author="uxtest-a2",
            )
            await store.store(entry)
            await store.update({entry_id!r}, {{"status": EntryStatus.ARCHIVED}})
        """,
                self._INSTALL_ROOT,
            )

            self._wipe_wal(db_path)

            conn = duckdb.connect(db_path, read_only=True)
            try:
                row = conn.execute(
                    "SELECT status FROM entries WHERE id = ?", [entry_id]
                ).fetchone()
            finally:
                conn.close()

            assert row is not None, "Updated entry disappeared after crash + WAL wipe"
            assert row[0] == EntryStatus.ARCHIVED.value

    def test_deleted_entry_survives_crash_and_wal_wipe(self) -> None:
        """A soft-deleted (archived) entry survives an ungraceful exit + WAL wipe."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "ghost.db")
            entry_id = "abcdef01-2345-6789-abcd-ef0123456789"

            _run_writer_subprocess(
                db_path,
                f"""
            entry = Entry(
                id={entry_id!r},
                content="will be soft-deleted",
                entry_type=EntryType.INBOX,
                source=EntrySource.CLAUDE_CODE,
                author="uxtest-a2",
            )
            await store.store(entry)
            assert await store.delete({entry_id!r}) is True
        """,
                self._INSTALL_ROOT,
            )

            self._wipe_wal(db_path)

            conn = duckdb.connect(db_path, read_only=True)
            try:
                row = conn.execute(
                    "SELECT status FROM entries WHERE id = ?", [entry_id]
                ).fetchone()
            finally:
                conn.close()

            assert row is not None, "Archived entry disappeared after crash + WAL wipe"
            assert row[0] == EntryStatus.ARCHIVED.value

    def test_batch_stored_entries_survive_crash_and_wal_wipe(self) -> None:
        """Entries stored via store_batch() survive an ungraceful exit + WAL wipe."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "ghost.db")
            ids = [
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
                "00000000-0000-0000-0000-000000000003",
            ]

            _run_writer_subprocess(
                db_path,
                f"""
            entries = [
                Entry(
                    id=i,
                    content=f"bulk {{i[-1]}}",
                    entry_type=EntryType.INBOX,
                    source=EntrySource.CLAUDE_CODE,
                    author="uxtest",
                )
                for i in {ids!r}
            ]
            await store.store_batch(entries)
        """,
                self._INSTALL_ROOT,
            )

            self._wipe_wal(db_path)

            conn = duckdb.connect(db_path, read_only=True)
            try:
                rows = conn.execute("SELECT id FROM entries ORDER BY id").fetchall()
            finally:
                conn.close()

            assert sorted(r[0] for r in rows) == sorted(ids)


# ---------------------------------------------------------------------------
# In-process sanity check: CHECKPOINT actually runs on the write paths
# ---------------------------------------------------------------------------


class TestCheckpointInvokedOnWritePaths:
    """Light unit tests covering the new :meth:`_checkpoint_after_write` hook.

    These don't need a subprocess — they just confirm the write methods
    call the hook.  Guards against a future refactor silently removing
    the CHECKPOINT and reintroducing issue #346.
    """

    async def test_store_invokes_checkpoint(
        self,
        mock_embedding_provider: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        await store.initialize()
        try:
            calls: list[str] = []
            original = DuckDBStore._checkpoint_after_write

            def _spy(self: DuckDBStore, conn: duckdb.DuckDBPyConnection) -> None:
                calls.append("checkpoint")
                original(self, conn)

            monkeypatch.setattr(DuckDBStore, "_checkpoint_after_write", _spy)
            await store.store(make_entry(content="observability"))
            assert calls == ["checkpoint"], "store() must checkpoint once per write"
        finally:
            await store.close()

    async def test_update_invokes_checkpoint(
        self,
        mock_embedding_provider: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        await store.initialize()
        try:
            entry = make_entry(content="stale content")
            await store.store(entry)

            calls: list[str] = []
            original = DuckDBStore._checkpoint_after_write

            def _spy(self: DuckDBStore, conn: duckdb.DuckDBPyConnection) -> None:
                calls.append("checkpoint")
                original(self, conn)

            monkeypatch.setattr(DuckDBStore, "_checkpoint_after_write", _spy)
            await store.update(entry.id, {"content": "fresh content"})
            assert calls == ["checkpoint"], "update() must checkpoint after write"
        finally:
            await store.close()

    async def test_delete_invokes_checkpoint_when_found(
        self,
        mock_embedding_provider: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        await store.initialize()
        try:
            entry = make_entry(content="about to be archived")
            await store.store(entry)

            calls: list[str] = []
            original = DuckDBStore._checkpoint_after_write

            def _spy(self: DuckDBStore, conn: duckdb.DuckDBPyConnection) -> None:
                calls.append("checkpoint")
                original(self, conn)

            monkeypatch.setattr(DuckDBStore, "_checkpoint_after_write", _spy)
            assert await store.delete(entry.id) is True
            assert calls == ["checkpoint"], "delete() must checkpoint on successful archive"
        finally:
            await store.close()

    async def test_delete_does_not_checkpoint_on_missing_entry(
        self,
        mock_embedding_provider: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No work, no checkpoint — minor perf nit but worth asserting."""
        store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
        await store.initialize()
        try:
            calls: list[str] = []
            original = DuckDBStore._checkpoint_after_write

            def _spy(self: DuckDBStore, conn: duckdb.DuckDBPyConnection) -> None:
                calls.append("checkpoint")
                original(self, conn)

            monkeypatch.setattr(DuckDBStore, "_checkpoint_after_write", _spy)
            assert await store.delete("non-existent-id") is False
            assert calls == []
        finally:
            await store.close()


# ---------------------------------------------------------------------------
# WAL recovery path preserves rather than deletes
# ---------------------------------------------------------------------------


class TestWalRecoveryPreservesBytes:
    """The corrupt-WAL fallback must keep a copy of the WAL on disk.

    Historically the fallback ``wal_path.unlink()``'d any WAL that looked
    suspicious.  That was too aggressive: it happily deleted WALs that
    contained legitimate user writes and manifested as silent data loss
    (issue #346).  The fix renames the WAL to a ``.corrupt.<timestamp>``
    sidecar so operators still have the bytes available for forensic
    recovery, and the main database file continues to open cleanly.
    """

    async def test_wal_recovery_renames_wal_instead_of_deleting(
        self,
        mock_embedding_provider: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The WAL is renamed to ``<db>.wal.corrupt.<timestamp>`` on recovery."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "ghost.db")

            # Seed a database and drop a sentinel WAL file next to it.
            store = DuckDBStore(
                db_path=db_path, embedding_provider=mock_embedding_provider
            )
            await store.initialize()
            await store.close()

            wal_path = Path(db_path + ".wal")
            wal_path.write_bytes(b"pretend this is a dirty WAL")

            # Monkey-patch _open_connection so the first call raises an
            # FTS-related error (matching the production failure mode),
            # then falls through to the real implementation on retry.
            real_open = DuckDBStore._open_connection
            call_count = {"n": 0}

            def flaky_open(self: DuckDBStore) -> duckdb.DuckDBPyConnection:
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # Mimic the exact FTS WAL replay failure signature so
                    # _recover_from_wal_replay_failure classifies it as a
                    # recoverable case (see #349 — the recovery path
                    # deliberately matches a narrow signature).
                    raise duckdb.Error(
                        "Dependency Error: Failure while replaying WAL file "
                        "\"/tmp/ghost.db.wal\": Cannot drop entry "
                        "\"fts_main_entries\" because there are entries that "
                        "depend on it."
                    )
                return real_open(self)

            monkeypatch.setattr(DuckDBStore, "_open_connection", flaky_open)

            store2 = DuckDBStore(
                db_path=db_path, embedding_provider=mock_embedding_provider
            )
            try:
                await store2.initialize()
            finally:
                await store2.close()

            # The original WAL must NOT have been unlinked — it must be
            # renamed to a ``.corrupt.<timestamp>`` sidecar.
            assert not wal_path.exists() or wal_path.stat().st_size == 0
            backups = list(Path(tmp).glob("ghost.db.wal.corrupt.*"))
            assert backups, (
                "Expected a preserved WAL sidecar after recovery, but the "
                "recovery path appears to have deleted the WAL outright."
            )
            assert backups[0].read_bytes() == b"pretend this is a dirty WAL"
