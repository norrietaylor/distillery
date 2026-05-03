"""Build NetworkX graphs from Distillery store data.

These builders are *lazy*: they import nx via distillery.graph and raise a
RuntimeError with installation guidance when the extra is not installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from distillery.graph import nx

if TYPE_CHECKING:
    import networkx as nx_types  # noqa: F401


def _require_networkx() -> None:
    if nx is None:
        raise RuntimeError("NetworkX not installed; run: pip install distillery-mcp[graph]")


def build_relations_graph(
    relations: list[dict[str, Any]],
    *,
    directed: bool = True,
) -> Any:  # nx.DiGraph | nx.Graph
    """Build a graph from entry_relations rows.

    Each row is expected to be ``{"from_id": str, "to_id": str, "relation_type": str}``.
    The edge attribute ``relation_type`` is preserved.
    """
    _require_networkx()
    g = nx.DiGraph() if directed else nx.Graph()
    for r in relations:
        g.add_edge(r["from_id"], r["to_id"], relation_type=r["relation_type"])
    return g
