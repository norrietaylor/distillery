"""Jina embedding provider implementation.

Uses the Jina AI Embeddings API (https://api.jina.ai/v1/embeddings) via httpx.
Supports Matryoshka truncation for configurable output dimensions and
differentiated task types for storage vs. query embeddings.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Jina AI Embeddings API endpoint
_JINA_API_URL = "https://api.jina.ai/v1/embeddings"

# Default model and dimensions per task description
_DEFAULT_MODEL = "jina-embeddings-v3"
_DEFAULT_DIMENSIONS = 1024

# Rate limiting / retry settings
_MAX_RETRIES = 3
_INITIAL_BACKOFF = 1.0  # seconds


class JinaEmbeddingProvider:
    """Embedding provider backed by the Jina AI Embeddings API.

    Uses httpx for HTTP requests and supports Matryoshka truncation to
    produce embeddings with a configurable number of dimensions.

    Parameters
    ----------
    api_key:
        Jina AI API key.  When not supplied directly, pass ``api_key_env``
        to read it from an environment variable.
    api_key_env:
        Name of the environment variable that holds the Jina API key.
        Ignored if ``api_key`` is provided directly.
    model:
        Jina embedding model identifier.  Defaults to ``jina-embeddings-v3``.
    dimensions:
        Desired embedding dimensionality (Matryoshka truncation).  Defaults
        to 1024.  Must be > 0.

    Raises
    ------
    ValueError
        If neither ``api_key`` nor ``api_key_env`` resolves to a non-empty
        API key.
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_key_env: str = "JINA_API_KEY",
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
    ) -> None:
        resolved_key = api_key or os.environ.get(api_key_env, "")

        if not resolved_key:
            raise ValueError(
                f"Jina API key not found. "
                f"Set the environment variable '{api_key_env}' or pass api_key directly."
            )

        self._api_key = resolved_key
        self._model = model
        self._dimensions = dimensions

    # ------------------------------------------------------------------
    # EmbeddingProvider protocol
    # ------------------------------------------------------------------

    @property
    def dimensions(self) -> int:
        """Return the configured embedding dimensionality."""
        return self._dimensions

    @property
    def model_name(self) -> str:
        """Return the Jina embedding model identifier."""
        return self._model

    def embed(self, text: str, task_type: str = "retrieval.passage") -> list[float]:
        """Embed a single text string.

        Args:
            text: The text to embed.
            task_type: Jina task type.  Use ``"retrieval.passage"`` for
                documents being stored and ``"retrieval.query"`` for search
                queries.  Defaults to ``"retrieval.passage"``.

        Returns:
            A list of floats representing the embedding vector.

        Raises:
            httpx.HTTPStatusError: On non-retryable HTTP errors.
            RuntimeError: If the API response is malformed.
        """
        results = self.embed_batch([text], task_type=task_type)
        return results[0]

    def embed_batch(
        self, texts: list[str], task_type: str = "retrieval.passage"
    ) -> list[list[float]]:
        """Embed multiple texts using the Jina batch embeddings endpoint.

        Implements exponential backoff retry on HTTP 429 (rate limit) and
        5xx server errors.  Maximum of 3 retries.

        Args:
            texts: A list of texts to embed.
            task_type: Jina task type.  Use ``"retrieval.passage"`` for
                documents being stored and ``"retrieval.query"`` for search
                queries.  Defaults to ``"retrieval.passage"``.

        Returns:
            A list of embedding vectors, one per input text, in the same order.

        Raises:
            httpx.HTTPStatusError: If all retries are exhausted or on a
                non-retryable error.
            RuntimeError: If the API response is malformed.
        """
        if not texts:
            return []

        payload = {
            "model": self._model,
            "input": texts,
            "task": task_type,
            "dimensions": self._dimensions,
            "truncate": True,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        backoff = _INITIAL_BACKOFF

        for attempt in range(_MAX_RETRIES):
            try:
                with httpx.Client(timeout=60.0, verify=True) as client:
                    response = client.post(_JINA_API_URL, json=payload, headers=headers)
                    response.raise_for_status()

                data = response.json()
                return self._parse_response(data, len(texts))

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 or status >= 500:
                    last_error = exc
                    if attempt < _MAX_RETRIES - 1:
                        logger.warning(
                            "Jina API request failed with status %d (attempt %d/%d). "
                            "Retrying in %.1f seconds.",
                            status,
                            attempt + 1,
                            _MAX_RETRIES,
                            backoff,
                        )
                        time.sleep(backoff)
                        backoff *= 2
                    continue
                else:
                    # Non-retryable client error (4xx other than 429)
                    raise RuntimeError(
                        f"Jina API request failed with status {status}: {exc.response.text}"
                    ) from exc

            except httpx.RequestError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "Jina API network error (attempt %d/%d): %s. Retrying in %.1f seconds.",
                        attempt + 1,
                        _MAX_RETRIES,
                        str(exc),
                        backoff,
                    )
                    time.sleep(backoff)
                    backoff *= 2
                continue

        raise RuntimeError(
            f"Jina API request failed after {_MAX_RETRIES} attempts. Last error: {last_error}"
        ) from last_error

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(data: dict[str, Any], expected_count: int) -> list[list[float]]:
        """Parse the Jina API response and extract embedding vectors.

        Args:
            data: Parsed JSON response from the Jina API.
            expected_count: Number of embeddings expected.

        Returns:
            List of embedding vectors.

        Raises:
            RuntimeError: If the response structure is unexpected or the
                number of returned embeddings does not match.
        """
        if "data" not in data:
            raise RuntimeError(
                f"Jina API response missing 'data' field. Response keys: {list(data.keys())}"
            )

        items = data["data"]
        if not isinstance(items, list):
            raise RuntimeError(f"Jina API 'data' field must be a list, got: {type(items).__name__}")

        if len(items) != expected_count:
            raise RuntimeError(
                f"Jina API returned {len(items)} embeddings, expected {expected_count}."
            )

        embeddings: list[list[float]] = []
        for i, item in enumerate(items):
            if "embedding" not in item:
                raise RuntimeError(
                    f"Jina API response item {i} missing 'embedding' field. "
                    f"Keys: {list(item.keys())}"
                )
            embedding = item["embedding"]
            if not isinstance(embedding, list):
                raise RuntimeError(
                    f"Jina API embedding {i} must be a list of floats, "
                    f"got: {type(embedding).__name__}"
                )
            embeddings.append([float(v) for v in embedding])

        return embeddings
