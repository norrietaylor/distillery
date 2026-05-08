"""Tests for issue #490 — entry_relations backfill on write + reconcile + accept_action.

Covers the three patch-fix mechanisms scoped into the initial PR:

  * Mechanism #1 — ``metadata.related_entries`` is fanned out into
    ``entry_relations`` on every ``store`` / ``store_batch`` / ``update`` call,
    AND re-scanned at startup on every ``DuckDBStore.initialize()`` so DBs
    that captured related_entries before this codepath existed populate
    retroactively.
  * Mechanism #2 — ``distillery_find_similar(accept_action=...)`` persists a
    typed relation from ``source_entry_id`` to each result above threshold.
  * Mechanism #9 — ``distillery_relations action="reconcile"`` re-runs the
    metadata backfill and reports per-mechanism counts.

All tests use the deterministic / controlled embedding provider so similarity
scoring is reproducible.
"""

from __future__ import annotations

import json

import duckdb
import pytest

from distillery.config import DistilleryConfig, load_config
from distillery.mcp.tools.relations import _handle_relations
from distillery.mcp.tools.search import _handle_find_similar
from distillery.store.duckdb import DuckDBStore
from distillery.store.migrations import (
    backfill_relations_from_metadata,
    run_pending_migrations,
)
from tests.conftest import ControlledEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# backfill_relations_from_metadata helper (idempotency, self-loop guard)
# ---------------------------------------------------------------------------


_DIMENSIONS = 4
_EMBEDDING = [0.25, 0.25, 0.25, 0.25]


def _setup_through_8(conn: duckdb.DuckDBPyConnection) -> None:
    """Run all migrations to bring up entry_relations + entries."""
    run_pending_migrations(conn, dimensions=_DIMENSIONS, vss_available=False)


def _insert_entry(
    conn: duckdb.DuckDBPyConnection,
    entry_id: str,
    metadata: dict | None = None,
) -> None:
    meta_json = json.dumps(metadata) if metadata else None
    conn.execute(
        "INSERT INTO entries (id, content, entry_type, source, author, metadata, embedding) "
        "VALUES (?, 'test content', 'inbox', 'manual', 'tester', ?, ?)",
        [entry_id, meta_json, _EMBEDDING],
    )


def test_backfill_helper_is_idempotent() -> None:
    """Running the helper twice produces the same row count — no duplicates."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_through_8(conn)
        _insert_entry(conn, "a", metadata={"related_entries": ["b", "c"]})
        _insert_entry(conn, "b")
        _insert_entry(conn, "c")

        first = backfill_relations_from_metadata(conn)
        second = backfill_relations_from_metadata(conn)

        assert first == 2
        # Second run is a no-op because all edges already exist.
        assert second == 0
        rows = conn.execute(
            "SELECT COUNT(*) FROM entry_relations WHERE relation_type = 'link'"
        ).fetchone()
        assert rows is not None and rows[0] == 2
    finally:
        conn.close()


def test_backfill_helper_skips_self_loops() -> None:
    """An entry whose related_entries lists itself must not produce a self-edge."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_through_8(conn)
        _insert_entry(conn, "a", metadata={"related_entries": ["a", "b"]})
        _insert_entry(conn, "b")

        inserted = backfill_relations_from_metadata(conn)
        assert inserted == 1
        rows = conn.execute("SELECT from_id, to_id FROM entry_relations").fetchall()
        assert ("a", "a") not in [(r[0], r[1]) for r in rows]
        assert ("a", "b") in [(r[0], r[1]) for r in rows]
    finally:
        conn.close()


def test_backfill_helper_skips_dangling_targets() -> None:
    """Targets that don't exist in entries are silently skipped."""
    conn = duckdb.connect(":memory:")
    try:
        _setup_through_8(conn)
        _insert_entry(conn, "a", metadata={"related_entries": ["ghost", "b"]})
        _insert_entry(conn, "b")

        inserted = backfill_relations_from_metadata(conn)
        assert inserted == 1
        to_ids = {r[0] for r in conn.execute("SELECT to_id FROM entry_relations").fetchall()}
        assert to_ids == {"b"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Write-path fan-out (mechanism #1) — store / store_batch / update
# ---------------------------------------------------------------------------


@pytest.fixture
async def store(  # type: ignore[no-untyped-def]
    controlled_embedding_provider: ControlledEmbeddingProvider,
):
    s = DuckDBStore(db_path=":memory:", embedding_provider=controlled_embedding_provider)
    await s.initialize()
    yield s
    await s.close()


async def test_store_fans_out_related_entries_to_entry_relations(store: DuckDBStore) -> None:
    """``store(entry)`` writes one entry_relations row per metadata.related_entries id."""
    target_a = make_entry(content="target A")
    target_b = make_entry(content="target B")
    a_id = await store.store(target_a)
    b_id = await store.store(target_b)

    source = make_entry(content="source", metadata={"related_entries": [a_id, b_id]})
    src_id = await store.store(source)

    rows = await store.get_related(src_id, direction="outgoing")
    to_ids = {r["to_id"] for r in rows}
    assert to_ids == {a_id, b_id}
    assert {r["relation_type"] for r in rows} == {"link"}


async def test_store_fan_out_is_idempotent_via_unique_index(
    store: DuckDBStore,
) -> None:
    """A second store with the same metadata.related_entries must not duplicate edges."""
    target = make_entry(content="target")
    t_id = await store.store(target)

    source = make_entry(content="source", metadata={"related_entries": [t_id]})
    src_id = await store.store(source)

    # Reconcile (re-run the metadata scan) to prove idempotency on the same
    # input. The unique index on (from_id, to_id, relation_type) suppresses
    # the duplicate insert.
    counts = await store.reconcile_relations()
    assert counts["metadata_links"] == 0

    rows = await store.get_related(src_id, direction="outgoing")
    assert len(rows) == 1


async def test_update_fans_out_new_related_entries(store: DuckDBStore) -> None:
    """Adding ``related_entries`` via update writes the corresponding edges."""
    a = await store.store(make_entry(content="a"))
    b = await store.store(make_entry(content="b"))
    src_id = await store.store(make_entry(content="src"))

    # Initially no relations.
    assert await store.get_related(src_id, direction="outgoing") == []

    # Update with related_entries — fan-out should fire.
    await store.update(src_id, {"metadata": {"related_entries": [a, b]}})
    to_ids = {r["to_id"] for r in await store.get_related(src_id, direction="outgoing")}
    assert to_ids == {a, b}


async def test_store_batch_fans_out_related_entries(store: DuckDBStore) -> None:
    """``store_batch`` populates entry_relations from each entry's metadata."""
    # Pre-existing target so cross-entry references resolve.
    pre_id = await store.store(make_entry(content="pre"))

    e1 = make_entry(content="e1", metadata={"related_entries": [pre_id]})
    e2 = make_entry(content="e2", metadata={"related_entries": [pre_id]})
    [e1_id, e2_id] = await store.store_batch([e1, e2])

    rows1 = await store.get_related(e1_id, direction="outgoing")
    rows2 = await store.get_related(e2_id, direction="outgoing")
    assert {r["to_id"] for r in rows1} == {pre_id}
    assert {r["to_id"] for r in rows2} == {pre_id}


async def test_startup_rescan_recovers_pre_migration_metadata(
    controlled_embedding_provider: ControlledEmbeddingProvider, tmp_path
) -> None:
    """A persisted DB where edges are missing recovers them on the next initialize().

    Simulates the field instance described in issue #490: entries written
    after migration 8 ran, with metadata.related_entries populated, but with
    the entry_relations table empty (e.g. edges were never written by the
    write-path because the fan-out hook didn't exist yet).
    """
    db_path = str(tmp_path / "rescan.duckdb")
    s1 = DuckDBStore(db_path=db_path, embedding_provider=controlled_embedding_provider)
    await s1.initialize()
    a = await s1.store(make_entry(content="a"))
    b = await s1.store(make_entry(content="b"))
    src_id = await s1.store(make_entry(content="src", metadata={"related_entries": [a, b]}))
    # Manually wipe entry_relations to simulate the regression — entries are
    # there with metadata but no edges exist yet.
    s1.connection.execute("DELETE FROM entry_relations")
    assert s1.connection.execute("SELECT COUNT(*) FROM entry_relations").fetchone()[0] == 0
    await s1.close()

    # Re-open: startup re-scan should re-create the edges from metadata.
    s2 = DuckDBStore(db_path=db_path, embedding_provider=controlled_embedding_provider)
    await s2.initialize()
    try:
        rows = await s2.get_related(src_id, direction="outgoing")
        assert {r["to_id"] for r in rows} == {a, b}
    finally:
        await s2.close()


# ---------------------------------------------------------------------------
# action="reconcile" handler (mechanism #9)
# ---------------------------------------------------------------------------


async def test_reconcile_handler_returns_zero_on_clean_db(store: DuckDBStore) -> None:
    """On a freshly initialised DB with no metadata, reconcile inserts nothing."""
    result = await _handle_relations(store, {"action": "reconcile"})
    payload = parse_mcp_response(result)
    assert payload["action"] == "reconcile"
    assert payload["metadata_links"] == 0
    assert payload["total"] == 0


async def test_reconcile_handler_recovers_missing_edges(
    store: DuckDBStore,
) -> None:
    """Reconcile fills in edges that are missing despite metadata.related_entries."""
    a = await store.store(make_entry(content="a"))
    b = await store.store(make_entry(content="b"))
    src_id = await store.store(make_entry(content="src", metadata={"related_entries": [a, b]}))
    # Wipe edges to simulate drift.
    store.connection.execute("DELETE FROM entry_relations")

    result = await _handle_relations(store, {"action": "reconcile"})
    payload = parse_mcp_response(result)
    assert payload["action"] == "reconcile"
    assert payload["metadata_links"] == 2
    assert payload["total"] == 2

    rows = await store.get_related(src_id, direction="outgoing")
    assert {r["to_id"] for r in rows} == {a, b}


async def test_reconcile_handler_is_idempotent_on_re_run(store: DuckDBStore) -> None:
    """Calling reconcile twice never produces more edges than the first run."""
    a = await store.store(make_entry(content="a"))
    src_id = await store.store(make_entry(content="src", metadata={"related_entries": [a]}))
    store.connection.execute("DELETE FROM entry_relations")

    first = parse_mcp_response(await _handle_relations(store, {"action": "reconcile"}))
    second = parse_mcp_response(await _handle_relations(store, {"action": "reconcile"}))

    assert first["metadata_links"] == 1
    assert second["metadata_links"] == 0
    rows = await store.get_related(src_id, direction="outgoing")
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# distillery_find_similar(accept_action=...) — mechanism #2
# ---------------------------------------------------------------------------


_UNIT_A = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


@pytest.fixture
def cfg() -> DistilleryConfig:
    return load_config()


async def test_find_similar_accept_action_link_persists_related_relation(
    store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """accept_action='link' writes a 'related' edge to each match."""
    controlled_embedding_provider.register("source", _UNIT_A)
    controlled_embedding_provider.register("target one", _UNIT_A)
    controlled_embedding_provider.register("target two", _UNIT_A)

    src_id = await store.store(make_entry(content="source"))
    t1_id = await store.store(make_entry(content="target one"))
    t2_id = await store.store(make_entry(content="target two"))

    result = await _handle_find_similar(
        store,
        {
            "source_entry_id": src_id,
            "threshold": 0.5,
            "limit": 10,
            "accept_action": "link",
        },
        cfg=cfg,
    )
    payload = parse_mcp_response(result)
    assert payload["accept_action"] == "link"
    assert payload["accept_relation_type"] == "related"
    assert payload["accept_persisted_count"] == 2
    persisted_to = {o["to_id"] for o in payload["accept_outcomes"] if o.get("persisted")}
    assert persisted_to == {t1_id, t2_id}

    rows = await store.get_related(src_id, direction="outgoing")
    types_by_to = {r["to_id"]: r["relation_type"] for r in rows}
    assert types_by_to == {t1_id: "related", t2_id: "related"}


async def test_find_similar_accept_action_merge_persists_merge_source(
    store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """accept_action='merge' maps to relation_type='merge_source'."""
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
    assert payload["accept_relation_type"] == "merge_source"
    rows = await store.get_related(src_id, direction="outgoing")
    assert {r["relation_type"] for r in rows} == {"merge_source"}
    assert {r["to_id"] for r in rows} == {t_id}


async def test_find_similar_accept_action_idempotent_re_call(
    store: DuckDBStore,
    controlled_embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """Calling find_similar with accept_action twice does not duplicate edges."""
    controlled_embedding_provider.register("a", _UNIT_A)
    controlled_embedding_provider.register("b", _UNIT_A)
    src_id = await store.store(make_entry(content="a"))
    t_id = await store.store(make_entry(content="b"))

    args = {
        "source_entry_id": src_id,
        "threshold": 0.5,
        "limit": 10,
        "accept_action": "link",
    }
    p1 = parse_mcp_response(await _handle_find_similar(store, args, cfg=cfg))
    p2 = parse_mcp_response(await _handle_find_similar(store, args, cfg=cfg))
    assert p1["accept_persisted_count"] == 1
    # Second call sees the edge already exists, so persisted_new==0 even
    # though every outcome reports persisted=True.
    assert p2["accept_persisted_count"] == 0
    assert all(o["persisted"] for o in p2["accept_outcomes"])
    rows = await store.get_related(src_id, direction="outgoing")
    assert len(rows) == 1
    assert rows[0]["to_id"] == t_id


async def test_find_similar_accept_action_requires_source_entry_id(
    store: DuckDBStore,
    cfg: DistilleryConfig,
) -> None:
    """accept_action without source_entry_id returns INVALID_PARAMS."""
    payload = parse_mcp_response(
        await _handle_find_similar(
            store,
            {"content": "anything", "accept_action": "link"},
            cfg=cfg,
        )
    )
    assert payload.get("error") is True
    assert payload.get("code") == "INVALID_PARAMS"
    assert "source_entry_id" in payload.get("message", "")


async def test_find_similar_accept_action_rejects_unknown_value(
    store: DuckDBStore,
    cfg: DistilleryConfig,
) -> None:
    """Unknown accept_action value is rejected before any work is done."""
    src_id = await store.store(make_entry(content="x"))
    payload = parse_mcp_response(
        await _handle_find_similar(
            store,
            {
                "source_entry_id": src_id,
                "accept_action": "bogus",
            },
            cfg=cfg,
        )
    )
    assert payload.get("error") is True
    assert payload.get("code") == "INVALID_PARAMS"
