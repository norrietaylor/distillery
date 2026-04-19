"""Shared exceptions for embedding providers.

These exceptions let calling code distinguish upstream provider issues
(rate limits, quotas, server errors) from generic ``RuntimeError`` so the
MCP layer can surface structured errors with ``retry_after`` hints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider call fails after all retries.

    Carries structured metadata about the upstream failure so callers can
    surface actionable errors (e.g. include ``retry_after`` in an MCP
    response when the provider is rate limiting us).

    Attributes:
        provider: Short provider identifier (``"jina"``, ``"openai"``).
        status_code: HTTP status code from the upstream response, if any.
        retry_after: Seconds the client should wait before retrying, parsed
            from the upstream ``Retry-After`` header when present. ``None``
            when the provider did not supply one.
        endpoint: The provider endpoint that was called.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        retry_after: float | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retry_after = retry_after
        self.endpoint = endpoint

    @property
    def is_rate_limited(self) -> bool:
        """Return True when the upstream indicated rate limiting (HTTP 429)."""
        return self.status_code == 429


def parse_retry_after(header_value: object) -> float | None:
    """Parse a ``Retry-After`` header value into seconds.

    Supports both forms permitted by RFC 7231:

    * Integer (or float) number of seconds (delta-seconds).
    * HTTP-date (e.g. ``Wed, 21 Oct 2015 07:28:00 GMT``) — converted
      to the number of seconds remaining until that instant.  Past
      dates clamp to ``0.0`` rather than returning a negative hint.

    Args:
        header_value: Raw header string or ``None``.  Non-string values
            are treated as missing.

    Returns:
        Non-negative float seconds, or ``None`` when the header is missing
        or unparseable.
    """
    if not isinstance(header_value, str) or not header_value:
        return None
    value = header_value.strip()
    try:
        seconds = float(value)
    except ValueError:
        # Not delta-seconds; try the HTTP-date form.
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at is None:
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        delta = (retry_at - datetime.now(UTC)).total_seconds()
        return max(0.0, delta)
    if seconds < 0:
        return None
    return seconds


def extract_retry_after(response: object) -> float | None:
    """Safely extract and parse ``Retry-After`` from a response-like object.

    Tolerates objects that don't expose ``headers`` (e.g. mocks), returning
    ``None`` in that case.
    """
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("Retry-After")
    except Exception:  # noqa: BLE001 — mocks and non-mapping objects
        return None
    return parse_retry_after(raw)


__all__ = ["EmbeddingProviderError", "extract_retry_after", "parse_retry_after"]
