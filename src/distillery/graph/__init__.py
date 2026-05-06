"""Graph analysis module — gated behind the [graph] optional extra."""

from __future__ import annotations

try:
    import networkx as nx
except ImportError:
    nx = None

__all__ = ["is_available", "nx"]


def is_available() -> bool:
    """Return True if networkx is installed."""
    return nx is not None
