"""Storage layer for Distillery.

Public exports:
    DistilleryStore             -- abstract storage protocol (structural subtyping)
    SearchResult                -- dataclass returned by search / find_similar
    EmbeddingModelMismatchError -- raised when DB metadata disagrees with the
                                   configured embedding provider
"""

from distillery.store.duckdb import EmbeddingModelMismatchError
from distillery.store.protocol import DistilleryStore, SearchResult

__all__ = ["DistilleryStore", "EmbeddingModelMismatchError", "SearchResult"]
