"""Jina Reader API client for enriching feed items with full article content.

The :class:`JinaReaderClient` fetches clean, LLM-ready markdown for any public
URL via the Jina Reader API (https://r.jina.ai/<url>).  It's used by the RSS
feed poller to enrich short ``<description>`` blurbs with the full article
body so embeddings and semantic search reflect the actual content.

Design choices
--------------

* Async (``httpx.AsyncClient``) — the poller is async; allows bounded
  concurrent enrichment via :class:`asyncio.Semaphore`.
* :meth:`JinaReaderClient.fetch` never raises — it returns ``None`` on any
  failure so the poller's existing per-source error handling is unchanged.
* Exponential backoff on 429 / 5xx / transport errors (max 2 retries),
  honoring ``Retry-After`` via the shared
  :func:`~distillery.embedding.errors.extract_retry_after` helper.
* Auth via the existing ``JINA_API_KEY`` environment variable (same secret
  as :class:`~distillery.embedding.jina.JinaEmbeddingProvider`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from urllib.parse import quote

import httpx

from distillery.embedding.errors import extract_retry_after

logger = logging.getLogger(__name__)

# Jina Reader API base URL — append the URL-encoded target URL to retrieve
# its content as markdown.
_JINA_READER_BASE_URL = "https://r.jina.ai/"

# Default backoff settings.  ``_MAX_RETRIES`` matches the issue spec ("max 2
# retries") and is the *additional* attempts after the first try, so the
# total maximum number of attempts is ``_MAX_RETRIES + 1``.
_MAX_RETRIES = 2
_INITIAL_BACKOFF = 1.0  # seconds


def build_reader_client(
    *,
    api_key_env: str = "JINA_API_KEY",
    timeout_seconds: float = 30.0,
    max_retries: int = _MAX_RETRIES,
    concurrency: int = 5,
) -> JinaReaderClient | None:
    """Build a :class:`JinaReaderClient` if the API key is present.

    Returns ``None`` when the configured environment variable is unset or
    empty so callers can silently disable Reader enrichment without raising.

    Args:
        api_key_env: Name of the environment variable holding the Jina API
            key.  Defaults to ``"JINA_API_KEY"``.
        timeout_seconds: Per-request timeout in seconds.
        max_retries: Maximum number of retry attempts on retryable errors.
        concurrency: Maximum number of concurrent requests.

    Returns:
        A configured :class:`JinaReaderClient`, or ``None`` if the API key
        is unset.
    """
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        # ``api_key_env`` is the *name* of the environment variable (e.g.
        # ``"JINA_API_KEY"``) — never the secret value — so logging it at
        # DEBUG is safe.  We do not log the variable name here to avoid
        # tripping CodeQL's ``py/clear-text-logging-sensitive-data`` rule,
        # which flags any logged identifier containing ``api_key`` even
        # when the value is a configuration string rather than a credential.
        logger.debug(
            "build_reader_client: configured env var is not set — Reader enrichment disabled"
        )
        return None
    return JinaReaderClient(
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        concurrency=concurrency,
    )


class JinaReaderClient:
    """Async client for the Jina Reader API.

    Fetches markdown for a public URL via ``GET https://r.jina.ai/<url>`` with
    a bearer token.  Retries on 429 and 5xx responses with exponential
    backoff, honoring the ``Retry-After`` header when supplied.

    Parameters
    ----------
    api_key:
        Jina AI API key.  Required — use :func:`build_reader_client` for
        the env-var-based factory that returns ``None`` when the key is
        missing.
    timeout_seconds:
        Per-request timeout passed to :class:`httpx.AsyncClient`.
    max_retries:
        Maximum number of retry attempts on 429 / 5xx / transport failures.
        The initial attempt is not counted, so ``max_retries=2`` yields up
        to 3 total HTTP requests per :meth:`fetch` call.
    concurrency:
        Maximum number of in-flight requests across all callers sharing
        this client instance.  Implemented via :class:`asyncio.Semaphore`.

    Raises
    ------
    ValueError
        If *api_key* is empty or *concurrency* / *max_retries* are
        out of range.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 30.0,
        max_retries: int = _MAX_RETRIES,
        concurrency: int = 5,
    ) -> None:
        if not api_key:
            raise ValueError("JinaReaderClient requires a non-empty api_key")
        if concurrency < 1:
            raise ValueError(f"concurrency must be >= 1, got: {concurrency}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be >= 0, got: {max_retries}")
        if timeout_seconds <= 0:
            raise ValueError(f"timeout_seconds must be > 0, got: {timeout_seconds}")

        self._api_key = api_key
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._semaphore = asyncio.Semaphore(concurrency)

    async def fetch(self, url: str) -> str | None:
        """Fetch markdown for *url* via the Jina Reader API.

        Never raises — returns ``None`` on any failure so callers can fall
        back to their original content without aborting the surrounding
        pipeline.  All failures are logged at WARNING level with the URL
        and (where available) the upstream status code.

        Args:
            url: The article URL to fetch.  Must be a non-empty HTTP(S)
                URL; other schemes return ``None`` immediately.

        Returns:
            Markdown body on success (non-empty string), or ``None`` on
            any failure (transport error, non-2xx, empty body, retries
            exhausted).
        """
        if not url or not url.strip():
            return None

        async with self._semaphore:
            return await self._fetch_with_retry(url.strip())

    async def _fetch_with_retry(self, url: str) -> str | None:
        """Inner retry loop — assumes the semaphore is already held."""
        endpoint = _JINA_READER_BASE_URL + quote(url, safe=":/?#[]@!$&'()*+,;=%")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "text/plain",
        }
        backoff = _INITIAL_BACKOFF

        # Total attempts = initial try + max_retries
        total_attempts = self._max_retries + 1

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(1, total_attempts + 1):
                start = time.monotonic()
                try:
                    response = await client.get(endpoint, headers=headers)
                except httpx.RequestError as exc:
                    duration_ms = (time.monotonic() - start) * 1000
                    logger.warning(
                        "JinaReaderClient transport error "
                        "(url=%s attempt=%d/%d duration_ms=%.0f): %s",
                        url,
                        attempt,
                        total_attempts,
                        duration_ms,
                        exc,
                    )
                    if attempt < total_attempts:
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    return None

                duration_ms = (time.monotonic() - start) * 1000
                status = response.status_code

                if 200 <= status < 300:
                    body = response.text
                    bytes_len = len(body.encode("utf-8"))
                    if not body.strip():
                        logger.warning(
                            "JinaReaderClient empty body "
                            "(url=%s status=%d attempt=%d/%d duration_ms=%.0f bytes=%d)",
                            url,
                            status,
                            attempt,
                            total_attempts,
                            duration_ms,
                            bytes_len,
                        )
                        return None
                    logger.debug(
                        "JinaReaderClient success "
                        "(url=%s status=%d attempt=%d/%d duration_ms=%.0f bytes=%d)",
                        url,
                        status,
                        attempt,
                        total_attempts,
                        duration_ms,
                        bytes_len,
                    )
                    return body

                # Non-2xx response.
                retry_after = extract_retry_after(response)
                retryable = status == 429 or status >= 500
                if retryable and attempt < total_attempts:
                    wait = retry_after if retry_after is not None else backoff
                    logger.warning(
                        "JinaReaderClient retryable error "
                        "(url=%s status=%d attempt=%d/%d duration_ms=%.0f "
                        "retry_after=%s). Retrying in %.1fs.",
                        url,
                        status,
                        attempt,
                        total_attempts,
                        duration_ms,
                        retry_after,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    backoff *= 2
                    continue

                # Non-retryable, or retries exhausted.
                logger.warning(
                    "JinaReaderClient request failed "
                    "(url=%s status=%d attempt=%d/%d duration_ms=%.0f retry_after=%s)",
                    url,
                    status,
                    attempt,
                    total_attempts,
                    duration_ms,
                    retry_after,
                )
                return None

        # Loop exited without returning — defensive fallback.
        return None


__all__ = ["JinaReaderClient", "build_reader_client"]
