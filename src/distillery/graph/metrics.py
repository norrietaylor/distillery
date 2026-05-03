"""Graph metrics over relations subgraphs."""

from __future__ import annotations

from typing import Any

from distillery.graph import nx
from distillery.graph.builders import _require_networkx


def bridges(g: Any, *, k: int = 10) -> list[tuple[str, float]]:
    """Top-k entries by betweenness centrality (descending)."""
    _require_networkx()
    if g.number_of_nodes() == 0:
        return []
    centrality = nx.betweenness_centrality(g)
    ranked = sorted(centrality.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:k]


def communities(g: Any) -> list[set[str]]:
    """Louvain communities on the undirected projection."""
    _require_networkx()
    if g.number_of_nodes() == 0:
        return []
    undirected = g.to_undirected() if g.is_directed() else g
    return list(nx.community.louvain_communities(undirected))
