"""Tests for distillery.graph.metrics.

Wrapped with ``pytest.importorskip("networkx")`` so these tests run only when
the [graph] extra is installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("networkx")

from distillery.graph.builders import build_relations_graph  # noqa: E402
from distillery.graph.metrics import (  # noqa: E402
    bridges,
    communities,
    constraint,
    link_prediction,
    orphan_rate,
)

pytestmark = pytest.mark.unit


def _bowtie() -> list[dict[str, str]]:
    """M brokers two otherwise-disconnected pairs: {A,B} and {X,Y}."""
    return [
        {"from_id": "M", "to_id": "A", "relation_type": "link"},
        {"from_id": "M", "to_id": "B", "relation_type": "link"},
        {"from_id": "A", "to_id": "B", "relation_type": "link"},
        {"from_id": "M", "to_id": "X", "relation_type": "link"},
        {"from_id": "M", "to_id": "Y", "relation_type": "link"},
        {"from_id": "X", "to_id": "Y", "relation_type": "link"},
    ]


def _shared_neighbors() -> list[dict[str, str]]:
    """A and B share neighbours C, D but are not directly connected."""
    return [
        {"from_id": "A", "to_id": "C", "relation_type": "link"},
        {"from_id": "A", "to_id": "D", "relation_type": "link"},
        {"from_id": "B", "to_id": "C", "relation_type": "link"},
        {"from_id": "B", "to_id": "D", "relation_type": "link"},
    ]


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


def test_constraint_broker_has_lowest_score() -> None:
    """In a bowtie, the broker M sits in a structural hole -> lowest constraint."""
    g = build_relations_graph(_bowtie(), directed=True)
    ranked = constraint(g, k=10)
    assert ranked
    assert ranked[0][0] == "M"
    scores = dict(ranked)
    # The broker is less constrained than a node embedded in a dense triangle.
    assert scores["M"] < scores["A"]


def test_constraint_empty_graph_returns_empty() -> None:
    g = build_relations_graph([], directed=True)
    assert constraint(g, k=10) == []


def test_link_prediction_source_predicts_shared_neighbour() -> None:
    """From A, the top Adamic-Adar candidate is B (they share C and D)."""
    g = build_relations_graph(_shared_neighbors(), directed=True)
    preds = link_prediction(g, source="A", k=5)
    assert preds
    src, tgt, score = preds[0]
    assert src == "A"
    assert tgt == "B"
    assert score > 0


def test_link_prediction_global_surfaces_shared_pair() -> None:
    """With no source, the A-B (and C-D) non-edges are scored across the graph."""
    g = build_relations_graph(_shared_neighbors(), directed=True)
    preds = link_prediction(g, k=10)
    pairs = {frozenset((u, v)) for u, v, _ in preds}
    assert frozenset(("A", "B")) in pairs


def test_link_prediction_unknown_source_returns_empty() -> None:
    g = build_relations_graph(_shared_neighbors(), directed=True)
    assert link_prediction(g, source="ZZZ", k=5) == []


def test_orphan_rate_partial() -> None:
    """8 entries with 2 in the graph -> orphan_rate 0.75 (issue #635)."""
    assert orphan_rate(graph_node_count=2, total_entries=8) == 0.75


def test_orphan_rate_all_linked() -> None:
    assert orphan_rate(graph_node_count=4, total_entries=4) == 0.0


def test_orphan_rate_zero_total_is_guarded() -> None:
    """total_entries == 0 -> orphan_rate 0.0 (no division by zero)."""
    assert orphan_rate(graph_node_count=0, total_entries=0) == 0.0


def test_orphan_rate_clamps_when_nodes_exceed_total() -> None:
    """graph_node_count > total_entries (archived-but-linked nodes) clamps to
    0.0 instead of going negative (issue #635 review)."""
    assert orphan_rate(graph_node_count=2, total_entries=1) == 0.0
