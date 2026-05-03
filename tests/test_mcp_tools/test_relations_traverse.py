"""Unit tests for the ``traverse`` action of ``distillery_relations``.

Covers multi-hop BFS over ``entry_relations``:
  - root with no relations returns just the root node
  - one-hop and two-hop chains return the expected depth-tagged nodes
  - hops parameter caps BFS depth (out-of-range entries are excluded)
  - cycles terminate without infinite loops
  - direction filter restricts edges followed
  - relation_type filter restricts edges followed
  - unknown root returns NOT_FOUND
  - invalid hops / direction / relation_type return INVALID_PARAMS
  - self-loop edges are tolerated
"""

from __future__ import annotations

import json

import pytest

from distillery.mcp.tools.relations import _handle_relations
from tests.conftest import make_entry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    """Store a minimal entry, return its id."""
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


def _parse(result: list) -> dict:  # type: ignore[type-arg]
    """Parse MCP TextContent list into a plain dict."""
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Happy paths — BFS shape
# ---------------------------------------------------------------------------


async def test_traverse_root_only_returns_self(store) -> None:  # type: ignore[no-untyped-def]
    """A root with no relations yields a single-node, zero-edge subgraph."""
    a = await _store_entry(store, content="lonely entry")

    result = await _handle_relations(store, {"action": "traverse", "entry_id": a})
    data = _parse(result)

    assert data.get("error") is not True
    assert data["root"] == a
    assert data["node_count"] == 1
    assert data["edge_count"] == 0
    assert data["nodes"] == [{"id": a, "depth": 0}]
    assert data["edges"] == []


async def test_traverse_one_hop(store) -> None:  # type: ignore[no-untyped-def]
    """One-hop chain A->B reaches B at depth 1 with one edge."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    await store.add_relation(a, b, "link")

    result = await _handle_relations(store, {"action": "traverse", "entry_id": a, "hops": 1})
    data = _parse(result)

    assert data.get("error") is not True
    depths = {n["id"]: n["depth"] for n in data["nodes"]}
    assert depths == {a: 0, b: 1}
    assert data["edge_count"] == 1
    assert data["node_count"] == 2


async def test_traverse_two_hops(store) -> None:  # type: ignore[no-untyped-def]
    """Two-hop chain A->B->C reaches C at depth 2."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")
    await store.add_relation(a, b, "link")
    await store.add_relation(b, c, "link")

    result = await _handle_relations(store, {"action": "traverse", "entry_id": a, "hops": 2})
    data = _parse(result)

    assert data.get("error") is not True
    depths = {n["id"]: n["depth"] for n in data["nodes"]}
    assert depths[a] == 0
    assert depths[b] == 1
    assert depths[c] == 2
    assert data["node_count"] == 3
    assert data["edge_count"] == 2


async def test_traverse_respects_hops_limit(store) -> None:  # type: ignore[no-untyped-def]
    """A four-node chain with hops=2 must not include the depth-3 entry."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")
    d = await _store_entry(store, content="entry D")
    await store.add_relation(a, b, "link")
    await store.add_relation(b, c, "link")
    await store.add_relation(c, d, "link")

    result = await _handle_relations(store, {"action": "traverse", "entry_id": a, "hops": 2})
    data = _parse(result)

    node_ids = {n["id"] for n in data["nodes"]}
    assert d not in node_ids
    assert node_ids == {a, b, c}


async def test_traverse_handles_cycle(store) -> None:  # type: ignore[no-untyped-def]
    """A->B and B->A must terminate (visited-set dedup) and return both nodes."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    await store.add_relation(a, b, "link")
    await store.add_relation(b, a, "link")

    result = await _handle_relations(store, {"action": "traverse", "entry_id": a, "hops": 3})
    data = _parse(result)

    assert data.get("error") is not True
    node_ids = {n["id"] for n in data["nodes"]}
    assert node_ids == {a, b}
    # Two distinct directed edges A->B and B->A.
    assert data["edge_count"] == 2


# ---------------------------------------------------------------------------
# Direction filter
# ---------------------------------------------------------------------------


async def test_traverse_direction_outgoing_only(store) -> None:  # type: ignore[no-untyped-def]
    """direction='outgoing' must follow only outgoing edges from the root."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")
    await store.add_relation(a, b, "link")  # A -> B
    await store.add_relation(c, a, "link")  # C -> A

    result = await _handle_relations(
        store,
        {"action": "traverse", "entry_id": a, "hops": 1, "direction": "outgoing"},
    )
    data = _parse(result)

    node_ids = {n["id"] for n in data["nodes"]}
    assert b in node_ids
    assert c not in node_ids


async def test_traverse_direction_incoming_only(store) -> None:  # type: ignore[no-untyped-def]
    """direction='incoming' must follow only incoming edges to the root."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")
    await store.add_relation(a, b, "link")  # A -> B
    await store.add_relation(c, a, "link")  # C -> A

    result = await _handle_relations(
        store,
        {"action": "traverse", "entry_id": a, "hops": 1, "direction": "incoming"},
    )
    data = _parse(result)

    node_ids = {n["id"] for n in data["nodes"]}
    assert c in node_ids
    assert b not in node_ids


# ---------------------------------------------------------------------------
# Relation type filter
# ---------------------------------------------------------------------------


async def test_traverse_relation_type_filter(store) -> None:  # type: ignore[no-untyped-def]
    """relation_type filter restricts edges followed during BFS."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")
    await store.add_relation(a, b, "link")
    await store.add_relation(a, c, "depends_on")

    result = await _handle_relations(
        store,
        {
            "action": "traverse",
            "entry_id": a,
            "hops": 1,
            "relation_type": "link",
        },
    )
    data = _parse(result)

    node_ids = {n["id"] for n in data["nodes"]}
    assert b in node_ids
    assert c not in node_ids
    rel_types = {e["relation_type"] for e in data["edges"]}
    assert rel_types == {"link"}


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


async def test_traverse_unknown_root_returns_not_found(store) -> None:  # type: ignore[no-untyped-def]
    """An unknown entry_id returns NOT_FOUND."""
    result = await _handle_relations(store, {"action": "traverse", "entry_id": "bogus-uuid"})
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "NOT_FOUND"


async def test_traverse_invalid_hops_returns_invalid_params(store) -> None:  # type: ignore[no-untyped-def]
    """hops=0 and hops=99 both fail validation."""
    a = await _store_entry(store, content="entry A")

    for bad_hops in (0, 99):
        result = await _handle_relations(
            store, {"action": "traverse", "entry_id": a, "hops": bad_hops}
        )
        data = _parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "hops" in data["message"]


async def test_traverse_invalid_direction_returns_invalid_params(store) -> None:  # type: ignore[no-untyped-def]
    """An unknown direction returns INVALID_PARAMS."""
    a = await _store_entry(store, content="entry A")

    result = await _handle_relations(
        store,
        {"action": "traverse", "entry_id": a, "direction": "sideways"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "direction" in data["message"]


async def test_traverse_invalid_relation_type_returns_invalid_params(store) -> None:  # type: ignore[no-untyped-def]
    """An unknown relation_type returns INVALID_PARAMS."""
    a = await _store_entry(store, content="entry A")

    result = await _handle_relations(
        store,
        {"action": "traverse", "entry_id": a, "relation_type": "bogus"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "relation_type" in data["message"]


# ---------------------------------------------------------------------------
# Self-loops
# ---------------------------------------------------------------------------


async def test_traverse_self_loop_tolerated(store) -> None:  # type: ignore[no-untyped-def]
    """A self-loop A->A must not cause errors and produces at least one node and edge."""
    a = await _store_entry(store, content="entry A")
    await store.add_relation(a, a, "link")

    result = await _handle_relations(store, {"action": "traverse", "entry_id": a, "hops": 2})
    data = _parse(result)

    assert data.get("error") is not True
    assert data["node_count"] >= 1
    assert data["edge_count"] >= 1
    node_ids = {n["id"] for n in data["nodes"]}
    assert a in node_ids
