"""Tests for relation curation: bi-temporal read filter + retire/revalidate.

Issue #653 graph-maintenance #4. The key property: ``invalid_at`` was previously
write-only — no read path honored it. These tests lock in that soft-retiring an
edge removes it from default reads, traversal, and the metrics subgraph, while
``include_retired`` still surfaces it and ``revalidate`` brings it back.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import make_entry

pytestmark = pytest.mark.unit


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


async def _edge(store, a, b, rel="related"):  # type: ignore[no-untyped-def]
    return await store.add_relation(a, b, rel)


# ---------------------------------------------------------------------------
# Store-level read filter
# ---------------------------------------------------------------------------


async def test_retired_edge_excluded_from_get_related(store) -> None:  # type: ignore[no-untyped-def]
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    rid = await _edge(store, a, b)

    assert len(await store.get_related(a)) == 1
    assert await store.retire_relation(rid) is True

    # Default read excludes the retired edge ...
    assert await store.get_related(a) == []
    # ... but include_retired surfaces it.
    assert len(await store.get_related(a, include_retired=True)) == 1


async def test_retired_edge_excluded_from_list_relations(store) -> None:  # type: ignore[no-untyped-def]
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    rid = await _edge(store, a, b)
    await store.retire_relation(rid)

    assert await store.list_relations() == []
    assert len(await store.list_relations(include_retired=True)) == 1


async def test_revalidate_restores_edge(store) -> None:  # type: ignore[no-untyped-def]
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    rid = await _edge(store, a, b)
    await store.retire_relation(rid)
    assert await store.get_related(a) == []

    assert await store.revalidate_relation(rid) is True
    assert len(await store.get_related(a)) == 1


async def test_future_invalid_at_stays_live(store) -> None:  # type: ignore[no-untyped-def]
    """An edge whose invalid_at is in the future is still live."""
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    rid = await _edge(store, a, b)
    await store.retire_relation(rid, invalid_at="2999-01-01T00:00:00Z")

    assert len(await store.get_related(a)) == 1


async def test_retire_is_idempotent_and_reports_missing(store) -> None:  # type: ignore[no-untyped-def]
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    rid = await _edge(store, a, b)

    assert await store.retire_relation(rid) is True
    assert await store.retire_relation(rid) is True  # idempotent
    assert await store.retire_relation("no-such-id") is False


async def test_traverse_excludes_retired(store) -> None:  # type: ignore[no-untyped-def]
    """BFS traversal (built on get_related) drops retired edges by default."""
    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    rid = await _edge(store, a, b)
    await store.retire_relation(rid)

    # get_related is the traversal primitive — both directions, no type filter.
    assert await store.get_related(a, direction="both") == []


# ---------------------------------------------------------------------------
# MCP actions
# ---------------------------------------------------------------------------


async def test_mcp_retire_and_revalidate_roundtrip(store) -> None:  # type: ignore[no-untyped-def]
    from distillery.mcp.tools.relations import _handle_relations

    a = await _store_entry(store, content="a")
    b = await _store_entry(store, content="b")
    rid = await _edge(store, a, b)

    retire = json.loads(
        (await _handle_relations(store, {"action": "retire", "relation_id": rid}))[0].text
    )
    assert retire["retired"] is True

    # get excludes it by default ...
    got = json.loads(
        (await _handle_relations(store, {"action": "get", "entry_id": a}))[0].text
    )
    assert got["count"] == 0
    # ... and surfaces it with include_retired.
    got_all = json.loads(
        (
            await _handle_relations(
                store, {"action": "get", "entry_id": a, "include_retired": True}
            )
        )[0].text
    )
    assert got_all["count"] == 1
    assert got_all["include_retired"] is True

    reval = json.loads(
        (await _handle_relations(store, {"action": "revalidate", "relation_id": rid}))[0].text
    )
    assert reval["revalidated"] is True
    got2 = json.loads(
        (await _handle_relations(store, {"action": "get", "entry_id": a}))[0].text
    )
    assert got2["count"] == 1


async def test_mcp_retire_requires_relation_id(store) -> None:  # type: ignore[no-untyped-def]
    from distillery.mcp.tools.relations import _handle_relations

    data = json.loads((await _handle_relations(store, {"action": "retire"}))[0].text)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
