"""Unit tests for the ``metrics`` action of ``distillery_relations``.

Covers graph metrics (bridges, communities) over the relations subgraph.
Most tests require NetworkX (gated via ``pytest.importorskip``); one test
exercises the missing-NetworkX path by monkeypatching the module attribute.
"""

from __future__ import annotations

import contextlib
import json

import pytest

from distillery.mcp.tools.relations import _handle_relations
from tests.conftest import make_entry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


def _parse(result: list) -> dict:  # type: ignore[type-arg]
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


async def _seed_star_relations(store):  # type: ignore[no-untyped-def]
    """Star A->{B,C,D} so betweenness centrality on A is non-zero."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")
    d = await _store_entry(store, content="entry D")
    await store.add_relation(a, b, "link")
    await store.add_relation(a, c, "link")
    await store.add_relation(a, d, "link")
    return a, b, c, d


def _reset_graph_cache() -> None:
    """Drop cached graphs between tests so cache_hit assertions are deterministic."""
    from distillery.graph.cache import default_cache

    cache = default_cache()
    cache._store.clear()


# ---------------------------------------------------------------------------
# Tests requiring NetworkX
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_graph_cache():  # type: ignore[no-untyped-def]
    """Ensure a clean cache for every test."""
    with contextlib.suppress(Exception):
        _reset_graph_cache()
    yield
    with contextlib.suppress(Exception):
        _reset_graph_cache()


async def test_metrics_bridges_global(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    a, _, _, _ = await _seed_star_relations(store)

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "global"}
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["action"] == "metrics"
    assert data["metric"] == "bridges"
    assert data["scope"] == "global"
    assert data["node_count"] >= 4
    assert data["edge_count"] >= 3
    assert isinstance(data["results"], list)
    assert len(data["results"]) > 0
    assert data["count"] == len(data["results"])
    # Each row should carry a node id and a numeric score.
    for row in data["results"]:
        assert "id" in row
        assert "score" in row
    # Cache must report a miss on first call.
    assert data["cache_hit"] is False
    # Centre of the star should be present in the top-k.
    assert any(row["id"] == a for row in data["results"])


async def test_metrics_communities_global(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    # Two separate triangles linked by one bridge edge.
    nodes = {}
    for name in ("A", "B", "C", "X", "Y", "Z"):
        nodes[name] = await _store_entry(store, content=f"entry {name}")
    pairs = [
        ("A", "B"),
        ("B", "C"),
        ("C", "A"),
        ("X", "Y"),
        ("Y", "Z"),
        ("Z", "X"),
        ("C", "X"),  # bridge
    ]
    for src, dst in pairs:
        await store.add_relation(nodes[src], nodes[dst], "link")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "communities", "scope": "global"}
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["metric"] == "communities"
    assert isinstance(data["results"], list)
    assert len(data["results"]) >= 1
    # Each entry is a {"members": [...]} dict.
    for row in data["results"]:
        assert "members" in row
        assert isinstance(row["members"], list)


async def test_metrics_invalid_metric_returns_invalid_params(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bogus", "scope": "global"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "metric" in data["message"]


async def test_metrics_invalid_scope_returns_invalid_params(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "galactic"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "scope" in data["message"]


async def test_metrics_ego_scope_requires_entry_id(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "ego"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "entry_id" in data["message"]


async def test_metrics_ego_scope_unknown_entry_id_returns_not_found(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store,
        {
            "action": "metrics",
            "metric": "bridges",
            "scope": "ego",
            "entry_id": "no-such-uuid",
        },
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "NOT_FOUND"


async def test_metrics_response_envelope_shape(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    await _seed_star_relations(store)
    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "global"}
    )
    data = _parse(result)

    expected_keys = {
        "action",
        "metric",
        "scope",
        "node_count",
        "edge_count",
        "results",
        "count",
        "computed_at",
        "cache_hit",
    }
    assert expected_keys.issubset(set(data.keys()))


async def test_metrics_cache_hit_flips_on_second_call(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    await _seed_star_relations(store)

    first = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "bridges", "scope": "global"}
        )
    )
    second = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "bridges", "scope": "global"}
        )
    )

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True


# ---------------------------------------------------------------------------
# NetworkX missing — runs even without the [graph] extra installed.
# ---------------------------------------------------------------------------


async def test_metrics_returns_internal_when_nx_missing(  # type: ignore[no-untyped-def]
    store, monkeypatch
) -> None:
    """Even when networkx is installed, simulate the missing-extra path.

    We monkeypatch ``distillery.graph.nx`` to None so the gate in
    ``_handle_metrics`` (via ``is_available()``) reports the extra missing.
    """
    import distillery.graph as graph_pkg

    monkeypatch.setattr(graph_pkg, "nx", None)

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "global"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INTERNAL"
    assert "NetworkX not installed" in data["message"]
