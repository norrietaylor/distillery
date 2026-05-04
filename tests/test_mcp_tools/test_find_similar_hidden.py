"""Tests for distillery_find_similar hidden-connections params (#140).

Covers the additive parameters added to ``_handle_find_similar``:

  - ``source_entry_id``: when set, the source entry's content is used as the
    similarity probe (if ``content`` is omitted) and the source entry is
    always self-excluded from results.
  - ``exclude_linked``: when ``True``, results also exclude entries that are
    already linked to ``source_entry_id`` via ``entry_relations``.
  - ``excluded_linked_count``: response field reported only when one of the
    new params is in use.

All tests use the ControlledEmbeddingProvider for deterministic similarity.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Fixtures (mirror tests/test_find_similar_extended.py)
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
    return load_config()


# ===========================================================================
# Hidden-connections behaviour
# ===========================================================================


class TestExcludeLinked:
    async def test_exclude_linked_filters_linked_entries(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        # All three entries embed to the same unit vector so they all match.
        embedding_provider.register("source content A", _UNIT_A)
        embedding_provider.register("linked content B", _UNIT_A)
        embedding_provider.register("unrelated content C", _UNIT_A)

        a = make_entry(content="source content A")
        b = make_entry(content="linked content B")
        c = make_entry(content="unrelated content C")
        a_id = await store.store(a)
        b_id = await store.store(b)
        c_id = await store.store(c)

        # Link A -> B (any relation_type, any direction).
        await store.add_relation(a_id, b_id, "link")

        response = await _handle_find_similar(
            store,
            {
                "source_entry_id": a_id,
                "exclude_linked": True,
                "threshold": 0.5,
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        result_ids = {r["entry"]["id"] for r in data["results"]}
        assert b_id not in result_ids, "B is linked to A and must be filtered out"
        assert c_id in result_ids, "C is unrelated and must remain in results"
        assert a_id not in result_ids, "Source entry must always be self-excluded"
        assert data.get("excluded_linked_count", 0) >= 1

    async def test_source_entry_id_uses_entry_content(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("auth flow", _UNIT_A)
        embedding_provider.register("other auth note", _UNIT_A)

        source = make_entry(content="auth flow")
        other = make_entry(content="other auth note")
        source_id = await store.store(source)
        other_id = await store.store(other)

        # No content provided — handler must use source.content as the probe.
        response = await _handle_find_similar(
            store,
            {"source_entry_id": source_id, "threshold": 0.5},
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        assert data["count"] >= 1
        result_ids = {r["entry"]["id"] for r in data["results"]}
        assert source_id not in result_ids, "Source entry must be self-excluded"
        assert other_id in result_ids

    async def test_source_entry_id_self_excluded_even_without_exclude_linked(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("self exclude probe", _UNIT_A)
        embedding_provider.register("self exclude other", _UNIT_A)

        source = make_entry(content="self exclude probe")
        other = make_entry(content="self exclude other")
        source_id = await store.store(source)
        other_id = await store.store(other)

        response = await _handle_find_similar(
            store,
            {
                "content": "self exclude probe",
                "source_entry_id": source_id,
                "threshold": 0.5,
                # exclude_linked omitted (default False)
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        result_ids = {r["entry"]["id"] for r in data["results"]}
        assert source_id not in result_ids, "Source entry must be self-excluded"
        assert other_id in result_ids
        # Field is present whenever source_entry_id is set.
        assert "excluded_linked_count" in data

    async def test_exclude_linked_without_source_entry_id_returns_invalid_params(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("no source needed", _UNIT_A)

        response = await _handle_find_similar(
            store,
            {"content": "no source needed", "exclude_linked": True},
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"
        assert "source_entry_id" in data["message"]

    async def test_unknown_source_entry_id_returns_not_found(
        self,
        store: DuckDBStore,
        cfg: DistilleryConfig,
    ) -> None:
        missing_id = "00000000-0000-0000-0000-000000000000"
        response = await _handle_find_similar(
            store,
            {"source_entry_id": missing_id},
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert data.get("error") is True
        assert data["code"] == "NOT_FOUND"
        assert missing_id in data["message"]

    async def test_excluded_linked_count_omitted_when_no_source(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("plain probe", _UNIT_A)

        response = await _handle_find_similar(
            store,
            {"content": "plain probe"},
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        assert "excluded_linked_count" not in data

    async def test_excluded_linked_count_zero_when_no_overlap(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        # Source content is anti-aligned with the probe so the source is
        # below threshold and not in the initial result set; with no
        # relations the filter has nothing to drop, so the count is 0.
        anti_unit = [-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        embedding_provider.register("anti source", anti_unit)
        embedding_provider.register("matching probe target", _UNIT_A)
        embedding_provider.register("explicit probe", _UNIT_A)

        source = make_entry(content="anti source")
        match = make_entry(content="matching probe target")
        source_id = await store.store(source)
        match_id = await store.store(match)

        response = await _handle_find_similar(
            store,
            {
                "content": "explicit probe",
                "source_entry_id": source_id,
                "exclude_linked": True,
                "threshold": 0.6,
            },
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        assert data["excluded_linked_count"] == 0
        # Match should still be present since it's unrelated to source.
        result_ids = {r["entry"]["id"] for r in data["results"]}
        assert source_id not in result_ids
        assert match_id in result_ids
