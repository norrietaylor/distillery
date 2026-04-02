"""Standardized error codes and helpers for MCP tool handlers.

This module defines a canonical set of error codes used across all 22 MCP
tool handlers, eliminating inconsistencies like ``INVALID_INPUT`` vs
``VALIDATION_ERROR`` that made client-side error handling complex.

Error codes are used with the ``error_response()`` helper from ``_common.py``
to produce structured JSON error responses.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ToolErrorCode(StrEnum):
    """Standard error codes for all MCP tool handlers.

    Attributes:
        INVALID_PARAMS: Request parameters fail validation (e.g., missing
            required fields, wrong types, values out of range). This replaces
            both ``INVALID_INPUT`` and ``VALIDATION_ERROR`` to provide
            consistency across all handlers.
        NOT_FOUND: The requested resource does not exist (e.g., entry ID not
            found, user not found).
        CONFLICT: The operation conflicts with existing state (e.g.,
            deduplication detected, concurrent modification).
        INTERNAL: An unexpected server-side error occurred (e.g., database
            connection failure, embedding service timeout).
    """

    INVALID_PARAMS = "INVALID_PARAMS"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL"


def tool_error(code: ToolErrorCode | str, message: str) -> tuple[ToolErrorCode | str, str]:
    """Format a tool error as a (code, message) tuple for use with error_response().

    This helper ensures consistent error response formatting. It returns a tuple
    that can be passed to ``error_response(code, message)`` from ``_common.py``.

    Args:
        code: A ``ToolErrorCode`` enum value or string.
        message: Human-readable error description.

    Returns:
        A (code, message) tuple ready for passing to error_response().

    Example:
        >>> from distillery.mcp.tools._common import error_response
        >>> from distillery.mcp.tools._errors import tool_error, ToolErrorCode
        >>> code, msg = tool_error(ToolErrorCode.NOT_FOUND, "User not found")
        >>> error = error_response(code, msg)
    """
    return (code, message)


def validate_limit(
    value: Any,
    min_val: int = 1,
    max_val: int = 1000,
    default: int = 50,
) -> int | tuple[ToolErrorCode | str, str]:
    """Validate and coerce a limit parameter to an integer in [min_val, max_val].

    Used by handlers to validate ``limit`` parameters consistently. If validation
    fails, returns a (code, message) tuple suitable for ``error_response()``.

    Args:
        value: The value to validate (typically from tool arguments).
        min_val: Minimum allowed value (inclusive). Default: ``1``.
        max_val: Maximum allowed value (inclusive). Default: ``1000``.
        default: Default value if ``value`` is ``None``. Default: ``50``.

    Returns:
        On success: An integer in [min_val, max_val].
        On failure: A (code, message) tuple ready for ``error_response()``.

    Example:
        >>> from distillery.mcp.tools._errors import validate_limit
        >>> result = validate_limit(None, min_val=1, max_val=100, default=50)
        >>> assert result == 50
        >>> result = validate_limit(150, min_val=1, max_val=100)
        >>> assert isinstance(result, tuple)  # error case
    """
    if value is None:
        return default

    try:
        limit = int(value)
    except (TypeError, ValueError):
        return tool_error(
            ToolErrorCode.INVALID_PARAMS,
            f"Field 'limit' must be an integer, got: {type(value).__name__}",
        )

    if limit < min_val:
        return tool_error(
            ToolErrorCode.INVALID_PARAMS,
            f"Field 'limit' must be >= {min_val}",
        )

    if limit > max_val:
        return tool_error(
            ToolErrorCode.INVALID_PARAMS,
            f"Field 'limit' must be <= {max_val}",
        )

    return limit
