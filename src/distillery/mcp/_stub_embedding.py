"""Lightweight stub EmbeddingProvider for testing and status-only operation.

This provider is used internally by the MCP server when no embedding provider
is configured in ``distillery.yaml`` (i.e. ``embedding.provider`` is empty).
It does not make any network calls and returns zero vectors.  It is not
intended for production use.
"""

from __future__ import annotations


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
