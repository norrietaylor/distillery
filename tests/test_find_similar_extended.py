"""Tests for _handle_find_similar extended parameters (T02.2).

Tests cover the new optional parameters added to _handle_find_similar:
  - dedup_action: bool — triggers dedup check and adds dedup field
  - conflict_check: bool — triggers conflict pass 1 and adds conflict_prompt
  - llm_responses: list[dict] | None — triggers conflict pass 2 evaluation

All tests use the ControlledEmbeddingProvider for deterministic similarity.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from distillery.config import DistilleryConfig, load_config
from distillery.mcp.tools.search import _handle_find_similar
from distillery.store.duckdb import DuckDBStore
from tests.conftest import ControlledEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Unit vectors for deterministic similarity
# ---------------------------------------------------------------------------

_UNIT_A = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
_UNIT_B = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture
def cfg() -> DistilleryConfig:
    """Return a DistilleryConfig with default classification thresholds."""
    return load_config()


# ===========================================================================
# Baseline: existing behaviour unchanged
# ===========================================================================


class TestFindSimilarBaseline:
    """Existing _handle_find_similar behaviour is unchanged."""

    async def test_basic_find_similar(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("existing text", _UNIT_A)
        embedding_provider.register("query text", _UNIT_A)
        await store.store(make_entry(content="existing text"))

        response = await _handle_find_similar(
            store, {"content": "query text", "threshold": 0.5}, cfg=cfg
        )
        data = parse_mcp_response(response)
        assert data["count"] >= 1
        assert "results" in data
        assert "threshold" in data

    async def test_no_dedup_or_conflict_fields_by_default(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("default test", _UNIT_A)
        response = await _handle_find_similar(store, {"content": "default test"}, cfg=cfg)
        data = parse_mcp_response(response)
        assert "dedup" not in data
        assert "conflict_evaluation" not in data
        assert "conflict_candidates_count" not in data

    async def test_missing_content_returns_error(
        self,
        store: DuckDBStore,
        cfg: DistilleryConfig,
    ) -> None:
        response = await _handle_find_similar(store, {}, cfg=cfg)
        data = parse_mcp_response(response)
        assert "error" in data


# ===========================================================================
# dedup_action mode
# ===========================================================================


class TestFindSimilarDedupAction:
    """dedup_action=True adds a dedup field with action and similar_entries."""

    async def test_dedup_action_returns_dedup_field(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("dedup existing", _UNIT_A)
        embedding_provider.register("dedup query", _UNIT_A)
        await store.store(make_entry(content="dedup existing"))

        response = await _handle_find_similar(
            store,
            {"content": "dedup query", "threshold": 0.5, "dedup_action": True},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "dedup" in data
        dedup = data["dedup"]
        assert "action" in dedup
        assert dedup["action"] in ("create", "skip", "merge", "link")
        assert "similar_entries" in dedup

    async def test_dedup_action_empty_store_returns_create(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("no dupes", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {"content": "no dupes", "dedup_action": True},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert data["dedup"]["action"] == "create"

    async def test_dedup_action_identical_content_returns_skip(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("identical content", _UNIT_A)
        embedding_provider.register("identical query", _UNIT_A)
        await store.store(make_entry(content="identical content"))

        response = await _handle_find_similar(
            store,
            {"content": "identical query", "threshold": 0.5, "dedup_action": True},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert data["dedup"]["action"] == "skip"
        assert len(data["dedup"]["similar_entries"]) >= 1

    async def test_dedup_action_false_omits_dedup_field(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("no dedup", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {"content": "no dedup", "dedup_action": False},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "dedup" not in data

    async def test_dedup_action_without_config_returns_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        embedding_provider.register("no cfg dedup", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {"content": "no cfg dedup", "dedup_action": True},
            cfg=None,
        )
        data = parse_mcp_response(response)
        assert "error" in data
        assert "configuration" in data["message"].lower()

    async def test_dedup_action_error_returns_dedup_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("dedup err content", _UNIT_A)

        with patch(
            "distillery.mcp.tools.quality.run_dedup_check",
            side_effect=RuntimeError("dedup boom"),
        ):
            response = await _handle_find_similar(
                store,
                {"content": "dedup err content", "dedup_action": True},
                cfg=cfg,
            )
        data = parse_mcp_response(response)
        assert "error" in data
        assert data["code"] == "DEDUP_ERROR"


# ===========================================================================
# conflict_check mode (pass 1 — discovery)
# ===========================================================================


class TestFindSimilarConflictCheckPass1:
    """conflict_check=True without llm_responses runs pass 1 discovery."""

    async def test_conflict_check_adds_conflict_candidates_count(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("conflict existing", _UNIT_A)
        embedding_provider.register("conflict query", _UNIT_A)
        await store.store(make_entry(content="conflict existing"))

        response = await _handle_find_similar(
            store,
            {"content": "conflict query", "threshold": 0.5, "conflict_check": True},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "conflict_candidates_count" in data
        assert isinstance(data["conflict_candidates_count"], int)
        assert "conflict_message" in data

    async def test_conflict_check_attaches_prompt_to_matching_results(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("prompt existing", _UNIT_A)
        embedding_provider.register("prompt query", _UNIT_A)
        await store.store(make_entry(content="prompt existing"))

        response = await _handle_find_similar(
            store,
            {"content": "prompt query", "threshold": 0.5, "conflict_check": True},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        # At least one result should have a conflict_prompt
        has_prompt = any("conflict_prompt" in r for r in data["results"])
        assert has_prompt, "Expected at least one result with conflict_prompt"

    async def test_conflict_check_empty_store(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("no conflicts", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {"content": "no conflicts", "conflict_check": True},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert data["conflict_candidates_count"] == 0

    async def test_conflict_check_false_omits_conflict_fields(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("no conflict mode", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {"content": "no conflict mode", "conflict_check": False},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "conflict_candidates_count" not in data
        assert "conflict_message" not in data

    async def test_conflict_check_without_config_returns_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
    ) -> None:
        embedding_provider.register("no cfg conflict", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {"content": "no cfg conflict", "conflict_check": True},
            cfg=None,
        )
        data = parse_mcp_response(response)
        assert "error" in data

    async def test_conflict_discovery_error_returns_conflict_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("disc err content", _UNIT_A)

        with patch(
            "distillery.mcp.tools.quality.run_conflict_discovery",
            side_effect=RuntimeError("discovery boom"),
        ):
            response = await _handle_find_similar(
                store,
                {"content": "disc err content", "conflict_check": True},
                cfg=cfg,
            )
        data = parse_mcp_response(response)
        assert "error" in data
        assert data["code"] == "CONFLICT_ERROR"


# ===========================================================================
# conflict_check mode (pass 2 — evaluation with llm_responses)
# ===========================================================================


class TestFindSimilarConflictCheckPass2:
    """conflict_check=True with llm_responses runs pass 2 evaluation."""

    async def test_llm_responses_returns_conflict_evaluation(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("eval2 existing", _UNIT_A)
        embedding_provider.register("eval2 query", _UNIT_A)
        entry = make_entry(content="eval2 existing")
        entry_id = await store.store(entry)

        llm_responses = [
            {"entry_id": entry_id, "is_conflict": True, "reasoning": "Direct contradiction"},
        ]
        response = await _handle_find_similar(
            store,
            {
                "content": "eval2 query",
                "threshold": 0.5,
                "conflict_check": True,
                "llm_responses": llm_responses,
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "conflict_evaluation" in data
        ce = data["conflict_evaluation"]
        assert ce["has_conflicts"] is True
        assert len(ce["conflicts"]) == 1

    async def test_llm_responses_no_conflict(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("eval2 no existing", _UNIT_A)
        embedding_provider.register("eval2 no query", _UNIT_A)
        entry = make_entry(content="eval2 no existing")
        entry_id = await store.store(entry)

        llm_responses = [
            {"entry_id": entry_id, "is_conflict": False, "reasoning": "Not a conflict"},
        ]
        response = await _handle_find_similar(
            store,
            {
                "content": "eval2 no query",
                "threshold": 0.5,
                "conflict_check": True,
                "llm_responses": llm_responses,
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert data["conflict_evaluation"]["has_conflicts"] is False

    async def test_llm_responses_without_conflict_check_returns_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("orphan llm", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {
                "content": "orphan llm",
                "conflict_check": False,
                "llm_responses": [{"entry_id": "x", "is_conflict": True, "reasoning": "r"}],
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "error" in data
        assert "conflict_check" in data["message"].lower()

    async def test_llm_responses_invalid_type_returns_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("bad type llm", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {
                "content": "bad type llm",
                "conflict_check": True,
                "llm_responses": "not_a_list",
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "error" in data

    async def test_llm_responses_missing_entry_id_returns_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("missing eid", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {
                "content": "missing eid",
                "conflict_check": True,
                "llm_responses": [{"is_conflict": True, "reasoning": "r"}],
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "error" in data
        assert "entry_id" in data["message"]

    async def test_llm_responses_missing_is_conflict_returns_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("missing ic", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {
                "content": "missing ic",
                "conflict_check": True,
                "llm_responses": [{"entry_id": "x", "reasoning": "r"}],
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "error" in data
        assert "is_conflict" in data["message"]

    async def test_llm_responses_non_dict_item_returns_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("non dict item", _UNIT_A)
        response = await _handle_find_similar(
            store,
            {
                "content": "non dict item",
                "conflict_check": True,
                "llm_responses": ["not_a_dict"],
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "error" in data

    async def test_conflict_evaluation_error_returns_conflict_error(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("eval err content", _UNIT_A)

        with patch(
            "distillery.mcp.tools.quality.run_conflict_evaluation",
            side_effect=RuntimeError("eval boom"),
        ):
            response = await _handle_find_similar(
                store,
                {
                    "content": "eval err content",
                    "conflict_check": True,
                    "llm_responses": [{"entry_id": "x", "is_conflict": True, "reasoning": "r"}],
                },
                cfg=cfg,
            )
        data = parse_mcp_response(response)
        assert "error" in data
        assert data["code"] == "CONFLICT_ERROR"


# ===========================================================================
# Combined modes
# ===========================================================================


class TestFindSimilarCombinedModes:
    """Both dedup_action and conflict_check can be enabled simultaneously."""

    async def test_both_dedup_and_conflict(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("both existing", _UNIT_A)
        embedding_provider.register("both query", _UNIT_A)
        await store.store(make_entry(content="both existing"))

        response = await _handle_find_similar(
            store,
            {
                "content": "both query",
                "threshold": 0.5,
                "dedup_action": True,
                "conflict_check": True,
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "dedup" in data
        assert "conflict_candidates_count" in data
        assert "results" in data

    async def test_dedup_and_conflict_with_llm_responses(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("combo existing", _UNIT_A)
        embedding_provider.register("combo query", _UNIT_A)
        entry = make_entry(content="combo existing")
        entry_id = await store.store(entry)

        response = await _handle_find_similar(
            store,
            {
                "content": "combo query",
                "threshold": 0.5,
                "dedup_action": True,
                "conflict_check": True,
                "llm_responses": [
                    {"entry_id": entry_id, "is_conflict": True, "reasoning": "contradiction"},
                ],
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        assert "dedup" in data
        assert "conflict_evaluation" in data
        assert data["conflict_evaluation"]["has_conflicts"] is True