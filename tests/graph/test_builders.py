"""Tests for distillery.graph.builders.

Wrapped with ``pytest.importorskip("networkx")`` so these tests run only when
the [graph] extra is installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("networkx")

from distillery.graph import builders  # noqa: E402
from distillery.graph.builders import _require_networkx, build_relations_graph  # noqa: E402

pytestmark = pytest.mark.unit


def test_build_relations_graph_empty_returns_empty_graph() -> None:
    g = build_relations_graph([], directed=True)
    assert g.number_of_nodes() == 0
    assert g.number_of_edges() == 0


def test_build_relations_graph_three_edges() -> None:
    rels = [
        {"from_id": "a", "to_id": "b", "relation_type": "link"},
        {"from_id": "b", "to_id": "c", "relation_type": "link"},
        {"from_id": "c", "to_id": "a", "relation_type": "depends_on"},
    ]
    g = build_relations_graph(rels, directed=True)
    assert set(g.nodes()) == {"a", "b", "c"}
    assert g.number_of_edges() == 3
    # Edge attribute should round-trip.
    assert g.edges["a", "b"]["relation_type"] == "link"
    assert g.edges["c", "a"]["relation_type"] == "depends_on"


def test_build_relations_graph_undirected_collapses_pair() -> None:
    rels = [
        {"from_id": "a", "to_id": "b", "relation_type": "link"},
        # In a directed graph, this would be a second distinct edge. In an
        # undirected graph, it collapses on top of the first because the
        # endpoint pair is identical.
        {"from_id": "b", "to_id": "a", "relation_type": "link"},
    ]
    g = build_relations_graph(rels, directed=False)
    assert g.is_directed() is False
    assert g.number_of_nodes() == 2
    assert g.number_of_edges() == 1


def test_require_networkx_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``distillery.graph.nx`` is None, ``_require_networkx`` raises."""
    monkeypatch.setattr(builders, "nx", None)
    with pytest.raises(RuntimeError, match="NetworkX not installed"):
        _require_networkx()
