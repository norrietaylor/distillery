"""Tests for the ``output_mode`` argument on ``distillery_store``.

``output_mode="summary"`` is the lightweight path: the entry is persisted and
the handler returns immediately with just ``entry_id``. The dedup warning
block and conflict check block are skipped, which also drops the per-call
embedding-budget cost from three embeds to one. Callers that already have
their own dedup mechanism (for example the ``/gh-sync`` skill, which tracks
``metadata.external_id``) use this mode to avoid the extra embeddings.

The tests below exercise that behaviour end-to-end via ``_handle_store``:

* summary mode does not surface ``warnings`` / ``conflicts`` even when
  similar entries are present,
* summary mode does not call ``store.find_similar`` at all,
* summary mode requests a single embedding from the budget, not three,
* the default (no ``output_mode`` argument) preserves the existing
  behaviour,
* invalid values are rejected with ``INVALID_PARAMS``.

See issue #238.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.server import _handle_store
from distillery.store.duckdb import DuckDBStore
from tests.conftest import ControlledEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNIT_A = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def _make_config(conflict_threshold: float = 0.60) -> DistilleryConfig:
    """Build a config with a low conflict threshold so similar entries surface."""
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(model="controlled-test-8d"),
        classification=ClassificationConfig(
            confidence_threshold=0.6,
            conflict_threshold=conflict_threshold,
        ),
    )


def _make_budget_mock_connection() -> MagicMock:
    """Return a connection mock that satisfies ``record_and_check``'s call pattern."""
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = None  # no prior usage recorded
    return conn


# ---------------------------------------------------------------------------
# Fixtures (mirror test_conflict.py so the store uses the controlled provider)
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider(
    controlled_embedding_provider: ControlledEmbeddingProvider,
) -> ControlledEmbeddingProvider:
    return controlled_embedding_provider


@pytest.fixture
async def store(embedding_provider: ControlledEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Behaviour: summary mode skips dedup warnings and conflict checks
# ---------------------------------------------------------------------------


class TestSummaryModeSkipsAnalysis:
    async def test_summary_mode_returns_only_entry_id_when_similar_exists(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """With a near-duplicate already in the store, summary mode returns
        just ``entry_id`` — no ``warnings`` and no ``conflicts``."""
        existing_text = "Cats are nocturnal hunters"
        new_text = "Cats are nocturnal animals"
        # Identical vectors → similarity 1.0, well above dedup + conflict thresholds.
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(new_text, _UNIT_A)
        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        response = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "inbox",
                "author": "tester",
                "output_mode": "summary",
            },
            config,
        )
        data = parse_mcp_response(response)

        assert data.get("error") is None
        assert "entry_id" in data
        assert "warnings" not in data
        assert "warning_message" not in data
        assert "conflicts" not in data
        assert "conflict_message" not in data

    async def test_summary_mode_does_not_call_find_similar(self) -> None:
        """Summary mode must not invoke ``store.find_similar`` at all."""
        mock_store = AsyncMock()
        mock_store.store.return_value = "stored-id"
        mock_store.find_similar.side_effect = AssertionError(
            "find_similar must not be called in summary mode"
        )
        mock_store.connection = _make_budget_mock_connection()

        response = await _handle_store(
            mock_store,
            {
                "content": "trusted content that already deduplicated upstream",
                "entry_type": "github",
                "author": "tester",
                "output_mode": "summary",
            },
            _make_config(),
        )
        data = parse_mcp_response(response)

        assert data.get("error") is None
        assert data["entry_id"] == "stored-id"
        mock_store.find_similar.assert_not_called()

    async def test_summary_mode_requests_one_embedding_budget_unit(self) -> None:
        """Summary mode requests count=1 from ``record_and_check``; full is count=3."""
        mock_store = AsyncMock()
        mock_store.store.return_value = "stored-id"
        mock_store.find_similar.return_value = []  # unused in summary
        conn = _make_budget_mock_connection()
        mock_store.connection = conn

        # Patch the budget helper to observe the count argument.
        from distillery.mcp import budget as budget_module

        seen_counts: list[int] = []

        def _fake_record_and_check(_conn: object, _limit: int, count: int = 1) -> None:
            seen_counts.append(count)

        original = budget_module.record_and_check
        budget_module.record_and_check = _fake_record_and_check  # type: ignore[assignment]
        try:
            await _handle_store(
                mock_store,
                {
                    "content": "batch ingest payload",
                    "entry_type": "feed",
                    "author": "tester",
                    "output_mode": "summary",
                },
                _make_config(),
            )
        finally:
            budget_module.record_and_check = original  # type: ignore[assignment]

        assert seen_counts == [1]


# ---------------------------------------------------------------------------
# Behaviour: default remains the "full" analysis path
# ---------------------------------------------------------------------------


class TestDefaultModeIsFull:
    async def test_default_mode_runs_conflict_check(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        """Omitting ``output_mode`` keeps the existing conflict-check behaviour."""
        existing_text = "Dogs are pack animals"
        new_text = "Dogs are solitary animals"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(new_text, _UNIT_A)
        await store.store(make_entry(content=existing_text))

        config = _make_config(conflict_threshold=0.60)
        response = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "inbox",
                "author": "tester",
            },
            config,
        )
        data = parse_mcp_response(response)

        assert data.get("error") is None
        assert "entry_id" in data
        assert "conflicts" in data
        assert len(data["conflicts"]) >= 1

    async def test_explicit_full_mode_runs_conflict_check(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        existing_text = "Birds migrate in winter"
        new_text = "Birds do not migrate in winter"
        embedding_provider.register(existing_text, _UNIT_A)
        embedding_provider.register(new_text, _UNIT_A)
        await store.store(make_entry(content=existing_text))

        response = await _handle_store(
            store,
            {
                "content": new_text,
                "entry_type": "inbox",
                "author": "tester",
                "output_mode": "full",
            },
            _make_config(conflict_threshold=0.60),
        )
        data = parse_mcp_response(response)

        assert data.get("error") is None
        assert "conflicts" in data


# ---------------------------------------------------------------------------
# Validation: invalid output_mode
# ---------------------------------------------------------------------------


class TestOutputModeValidation:
    async def test_invalid_output_mode_returns_invalid_params(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        embedding_provider.register("anything", _UNIT_A)
        response = await _handle_store(
            store,
            {
                "content": "anything",
                "entry_type": "inbox",
                "author": "tester",
                "output_mode": "ids",  # valid for list but not for store
            },
            _make_config(),
        )
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"
        assert "output_mode" in data["message"]

    async def test_non_string_output_mode_returns_invalid_params(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        embedding_provider.register("anything", _UNIT_A)
        response = await _handle_store(
            store,
            {
                "content": "anything",
                "entry_type": "inbox",
                "author": "tester",
                "output_mode": 123,
            },
            _make_config(),
        )
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"
