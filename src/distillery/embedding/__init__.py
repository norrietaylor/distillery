"""Embedding provider implementations for Distillery."""

from __future__ import annotations

from .jina import JinaEmbeddingProvider
from .openai import OpenAIEmbeddingProvider
from .protocol import EmbeddingProvider

__all__ = [
    "EmbeddingProvider",
    "JinaEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "create_provider",
]


def create_provider(config: object) -> EmbeddingProvider:
    """Create an embedding provider based on configuration.

    Selects the provider implementation based on the ``embedding.provider``
    value in the supplied configuration object.

    Supported provider values:

    - ``"openai"`` — :class:`OpenAIEmbeddingProvider` using the OpenAI API.
    - ``"jina"`` — :class:`JinaEmbeddingProvider` using the Jina AI API.

    Args:
        config: A :class:`~distillery.config.DistilleryConfig` instance (or
            any object with an ``embedding`` attribute that exposes
            ``provider``, ``model``, ``dimensions``, and ``api_key_env``).

    Returns:
        An object satisfying the :class:`EmbeddingProvider` protocol.

    Raises:
        ValueError: If ``embedding.provider`` is not a recognised value.
        ValueError: If the required API key environment variable is not set.
    """
    embedding_cfg = config.embedding  # type: ignore[attr-defined]
    provider_name = embedding_cfg.provider

    if provider_name == "openai":
        return OpenAIEmbeddingProvider(
            model=embedding_cfg.model,
            dimensions=embedding_cfg.dimensions,
            api_key_env=embedding_cfg.api_key_env or "OPENAI_API_KEY",
        )

    if provider_name == "jina":
        return JinaEmbeddingProvider(
            model=embedding_cfg.model,
            dimensions=embedding_cfg.dimensions,
            api_key_env=embedding_cfg.api_key_env or "JINA_API_KEY",
        )

    raise ValueError(
        f"Unknown embedding provider: {provider_name!r}. Supported values are 'openai' and 'jina'."
    )