"""Content truncation utilities for feed item embedding.

Provides a safety-net pre-truncation layer to ensure feed item content stays
within the Jina embedding model's 8194-token input limit.  The Jina API also
accepts ``truncate: true`` in the request payload, but pre-truncating avoids
wasting bandwidth on oversized payloads and provides a clear log trail.

The conservative character limit of 30 000 characters is safely under 8194
tokens for all common languages (English averages ~4 characters per token).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Conservative character limit that stays safely under Jina's 8194-token cap.
# English text averages ~4 chars/token, so 30 000 chars ≈ 7 500 tokens.
MAX_CONTENT_CHARS = 30_000

_TRUNCATED_SUFFIX = " [truncated]"


def truncate_content(text: str, max_chars: int = MAX_CONTENT_CHARS) -> str:
    """Truncate *text* to at most *max_chars* characters.

    When truncation occurs a ``[truncated]`` marker is appended and a
    DEBUG-level log message is emitted.

    Args:
        text: The content string to truncate.
        max_chars: Maximum number of characters to keep.  Defaults to
            :data:`MAX_CONTENT_CHARS` (30 000).

    Returns:
        The original string if it fits, or a truncated version with a
        ``[truncated]`` suffix.
    """
    if len(text) <= max_chars:
        return text

    logger.debug(
        "truncate_content: truncating %d chars to %d chars",
        len(text),
        max_chars,
    )
    suffix = _TRUNCATED_SUFFIX
    if max_chars <= len(suffix):
        return suffix[:max_chars]
    cutoff = max_chars - len(suffix)
    return text[:cutoff] + suffix
