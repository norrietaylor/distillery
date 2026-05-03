"""Tests for distillery.graph.metrics.

Wrapped with ``pytest.importorskip("networkx")`` so these tests run only when
the [graph] extra is installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("networkx")

from distillery.graph.builders import build_relations_graph  # noqa: E402
from distillery.graph.metrics import bridges, communities  # noqa: E402

pytestmark = pytest.mark.unit


def test_bridges_star_graph_center_first() -> None:
    """In a star A-{B,C,D}, the centre A has the highest betweenness."""
    rels = [
        {"from_id": "A", "to_id": "B", "relation_type": "link"},
        {"from_id": "A", "to_id": "C", "relation_type": "link"},
        {"from_id": "A", "to_id": "D", "relation_type": "link"},
    ]
    g = build_relations_graph(rels, directed=True)
    ranked = bridges(g, k=4)
    assert ranked, "ranked list should be non-empty for a 4-node graph"
    assert ranked[0][0] == "A"


def test_bridges_empty_graph_returns_empty() -> None:
    g = build_relations_graph([], directed=True)
    assert bridges(g, k=10) == []


def test_communities_two_clusters_with_bridge() -> None:
    """Two triangles connected by a single bridge edge — Louvain should split them."""
    rels = [
        # Triangle 1
        {"from_id": "A", "to_id": "B", "relation_type": "link"},
        {"from_id": "B", "to_id": "C", "relation_type": "link"},
        {"from_id": "C", "to_id": "A", "relation_type": "link"},
        # Triangle 2
        {"from_id": "X", "to_id": "Y", "relation_type": "link"},
        {"from_id": "Y", "to_id": "Z", "relation_type": "link"},
        {"from_id": "Z", "to_id": "X", "relation_type": "link"},
        # Single bridge
        {"from_id": "C", "to_id": "X", "relation_type": "link"},
    ]
    g = build_relations_graph(rels, directed=True)
    comms = communities(g)
    # Expect exactly two communities aligned with the triangles.
    assert len(comms) == 2
    members = sorted([sorted(c) for c in comms], key=lambda x: x[0])
    assert members == [["A", "B", "C"], ["X", "Y", "Z"]]
