"""Storage layer for Distillery.

Public exports:
    DistilleryStore -- abstract storage protocol (structural subtyping)
    SearchResult    -- dataclass returned by search / find_similar
"""

from distillery.store.protocol import DistilleryStore, SearchResult

__all__ = ["DistilleryStore", "SearchResult"]
