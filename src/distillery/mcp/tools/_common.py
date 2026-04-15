"""Shared utilities for MCP tool handlers.

This module contains common helpers used across multiple domain modules:
- User identity resolution
- Error and success response formatting
- Input validation helpers
"""

from __future__ import annotations

import json
from typing import Any

from mcp import types

# ---------------------------------------------------------------------------
# User identity helpers
# ---------------------------------------------------------------------------


def _get_authenticated_user() -> str:  # pragma: no cover — requires live OAuth context
    """Return the authenticated GitHub username, or ``""`` if auth is not active.

    Uses FastMCP's ``get_access_token()`` to retrieve the current request's
    access token.  The GitHub username is extracted from the JWT claims
    (``login`` field populated by the GitHubProvider).

    Returns ``""`` only when no auth is configured (stdio transport or
    ``auth=None``).  When a token is present but identity cannot be
    resolved, raises ``RuntimeError`` to fail closed rather than silently
    treating an authenticated-but-unresolvable request as anonymous.
    """
    try:
        from fastmcp.server.dependencies import get_access_token
    except ImportError:
        return ""

    token = get_access_token()
    if token is None:
        return ""

    # Extract username from claims.  Validate type to avoid str(None) → "None".
    raw_login = token.claims.get("login")
    if isinstance(raw_login, str) and raw_login:
        return raw_login

    raw_sub = token.claims.get("sub")
    if isinstance(raw_sub, str) and raw_sub:
        return raw_sub

    # Token present but no valid identity claim — fail closed.
    raise RuntimeError(
        "Authenticated request has no 'login' or 'sub' claim in access token. "
        "Cannot determine user identity for ownership checks."
    )


# ---------------------------------------------------------------------------
# Error response helpers
# ---------------------------------------------------------------------------


def error_response(
    code: str, message: str, details: dict[str, Any] | None = None
) -> list[types.TextContent]:
    """Build a structured error response as MCP content.

    Args:
        code: Short machine-readable error code (e.g. ``"NOT_FOUND"``).
        message: Human-readable error description.
        details: Optional extra context dict.

    Returns:
        A single-element list of :class:`~mcp.types.TextContent` with a JSON payload.
    """
    from distillery.security import sanitize_error

    message = sanitize_error(message)
    payload: dict[str, Any] = {"error": True, "code": code, "message": message}
    if details:
        payload["details"] = details
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]


def success_response(data: dict[str, Any]) -> list[types.TextContent]:
    """Build a structured success response as MCP content.

    Args:
        data: Payload to serialise as JSON.

    Returns:
        A single-element list of :class:`~mcp.types.TextContent`.
    """
    return [types.TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------


def validate_required(arguments: dict[str, Any], *fields: str) -> str | None:
    """Return an error message if any required field is missing from *arguments*.

    A field is considered missing if it is absent, ``None``, or (for strings)
    empty.  Values such as ``0`` and ``False`` are **not** treated as missing.

    Args:
        arguments: The tool argument dict.
        *fields: Field names that must be present and non-empty.

    Returns:
        An error message string if validation fails, or ``None`` if all fields
        are present.
    """
    missing = [
        f
        for f in fields
        if arguments.get(f) is None
        or (isinstance(arguments.get(f), str) and not arguments.get(f))
    ]
    if missing:
        return f"Missing required fields: {', '.join(missing)}"
    return None


def validate_type(
    arguments: dict[str, Any], field: str, expected_type: type | tuple[type, ...], label: str
) -> str | None:
    """Return an error message if *field* is not of *expected_type*.

    Args:
        arguments: The tool argument dict.
        field: Key to check.
        expected_type: Python type that the value must satisfy.
        label: Human-readable type name for the error message.

    Returns:
        An error message string or ``None``.
    """
    value = arguments.get(field)
    if value is not None and not isinstance(value, expected_type):
        return f"Field '{field}' must be a {label}"
    return None


def validate_enum(
    arguments: dict[str, Any], field: str, valid_values: set[str], label: str = ""
) -> str | None:
    """Return an error message if *field* is not one of *valid_values*.

    Args:
        arguments: The tool argument dict.
        field: Key to check.
        valid_values: Allowed string values.
        label: Human-readable description for the error message
            (defaults to *field* when empty).

    Returns:
        An error message string or ``None``.
    """
    val = arguments.get(field)
    if val is not None and val not in valid_values:
        desc = label or field
        return f"Invalid {desc} {val!r}. Must be one of: {', '.join(sorted(valid_values))}."
    return None


def validate_positive_int(
    arguments: dict[str, Any], field: str, default: int | None = None
) -> int | tuple[str, str]:
    """Validate and return a positive integer from *arguments*.

    Args:
        arguments: The tool argument dict.
        field: Key to check.
        default: Default value if *field* is absent.

    Returns:
        On success: the validated positive integer.
        On failure: a ``(code, message)`` tuple suitable for ``error_response()``.
    """
    from distillery.mcp.tools._errors import ToolErrorCode

    raw = arguments.get(field, default)
    if raw is None:
        return (ToolErrorCode.INVALID_PARAMS.value, f"Field '{field}' is required.")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        return (ToolErrorCode.INVALID_PARAMS.value, f"Field '{field}' must be a positive integer.")
    return int(raw)