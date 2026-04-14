"""OpenAI embedding provider implementation."""

from __future__ import annotations

import contextlib
import os
import time
from typing import Any

import httpx


class OpenAIEmbeddingProvider:
    """Embedding provider using the OpenAI Embeddings API.

    Uses httpx for HTTP requests. Supports rate limiting with exponential
    backoff on batch requests.

    Attributes:
        _model: The OpenAI embedding model identifier.
        _dimensions: The number of dimensions for the embedding vectors.
        _api_key: The OpenAI API key used for authentication.
        _client: The httpx client for making API requests.

    Example::

        provider = OpenAIEmbeddingProvider(api_key="sk-...")
        vector = provider.embed("Hello, world!")
        vectors = provider.embed_batch(["Hello", "World"])
    """

    _BASE_URL = "https://api.openai.com/v1/embeddings"
    _MAX_RETRIES = 3

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        dimensions: int = 512,
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        """Initialise the OpenAI embedding provider.

        Args:
            api_key: The OpenAI API key. If *None* the key is read from the
                environment variable named by *api_key_env*.
            model: The embedding model to use. Defaults to
                ``text-embedding-3-small``.
            dimensions: The number of dimensions to request via the
                OpenAI ``dimensions`` parameter. Defaults to ``512``.
            api_key_env: Name of the environment variable that holds the API
                key, used when *api_key* is not supplied directly.

        Raises:
            ValueError: If no API key can be resolved.
        """
        resolved_key = api_key or os.environ.get(api_key_env, "")
        if not resolved_key:
            raise ValueError(
                f"OpenAI API key not found. Set the {api_key_env!r} environment "
                "variable or pass api_key explicitly."
            )

        self._model = model
        self._dimensions = dimensions
        self._api_key = resolved_key
        self._client = httpx.Client(timeout=30.0, verify=True)

    # ------------------------------------------------------------------
    # EmbeddingProvider protocol implementation
    # ------------------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Embed a single text string.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.

        Raises:
            RuntimeError: If the API request fails.
        """
        results = self._request([text])
        return results[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts with rate-limit retry and exponential backoff.

        Retries up to ``_MAX_RETRIES`` times on HTTP 429 or 5xx responses,
        using exponential backoff starting at 1 second.

        Args:
            texts: A list of texts to embed.

        Returns:
            A list of embedding vectors, one per input text, in input order.

        Raises:
            RuntimeError: If the API request fails after all retries.
        """
        last_error: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return self._request(texts)
            except _RateLimitError as exc:
                last_error = exc
                wait = 2**attempt  # 1 s, 2 s, 4 s
                time.sleep(wait)
            except _ServerError as exc:
                last_error = exc
                wait = 2**attempt
                time.sleep(wait)

        raise RuntimeError(
            f"OpenAI embed_batch failed after {self._MAX_RETRIES} retries: {last_error}"
        )

    @property
    def dimensions(self) -> int:
        """Return the dimensionality of the embedding vectors.

        Returns:
            The number of dimensions in each embedding vector.
        """
        return self._dimensions

    @property
    def model_name(self) -> str:
        """Return the identifier of the embedding model.

        Returns:
            The model identifier (e.g., ``text-embedding-3-small``).
        """
        return self._model

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, texts: list[str]) -> list[list[float]]:
        """Send an embeddings request to the OpenAI API.

        Args:
            texts: Texts to embed.

        Returns:
            List of embedding vectors.

        Raises:
            _RateLimitError: On HTTP 429.
            _ServerError: On HTTP 5xx.
            RuntimeError: On other non-2xx responses or network errors.
        """
        payload: dict[str, Any] = {
            "input": texts,
            "model": self._model,
            "dimensions": self._dimensions,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._client.post(self._BASE_URL, json=payload, headers=headers)
        except httpx.RequestError as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

        if response.status_code == 429:
            raise _RateLimitError(f"OpenAI rate limit exceeded (HTTP 429): {response.text}")

        if response.status_code >= 500:
            raise _ServerError(
                f"OpenAI server error (HTTP {response.status_code}): {response.text}"
            )

        if response.status_code != 200:
            raise RuntimeError(f"OpenAI API error (HTTP {response.status_code}): {response.text}")

        data = response.json()

        # Sort results by index to guarantee order matches input
        embeddings_data = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in embeddings_data]

    def __del__(self) -> None:
        """Close the httpx client when the provider is garbage-collected."""
        with contextlib.suppress(Exception):
            self._client.close()


class _RateLimitError(Exception):
    """Raised internally when the OpenAI API returns HTTP 429."""


class _ServerError(Exception):
    """Raised internally when the OpenAI API returns an HTTP 5xx response."""
