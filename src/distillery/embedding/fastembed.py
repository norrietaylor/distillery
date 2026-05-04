"""Fastembed (local, on-device) embedding provider implementation.

Wraps the ``fastembed`` package's :class:`fastembed.TextEmbedding` so that
Distillery can produce embeddings entirely offline.  The default model
``BAAI/bge-small-en-v1.5`` is ~67 MB and produces 384-dimensional vectors,
making it suitable for reproducible benchmarking and for local development
without an API key.

Why a local provider?
---------------------

* **Reproducibility (primary).**  Pinning the fastembed version + model
  identifier yields byte-identical embeddings across runs.  Hosted APIs
  (Jina, OpenAI) can update a model under the same name silently, which
  poisons longitudinal benchmark numbers.
* **Cost (secondary).**  No per-token billing for benchmark loops or
  CI.  All computation happens on-device.

The ``fastembed`` package itself is an *optional* dependency exposed via
``pip install distillery-mcp[fastembed]`` so we don't bloat the default
install with onnxruntime.  Importing this module is safe even when the
package is missing — the import is deferred until first use and surfaces
a clear ``ImportError`` if the dep group has not been installed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastembed import TextEmbedding  # pragma: no cover - typing only

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

#: Default model identifier — small (~67 MB), 384-dimensional, English.
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

#: Friendly aliases for the small set of models the bench / docs reference.
#: The full set is available via :func:`fastembed.TextEmbedding.list_supported_models`.
MODEL_ALIASES: dict[str, str] = {
    "bge-small": "BAAI/bge-small-en-v1.5",
    "bge-base": "BAAI/bge-base-en-v1.5",
    "bge-large": "BAAI/bge-large-en-v1.5",
    "nomic": "nomic-ai/nomic-embed-text-v1.5",
    "mxbai": "mixedbread-ai/mxbai-embed-large-v1",
}

#: Embedding dimensions for known models.  Used so :attr:`dimensions` can be
#: answered before the model has been lazy-loaded (e.g. by config validators).
#: The fastembed library is the source of truth; this map mirrors its
#: ``DenseModelDescription.dim`` values for the aliased models.
_KNOWN_DIMENSIONS: dict[str, int] = {
    "BAAI/bge-small-en-v1.5": 384,
    "BAAI/bge-base-en-v1.5": 768,
    "BAAI/bge-large-en-v1.5": 1024,
    "nomic-ai/nomic-embed-text-v1.5": 768,
    "mixedbread-ai/mxbai-embed-large-v1": 1024,
}


def _resolve_model_name(model: str) -> str:
    """Resolve an alias (e.g. ``"bge-small"``) to its full identifier.

    Pass-through for any value not registered in :data:`MODEL_ALIASES`.
    """
    return MODEL_ALIASES.get(model, model)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class FastembedProvider:
    """Local embedding provider backed by the ``fastembed`` ONNX runtime.

    Implements the :class:`distillery.embedding.protocol.EmbeddingProvider`
    protocol.  The underlying :class:`fastembed.TextEmbedding` is *lazy
    loaded* on the first :meth:`embed` or :meth:`embed_batch` call so that
    constructing a provider is cheap and so that misconfigured deployments
    fail at first use rather than at import.

    Parameters
    ----------
    model:
        Either a full HuggingFace identifier (e.g.
        ``"BAAI/bge-small-en-v1.5"``) or a friendly alias from
        :data:`MODEL_ALIASES` (``"bge-small"``, ``"bge-base"``,
        ``"bge-large"``, ``"nomic"``, ``"mxbai"``).  Defaults to
        :data:`DEFAULT_MODEL` (384-dim, ~67 MB).
    cache_dir:
        Directory in which fastembed caches downloaded ONNX weights.  If
        ``None`` the package default is used (``~/.cache/fastembed``).
    threads:
        Optional thread count override forwarded to fastembed's ONNX
        runtime session.  ``None`` lets onnxruntime pick.

    Raises
    ------
    ImportError
        If the optional ``fastembed`` package is not installed.  Surfaces
        only at first :meth:`embed`/:meth:`embed_batch` call (lazy load),
        not at construction time, so config validators can probe the
        provider without forcing an import.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        cache_dir: str | None = None,
        threads: int | None = None,
    ) -> None:
        self._model_name = _resolve_model_name(model)
        self._cache_dir = cache_dir
        self._threads = threads
        self._dimensions: int | None = _KNOWN_DIMENSIONS.get(self._model_name)
        # Lazy-loaded TextEmbedding instance.  Typed as Any so this module
        # imports cleanly when fastembed is not installed.
        self._embedder: Any | None = None

    # ------------------------------------------------------------------
    # Lazy loader
    # ------------------------------------------------------------------

    def _load(self) -> Any:
        """Instantiate the underlying :class:`fastembed.TextEmbedding`.

        Imports ``fastembed`` lazily so the module remains importable
        without the optional dep group installed.  Caches the embedder so
        the model is loaded at most once per provider instance.
        """
        if self._embedder is not None:
            return self._embedder

        try:
            from fastembed import TextEmbedding
        except ImportError as exc:  # pragma: no cover - exercised manually
            raise ImportError(
                "The 'fastembed' package is required for FastembedProvider. "
                "Install it with: pip install distillery-mcp[fastembed]"
            ) from exc

        logger.info(
            "Loading fastembed model %s (cache_dir=%s, threads=%s)",
            self._model_name,
            self._cache_dir,
            self._threads,
        )
        embedder: TextEmbedding = TextEmbedding(
            model_name=self._model_name,
            cache_dir=self._cache_dir,
            threads=self._threads,
        )

        # Update cached dimensions from the embedder when not pre-known
        # (e.g. a custom model registered at runtime).
        if self._dimensions is None:
            self._dimensions = int(embedder.embedding_size)

        self._embedder = embedder
        return embedder

    # ------------------------------------------------------------------
    # EmbeddingProvider protocol
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Embed a single text string into a vector.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        ``fastembed`` is fully synchronous and CPU-bound; this method
        materialises the underlying generator into a list of native Python
        ``list[float]`` so callers don't have to depend on ``numpy``.

        Args:
            texts: The texts to embed.  Empty list returns an empty list
                without loading the model.

        Returns:
            A list of embedding vectors in the same order as the input.
        """
        if not texts:
            return []

        embedder = self._load()
        # ``TextEmbedding.embed`` returns an iterator of numpy arrays; convert
        # each to a plain list[float] so the public contract is dependency-free.
        result: list[list[float]] = [[float(v) for v in vector] for vector in embedder.embed(texts)]
        return result

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def dimensions(self) -> int:
        """Return the dimensionality of the embedding vectors.

        For aliased / well-known models the dimension is returned without
        loading the model.  For unknown identifiers the model is loaded
        lazily on first access.
        """
        if self._dimensions is None:
            self._load()
        # _dimensions is guaranteed populated after _load()
        assert self._dimensions is not None
        return self._dimensions

    @property
    def model_name(self) -> str:
        """Return the resolved HuggingFace model identifier."""
        return self._model_name
