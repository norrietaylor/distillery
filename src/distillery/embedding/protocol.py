"""Embedding provider protocol definition."""

from typing import Protocol


class EmbeddingProvider(Protocol):
    """Abstract protocol for embedding generation.

    Implementations of this protocol provide methods to generate vector embeddings
    for text content. The protocol supports both single and batch embedding operations,
    and exposes metadata about the model's dimensionality and identifier.
    """

    def embed(self, text: str) -> list[float]:
        """Embed a single text string into a vector.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts efficiently in a batch.

        Args:
            texts: A list of texts to embed.

        Returns:
            A list of embedding vectors, one per input text, in the same order.
        """
        ...

    @property
    def dimensions(self) -> int:
        """Return the dimensionality of the embedding vectors.

        Returns:
            The number of dimensions in each embedding vector.
        """
        ...

    @property
    def model_name(self) -> str:
        """Return the identifier of the embedding model.

        Returns:
            The model identifier (e.g., 'jina-embeddings-v3', 'text-embedding-3-small').
        """
        ...
