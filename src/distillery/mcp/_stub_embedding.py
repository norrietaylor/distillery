"""Lightweight embedding providers for testing and development.

This module contains two providers:

- :class:`StubEmbeddingProvider` — returns zero vectors; used when no provider
  is configured (``embedding.provider`` is empty).  Suitable for status-only
  operations but **not** for search (zero vectors break cosine similarity).

- :class:`HashEmbeddingProvider` — returns deterministic, L2-normalised
  vectors derived from a hash of the input text.  Registered under
  ``embedding.provider: "mock"``.  Suitable for development, eval scenarios,
  and any context where search must return non-trivial results without
  requiring an external API key.
"""

from __future__ import annotations

import math


class StubEmbeddingProvider:
    """A minimal embedding provider that returns zero vectors.

    Useful for local development and smoke-testing the MCP server without
    requiring a live API key.

    Parameters
    ----------
    dimensions:
        Dimensionality of the returned zero vectors.  Defaults to 1024.
    """

    def __init__(self, dimensions: int = 1024) -> None:
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        """Return a zero vector of the configured dimensionality.

        Args:
            text: Ignored.

        Returns:
            A list of ``dimensions`` zeros.
        """
        return [0.0] * self._dimensions

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return a list of zero vectors.

        Args:
            texts: List of texts (ignored).

        Returns:
            One zero vector per input text.
        """
        return [[0.0] * self._dimensions for _ in texts]

    @property
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors."""
        return self._dimensions

    @property
    def model_name(self) -> str:
        """Model identifier."""
        return "stub"


class HashEmbeddingProvider:
    """Deterministic hash-based embedding provider — no API calls needed.

    Produces L2-normalised vectors derived from a hash of the input text.
    Different inputs yield different vectors, making cosine similarity
    functional for search and deduplication.  Registered under
    ``embedding.provider: "mock"`` in the MCP server factory.

    Parameters
    ----------
    dimensions:
        Dimensionality of the returned vectors.  Defaults to 4.
    """

    def __init__(self, dimensions: int = 4) -> None:
        self._dimensions = dimensions

    def _vector_for(self, text: str) -> list[float]:
        """Return a deterministic, L2-normalised vector for *text*."""
        h = hash(text) & 0xFFFFFFFF
        parts = [(h >> (8 * i)) & 0xFF for i in range(self._dimensions)]
        floats = [float(p) + 1.0 for p in parts]
        mag = math.sqrt(sum(x * x for x in floats))
        return [x / mag for x in floats]

    def embed(self, text: str) -> list[float]:
        """Return a hash-based embedding vector for *text*.

        Args:
            text: Input text to embed.

        Returns:
            A list of ``dimensions`` floats, L2-normalised.
        """
        return self._vector_for(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return hash-based embedding vectors for each text.

        Args:
            texts: List of input texts.

        Returns:
            One L2-normalised vector per input text.
        """
        return [self._vector_for(t) for t in texts]

    @property
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors."""
        return self._dimensions

    @property
    def model_name(self) -> str:
        """Model identifier."""
        return "mock-hash"
