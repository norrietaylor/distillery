"""Shared type aliases for the ``distillery.mcp`` package."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

# Callback signature: (user_id, operation, entry_id, action, outcome) -> awaitable
AuditCallback = Callable[[str, str, str, str, str], Awaitable[None]]
