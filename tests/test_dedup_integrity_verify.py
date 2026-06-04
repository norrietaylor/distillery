"""Tests for issue #584 — post-bulk-rewrite integrity verification of ``entries``.

A dedup/merge that bulk-rewrites the ``entries`` table across the
variable-length VARCHAR / embedding columns can leave the table corrupt in a
way that ``SELECT COUNT(*)`` never detects.  These tests cover the read-back
guard added in response:

  * :meth:`DuckDBStore.verify_entries_readable` passes on a healthy table after
    a real bulk rewrite (an ``apply_correction`` that INSERTs a new row and
    UPDATEs the original).
  * It raises :class:`EntriesIntegrityError` when the read-back materialisation
    errors (simulating an unreadable post-state).
  * The ``distillery_find_similar`` merge/duplicate accept path returns success
    when the table verifies readable...
  * ...and fails loud (INTERNAL error, not success) when verification raises.

All tests use the controlled embedding provider so similarity scoring is
reproducible.
"""

from __future__ import annotations

from typing import Any

import pytest

from distillery.config import DistilleryConfig, load_config
from distillery.mcp.tools.search import _handle_find_similar
from distillery.store.duckdb import DuckDBStore, EntriesIntegrityError
from tests.conftest import ControlledEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.unit

_UNIT_A = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


@pytest.fixture
async def store(  # type: ignore[no-untyped-def]
    controlled_embedding_provider: ControlledEmbeddingProvider,
):
    s = DuckDBStore(db_path=":memory:", embedding_provider=controlled_embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def cfg() -> DistilleryConfig:
    return load_config()


# ---------------------------------------------------------------------------
# Store-level verify_entries_readable
# ---------------------------------------------------------------------------


async def test_verify_entries_readable_passes_after_real_bulk_rewrite(
    store: DuckDBStore,
) -> None:
    """After a real entries rewrite, read-back over the touched ids succeeds."""
    original_id = await store.store(make_entry(content="original wrong fact"))
    # apply_correction is a bulk rewrite of entries: INSERT new row + UPDATE
    # original across the variable-length VARCHAR / embedding columns.
    correction = make_entry(content="corrected fact")
    new_id = await store.apply_correction(correction, original_id)

    # Should not raise — the table is readable.
    await store.verify_entries_readable([original_id, new_id])


async def test_verify_entries_readable_empty_ids_runs_sweep(
    store: DuckDBStore,
) -> None:
    """An empty id list still checkpoints and runs the storage sweep without error."""
    await store.store(make_entry(content="some entry"))
    await store.verify_entries_readable([])


class _FailOnSQLConnection:
    """Proxy over a real DuckDB connection that raises on a marker substring.

    The native ``DuckDBPyConnection.execute`` attribute is read-only and cannot
    be monkeypatched in place, so we wrap the connection and swap it onto the
    store to simulate the corrupt-data-page failure DuckDB raises when scanning
    a botched dictionary/raw/bitpacked column during the read-back.
    """

    def __init__(self, real: Any, marker: str, message: str) -> None:
        self._real = real
        self._marker = marker
        self._message = message

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        if self._marker in sql:
            raise RuntimeError(self._message)
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


async def test_verify_entries_readable_raises_on_unreadable_readback(
    store: DuckDBStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-back that errors is surfaced as EntriesIntegrityError (fail loud)."""
    entry_id = await store.store(make_entry(content="entry"))

    proxy = _FailOnSQLConnection(
        store.connection,
        marker="FROM entries WHERE id = ANY",
        message="IO Error: Failed to scan dictionary string - out of range",
    )
    monkeypatch.setattr(store, "_conn", proxy)

    with pytest.raises(EntriesIntegrityError) as exc_info:
        await store.verify_entries_readable([entry_id])
    assert "read-back failed" in str(exc_info.value)


async def test_verify_entries_readable_materialises_embedding_column(
    store: DuckDBStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read-back SELECT materialises the ``embedding`` column (issue #584).

    ``embedding`` (FLOAT[1024]) is a named corruption target, so a torn rewrite
    isolated to that column must be scanned and caught by the guard.
    """
    entry_id = await store.store(make_entry(content="entry"))

    captured: list[str] = []

    class _Capturing:
        def __init__(self, real: Any) -> None:
            self._real = real

        def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
            captured.append(sql)
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

    monkeypatch.setattr(store, "_conn", _Capturing(store.connection))
    await store.verify_entries_readable([entry_id])

    readback = next(s for s in captured if "FROM entries WHERE id = ANY" in s)
    assert "embedding" in readback


async def test_verify_entries_readable_raises_on_unreadable_embedding(
    store: DuckDBStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A torn embedding column surfaced during read-back fails loud."""
    entry_id = await store.store(make_entry(content="entry"))

    proxy = _FailOnSQLConnection(
        store.connection,
        marker="embedding FROM entries WHERE id = ANY",
        message="IO Error: Failed to scan FLOAT[1024] embedding - corrupt data page",
    )
    monkeypatch.setattr(store, "_conn", proxy)

    with pytest.raises(EntriesIntegrityError) as exc_info:
        await store.verify_entries_readable([entry_id])
    assert "read-back failed" in str(exc_info.value)


async def test_verify_entries_readable_raises_on_storage_sweep_failure(
    store: DuckDBStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing PRAGMA storage_info sweep also fails loud."""
    entry_id = await store.store(make_entry(content="entry"))

    proxy = _FailOnSQLConnection(
        store.connection,
        marker="storage_info",
        message="INTERNAL Error: Bitpacking offset is out of range",
    )
    monkeypatch.setattr(store, "_conn", proxy)

    with pytest.raises(EntriesIntegrityError):
        await store.verify_entries_readable([entry_id])


# ---------------------------------------------------------------------------
# Merge path of distillery_find_similar (accept_action="merge"|"duplicate")
# ---------------------------------------------------------------------------


async def test_find_similar_merge_verifies_and_succeeds(
    store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """accept_action='merge' runs the integrity guard and still reports success."""
    controlled_embedding_provider.register("a", _UNIT_A)
    controlled_embedding_provider.register("b", _UNIT_A)
    src_id = await store.store(make_entry(content="a"))
    t_id = await store.store(make_entry(content="b"))

    payload = parse_mcp_response(
        await _handle_find_similar(
            store,
            {
                "source_entry_id": src_id,
                "threshold": 0.5,
                "limit": 10,
                "accept_action": "merge",
            },
            cfg=cfg,
        )
    )
    assert payload.get("error") is not True
    assert payload["accept_relation_type"] == "merge_source"
    assert {o["to_id"] for o in payload["accept_outcomes"]} == {t_id}


@pytest.mark.parametrize("action", ["merge", "duplicate"])
async def test_find_similar_merge_fails_loud_on_corruption(
    store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    """A simulated unreadable post-merge state returns INTERNAL, not success."""
    controlled_embedding_provider.register("a", _UNIT_A)
    controlled_embedding_provider.register("b", _UNIT_A)
    src_id = await store.store(make_entry(content="a"))
    await store.store(make_entry(content="b"))

    async def boom(entry_ids: Any) -> None:
        raise EntriesIntegrityError("entries table read-back failed after bulk rewrite")

    monkeypatch.setattr(store, "verify_entries_readable", boom)

    payload = parse_mcp_response(
        await _handle_find_similar(
            store,
            {
                "source_entry_id": src_id,
                "threshold": 0.5,
                "limit": 10,
                "accept_action": action,
            },
            cfg=cfg,
        )
    )
    assert payload.get("error") is True
    assert payload.get("code") == "INTERNAL"
    assert "integrity" in payload.get("message", "").lower()


async def test_find_similar_link_does_not_run_integrity_guard(
    store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """accept_action='link' is not a bulk rewrite, so the guard is not invoked."""
    controlled_embedding_provider.register("a", _UNIT_A)
    controlled_embedding_provider.register("b", _UNIT_A)
    src_id = await store.store(make_entry(content="a"))
    await store.store(make_entry(content="b"))

    async def boom(entry_ids: Any) -> None:  # pragma: no cover — must not run
        raise EntriesIntegrityError("should not be called for link")

    monkeypatch.setattr(store, "verify_entries_readable", boom)

    payload = parse_mcp_response(
        await _handle_find_similar(
            store,
            {
                "source_entry_id": src_id,
                "threshold": 0.5,
                "limit": 10,
                "accept_action": "link",
            },
            cfg=cfg,
        )
    )
    assert payload.get("error") is not True
    assert payload["accept_relation_type"] == "related"
