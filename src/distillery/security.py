"""Security utilities for the Distillery system.

Provides :func:`sanitize_error` for redacting API keys and secrets from
error messages, log output, and MCP responses, plus a :class:`logging.Filter`
that applies the same sanitization to all log records.
"""

from __future__ import annotations

import logging
import re

# Patterns that match known API key formats.  Each pattern captures the
# first 4 characters as a prefix so the redacted output hints at the key
# type without exposing the secret.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # Jina: jina_<key>
    re.compile(r"\b(jina_\w{0,4})\w+"),
    # OpenAI: sk-<key>
    re.compile(r"\b(sk-\w{0,4})\w+"),
    # GitHub personal access token (classic): ghp_<key>
    re.compile(r"\b(ghp_\w{0,4})\w+"),
    # GitHub OAuth access token: gho_<key>
    re.compile(r"\b(gho_\w{0,4})\w+"),
    # GitHub fine-grained PAT: github_pat_<key>
    re.compile(r"\b(github_pat_\w{0,4})\w+"),
]


def sanitize_error(message: str) -> str:
    """Redact known API key patterns from *message*.

    Replaces the secret portion of any matched key with ``****`` while
    preserving the first few characters as a type hint.

    Args:
        message: The string to sanitize.

    Returns:
        The sanitized string with secrets redacted.
    """
    for pattern in _SECRET_PATTERNS:
        message = pattern.sub(r"\1****", message)
    return message


class SecretRedactFilter(logging.Filter):
    """A :class:`logging.Filter` that redacts API keys from log records.

    Attach to a logger or handler to ensure secrets never appear in log
    output, even if accidentally included in exception messages or
    debug strings.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize the log record message and args.

        Always returns ``True`` so the record is emitted (this is a
        mutation filter, not a suppression filter).
        """
        if isinstance(record.msg, str):
            record.msg = sanitize_error(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: sanitize_error(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    sanitize_error(str(a)) if isinstance(a, str) else a for a in record.args
                )
        return True
