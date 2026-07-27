"""Graph metrics over relations subgraphs."""

from __future__ import annotations

import math
from typing import Any

from distillery.graph import nx
from distillery.graph.builders import _require_networkx


def orphan_rate(*, graph_node_count: int, total_entries: int) -> float:
    """Fraction of entries that never appear in the relations graph.

    Computed as ``1 - graph_node_count / total_entries``. The relations graph
    only contains entries that are an endpoint of at least one relation, so an
    entry with no relations is invisible to every graph metric. A high value
    signals a near-empty graph (graph-health signal for operators).

    Guards ``total_entries == 0`` -> ``0.0`` and clamps the result to ``[0, 1]``:
    the graph is built from unfiltered relations and may contain archived-but-
    still-linked nodes that are excluded from ``total_entries``, so
    ``graph_node_count`` can exceed the denominator (a documented rate must
    never be negative; issue #635).
    """
    if total_entries <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - graph_node_count / total_entries))


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


def constraint(g: Any, *, k: int = 10) -> list[tuple[str, float]]:
    """Top-k structural-hole brokers by Burt's constraint (ascending).

    Computed on the undirected projection. Burt's constraint is *low* for nodes
    that bridge otherwise-disconnected neighbours (a structural hole / broker)
    and *high* for nodes embedded in a dense, redundant clique. Results are
    sorted ascending, so the first entries are the strongest brokers.

    Nodes with no neighbours (constraint is NaN) are excluded.
    """
    _require_networkx()
    if g.number_of_nodes() == 0:
        return []
    undirected = g.to_undirected() if g.is_directed() else g
    raw = nx.constraint(undirected)
    ranked = [
        (node, float(value))
        for node, value in raw.items()
        if value is not None and not math.isnan(value)
    ]
    ranked.sort(key=lambda kv: kv[1])
    return ranked[:k]


def link_prediction(
    g: Any, *, source: str | None = None, k: int = 10
) -> list[tuple[str, str, float]]:
    """Top-k predicted edges by the Adamic-Adar index (descending).

    Adamic-Adar scores a candidate (non-existent) edge by its shared
    neighbours, weighting each by ``1 / log(degree)`` so a connection through a
    niche shared node counts more than one through a hub. Computed on the
    undirected projection.

    When *source* is given, only candidate edges from that node to its
    non-neighbours are scored (emerging adjacencies for one entry); the source
    must be a node in the graph or an empty list is returned. When *source* is
    ``None``, all non-existent edges are scored — bound the graph first (e.g.
    via ``scope="ego"``) since this is quadratic in node count.

    Returns a list of ``(source, target, score)`` tuples.
    """
    _require_networkx()
    if g.number_of_nodes() == 0:
        return []
    undirected = g.to_undirected() if g.is_directed() else g
    ebunch: list[tuple[str, str]] | None
    if source is not None:
        if source not in undirected:
            return []
        excluded = set(undirected[source])
        excluded.add(source)
        ebunch = [(source, target) for target in undirected.nodes if target not in excluded]
        if not ebunch:
            return []
    else:
        ebunch = None
    ranked = sorted(nx.adamic_adar_index(undirected, ebunch), key=lambda t: t[2], reverse=True)
    return [(u, v, float(p)) for u, v, p in ranked[:k]]


def mean_degree(g: Any) -> float:
    """Mean node degree on the undirected projection (``2·|E| / |V|``).

    A graph-health signal: how densely connected the average node is. Computed
    on the undirected projection so reciprocal directed edges collapse to one,
    matching the other structural metrics in this module. Guards an empty graph
    -> ``0.0``.
    """
    _require_networkx()
    n = int(g.number_of_nodes())
    if n == 0:
        return 0.0
    undirected = g.to_undirected() if g.is_directed() else g
    return 2.0 * int(undirected.number_of_edges()) / n


def connected_component_count(g: Any) -> int:
    """Number of connected components on the undirected projection.

    A graph-health signal: a fragmented graph has many small components; a
    healthy one consolidates toward few large components. Guards an empty graph
    -> ``0``.
    """
    _require_networkx()
    if int(g.number_of_nodes()) == 0:
        return 0
    undirected = g.to_undirected() if g.is_directed() else g
    return int(nx.number_connected_components(undirected))


def largest_component_fraction(g: Any) -> float:
    """Fraction of nodes in the largest connected component (``[0, 1]``).

    A graph-health signal paired with ``connected_component_count``: a value
    near 1 means most linked entries form a single giant component (good for
    traversal); a low value means the graph is shattered into islands. Computed
    on the undirected projection. Guards an empty graph -> ``0.0``.
    """
    _require_networkx()
    n = int(g.number_of_nodes())
    if n == 0:
        return 0.0
    undirected = g.to_undirected() if g.is_directed() else g
    largest = max((len(c) for c in nx.connected_components(undirected)), default=0)
    return largest / n
