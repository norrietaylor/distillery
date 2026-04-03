"""Embedding budget tracker backed by DuckDB ``_meta`` table.

Tracks daily embedding API calls and enforces a configurable budget.
Counters are stored in ``_meta`` as ``embed_calls_YYYY-MM-DD`` keys so they
survive process restarts (important for Fly.io scale-to-zero).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EmbeddingBudgetError(Exception):
    """Raised when the daily embedding budget has been exhausted."""

    def __init__(self, used: int, limit: int) -> None:
        self.used = used
        self.limit = limit
        super().__init__(
            f"Daily embedding budget exceeded: {used}/{limit} calls used. "
            "Try again tomorrow or increase rate_limit.embedding_budget_daily."
        )


def _today_key() -> str:
    """Return the ``_meta`` key for today's embedding counter."""
    return f"embed_calls_{datetime.date.today().isoformat()}"


def get_daily_usage(conn: Any) -> int:
    """Read today's embedding call count from ``_meta``.

    Args:
        conn: An open DuckDB connection.

    Returns:
        The number of embedding calls made today.
    """
    key = _today_key()
    row = conn.execute("SELECT value FROM _meta WHERE key = ?", [key]).fetchone()
    return int(row[0]) if row else 0


def increment_usage(conn: Any, count: int = 1) -> int:
    """Atomically increment today's embedding call count.

    Uses ``INSERT … ON CONFLICT UPDATE`` so the counter is created on first
    call of the day.

    Args:
        conn: An open DuckDB connection.
        count: Number of calls to add (default 1).

    Returns:
        The new total for today.
    """
    key = _today_key()
    conn.execute(
        "INSERT INTO _meta (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = CAST(CAST(_meta.value AS INTEGER) + ? AS VARCHAR)",
        [key, str(count), count],
    )
    row = conn.execute("SELECT value FROM _meta WHERE key = ?", [key]).fetchone()
    return int(row[0]) if row else count


def check_budget(conn: Any, daily_limit: int, count: int = 1) -> None:
    """Check whether the daily embedding budget allows more calls.

    Args:
        conn: An open DuckDB connection.
        daily_limit: Maximum calls per day.  ``0`` means unlimited.
        count: Number of calls about to be made.

    Raises:
        EmbeddingBudgetError: If the budget would be exceeded.
    """
    if daily_limit <= 0:
        return  # unlimited
    used = get_daily_usage(conn)
    if used + count > daily_limit:
        raise EmbeddingBudgetError(used, daily_limit)


def record_and_check(conn: Any, daily_limit: int, count: int = 1) -> int:
    """Increment usage and check budget in one call.

    Call this *before* making the embedding API request so that the budget
    is enforced even if the process crashes mid-request.

    Args:
        conn: An open DuckDB connection.
        daily_limit: Maximum calls per day.  ``0`` means unlimited.
        count: Number of calls to record.

    Returns:
        The new total for today.

    Raises:
        EmbeddingBudgetError: If the budget would be exceeded.
    """
    if daily_limit <= 0:
        return increment_usage(conn, count)  # unlimited, still track
    check_budget(conn, daily_limit, count)
    return increment_usage(conn, count)