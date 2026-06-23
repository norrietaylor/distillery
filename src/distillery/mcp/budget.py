"""Embedding budget tracker backed by DuckDB ``_meta`` table.

Tracks daily embedding API calls and enforces a configurable budget.
Counters are stored in ``_meta`` as ``embed_calls_YYYY-MM-DD`` keys so they
survive process restarts (important for Fly.io scale-to-zero).

The budget is an **opt-in cost ceiling**, not a rate limiter.  By default
``rate_limit.embedding_budget_daily`` is ``0`` (unlimited) and the
embedding provider's own rate limiter (Jina / OpenAI) is the source of
truth — it already returns HTTP 429 with ``Retry-After`` hints.  Set the
budget to a positive integer only when you want a hard daily cost
guard.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Counter writes are serialized by the store's ``_conn_lock``: production
# callers reach this module only via ``DuckDBStore.record_embedding_usage``,
# which runs the upsert under that lock (issue #655).  No module-level lock is
# needed — adding one would let the budget write race the store's serialized
# writes/CHECKPOINT on the non-thread-safe connection, which is the very bug
# the store-side serialization fixes.


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
    # Use a per-call cursor: another execute() on the shared connection would
    # invalidate a pending result set ("No open result set") under concurrency.
    row = conn.cursor().execute("SELECT value FROM _meta WHERE key = ?", [key]).fetchone()
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
    return _increment_locked(conn, count)


def _increment_locked(conn: Any, count: int) -> int:
    """Upsert today's counter and return the new total.

    Callers must already serialize access to *conn* (production goes through
    the store's ``_conn_lock`` via ``DuckDBStore.record_embedding_usage``).
    """
    key = _today_key()
    # Use a per-call cursor so a pending result set on the shared connection
    # is not invalidated mid-fetch.
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO _meta (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET "
        "value = CAST(CAST(_meta.value AS INTEGER) + ? AS VARCHAR)",
        [key, str(count), count],
    )
    row = cur.execute("SELECT value FROM _meta WHERE key = ?", [key]).fetchone()
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
    # Check then increment in one critical section so concurrent callers can't
    # all pass the read and collectively overspend the cap.  The caller
    # serializes access to *conn* (production: the store's ``_conn_lock``).
    used = get_daily_usage(conn)
    if used + count > daily_limit:
        raise EmbeddingBudgetError(used, daily_limit)
    return _increment_locked(conn, count)
