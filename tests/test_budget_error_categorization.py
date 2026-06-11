"""Tests for budget-check failure categorization in crud handlers (issue #557).

``_handle_store`` / ``_handle_store_batch`` / ``_handle_correct`` previously
collapsed every non-budget ``record_and_check`` failure to a bare
``INTERNAL: Failed to check embedding budget``.  They must now distinguish:

  - ``EmbeddingBudgetError``          -> ``BUDGET_EXCEEDED`` (not retryable)
  - transient DuckDB faults           -> ``STORE_TRANSIENT`` (retry with backoff)
  - anything else                     -> ``INTERNAL`` (cause-specific message)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import duckdb
import pytest

from distillery.config import DistilleryConfig, StorageConfig
from distillery.mcp.budget import EmbeddingBudgetError
from distillery.mcp.tools.crud import _handle_correct, _handle_store, _handle_store_batch
from tests.conftest import make_entry, parse_mcp_response

pytestmark = pytest.mark.unit

_OLD_BARE_MESSAGE = "Failed to check embedding budget"

_STORE_ARGS = {"content": "test", "entry_type": "inbox", "author": "bob"}
_BATCH_ARGS = {"entries": [{"content": "First entry", "author": "alice"}]}
_CORRECT_ARGS = {"wrong_entry_id": "some-id", "content": "corrected content"}


def _make_mock_store() -> AsyncMock:
    """Build a mock store sufficient to reach the budget check in all handlers."""
    store = AsyncMock()
    store.connection = None  # budget check uses this
    store.get.return_value = make_entry()  # _handle_correct fetches the original
    return store


def _make_cfg() -> DistilleryConfig:
    """In-memory config so the db-size gate is skipped and budget check runs."""
    return DistilleryConfig(storage=StorageConfig(database_path=":memory:"))


async def _invoke(handler, store: AsyncMock, cfg: DistilleryConfig) -> dict:  # type: ignore[no-untyped-def]
    args = {
        _handle_store: _STORE_ARGS,
        _handle_store_batch: _BATCH_ARGS,
        _handle_correct: _CORRECT_ARGS,
    }[handler]
    return parse_mcp_response(await handler(store, dict(args), cfg=cfg))


@pytest.mark.parametrize("handler", [_handle_store, _handle_store_batch, _handle_correct])
async def test_transient_db_error_returns_store_transient(handler) -> None:  # type: ignore[no-untyped-def]
    """An aborted/poisoned transaction maps to STORE_TRANSIENT, not INTERNAL."""
    store = _make_mock_store()
    exc = duckdb.TransactionException(
        "TransactionContext Error: Current transaction is aborted (please ROLLBACK)"
    )
    with patch("distillery.mcp.budget.record_and_check", side_effect=exc):
        data = await _invoke(handler, store, _make_cfg())

    assert data["error"] is True
    assert data["code"] == "STORE_TRANSIENT"
    assert data["message"] == (
        "Embedding budget check failed (transient database error) — retry with backoff."
    )
    # Rollback recovery must still run for transient failures.
    store.rollback.assert_awaited_once()


@pytest.mark.parametrize("handler", [_handle_store, _handle_store_batch, _handle_correct])
async def test_lock_contention_returns_store_transient(handler) -> None:  # type: ignore[no-untyped-def]
    """File-lock contention (duckdb.IOException) is also categorized as transient."""
    store = _make_mock_store()
    exc = duckdb.IOException("Could not set lock on file: Conflicting lock is held")
    with patch("distillery.mcp.budget.record_and_check", side_effect=exc):
        data = await _invoke(handler, store, _make_cfg())

    assert data["error"] is True
    assert data["code"] == "STORE_TRANSIENT"


@pytest.mark.parametrize("handler", [_handle_store, _handle_store_batch, _handle_correct])
async def test_budget_exhausted_still_returns_budget_exceeded(handler) -> None:  # type: ignore[no-untyped-def]
    """EmbeddingBudgetError keeps its dedicated BUDGET_EXCEEDED branch."""
    store = _make_mock_store()
    exc = EmbeddingBudgetError(used=5, limit=5)
    with patch("distillery.mcp.budget.record_and_check", side_effect=exc):
        data = await _invoke(handler, store, _make_cfg())

    assert data["error"] is True
    assert data["code"] == "BUDGET_EXCEEDED"
    assert "budget exceeded" in data["message"].lower()


@pytest.mark.parametrize("handler", [_handle_store, _handle_store_batch, _handle_correct])
async def test_unexpected_error_returns_internal_with_specific_message(handler) -> None:  # type: ignore[no-untyped-def]
    """Non-DB, non-budget failures stay INTERNAL with a cause-specific message."""
    store = _make_mock_store()
    with patch("distillery.mcp.budget.record_and_check", side_effect=RuntimeError("boom")):
        data = await _invoke(handler, store, _make_cfg())

    assert data["error"] is True
    assert data["code"] == "INTERNAL"
    assert data["message"] == "Embedding budget check failed (unexpected error)"
    # The misleading bare string must be gone in all branches.
    assert data["message"] != _OLD_BARE_MESSAGE
    store.rollback.assert_awaited_once()
