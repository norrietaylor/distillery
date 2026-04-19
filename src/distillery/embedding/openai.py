"""OpenAI embedding provider implementation."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Any

import httpx

from .errors import EmbeddingProviderError, extract_retry_after

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "openai"


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
        using exponential backoff starting at 1 second. When the upstream
        sends a ``Retry-After`` header its value is preferred over the
        exponential backoff for the next sleep.

        Args:
            texts: A list of texts to embed.

        Returns:
            A list of embedding vectors, one per input text, in input order.

        Raises:
            EmbeddingProviderError: When all retries are exhausted after an
                upstream rate limit (HTTP 429) or server error (HTTP 5xx).
                Carries ``provider``, ``status_code``, and ``retry_after``
                so callers can surface structured errors.
            RuntimeError: On non-retryable errors (e.g. non-2xx/non-5xx
                responses, network errors).
        """
        last_error: _RetryableError | None = None
        last_status: int | None = None
        last_retry_after: float | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return self._request(texts)
            except _RetryableError as exc:
                last_error = exc
                last_status = exc.status_code
                last_retry_after = exc.retry_after
                wait = exc.retry_after if exc.retry_after is not None else 2**attempt
                if attempt < self._MAX_RETRIES - 1:
                    logger.warning(
                        "Upstream embedding provider throttled request "
                        "(provider=%s endpoint=%s status=%d attempt=%d/%d "
                        "retry_after=%s). Retrying in %.1f seconds.",
                        _PROVIDER_NAME,
                        self._BASE_URL,
                        exc.status_code,
                        attempt + 1,
                        self._MAX_RETRIES,
                        exc.retry_after,
                        wait,
                    )
                    time.sleep(wait)

        logger.warning(
            "Upstream embedding provider exhausted retries "
            "(provider=%s endpoint=%s status=%s retry_after=%s attempts=%d).",
            _PROVIDER_NAME,
            self._BASE_URL,
            last_status,
            last_retry_after,
            self._MAX_RETRIES,
        )
        raise EmbeddingProviderError(
            f"OpenAI embed_batch failed after {self._MAX_RETRIES} retries: {last_error}",
            provider=_PROVIDER_NAME,
            status_code=last_status,
            retry_after=last_retry_after,
            endpoint=self._BASE_URL,
        ) from last_error

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
            raise _RateLimitError(
                f"OpenAI rate limit exceeded (HTTP 429): {response.text}",
                status_code=429,
                retry_after=extract_retry_after(response),
            )

        if response.status_code >= 500:
            raise _ServerError(
                f"OpenAI server error (HTTP {response.status_code}): {response.text}",
                status_code=response.status_code,
                retry_after=extract_retry_after(response),
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


class _RetryableError(Exception):
    """Base for internal retryable upstream failures (carries status/retry_after)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class _RateLimitError(_RetryableError):
    """Raised internally when the OpenAI API returns HTTP 429."""


class _ServerError(_RetryableError):
    """Raised internally when the OpenAI API returns an HTTP 5xx response."""
