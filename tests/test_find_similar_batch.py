"""Tests for the ``distillery_find_similar`` batch mode (``source_entry_ids``).

Covers the server-side batch path that reuses each seed's STORED embedding (no
re-embed, no embedding-budget spend) and runs all similarity queries in one read
acquisition:

  - store.find_similar_by_ids: keyed map, missing-embedding seed -> [],
    self-exclusion, linked exclusion, threshold + limit honoured per seed.
  - store.find_similar_by_id: single-seed stored-vector reuse (returns None when
    no stored embedding).
  - the MCP handler batch path: payload shape, zero embedding budget, and
    INVALID_PARAMS validation (forbidden companions, empty / oversized list).
  - the single source_entry_id handler path now reuses the stored vector (no
    embed) and still self/linked-excludes.

Uses the ControlledEmbeddingProvider for deterministic similarity.
"""

from __future__ import annotations

import pytest

from distillery.config import DistilleryConfig, load_config
from distillery.mcp.tools.search import _handle_find_similar
from distillery.store.duckdb import DuckDBStore
from tests.conftest import ControlledEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Unit vectors for deterministic similarity (8D ControlledEmbeddingProvider)
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
    return load_config()


# ===========================================================================
# Store: find_similar_by_ids
# ===========================================================================


class TestFindSimilarByIds:
    async def test_returns_map_keyed_by_every_requested_id(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("seed one", _UNIT_A)
        embedding_provider.register("seed two", _UNIT_B)
        s1 = await store.store(make_entry(content="seed one"))
        s2 = await store.store(make_entry(content="seed two"))

        out = await store.find_similar_by_ids(
            [s1, s2], threshold=0.5, limit=5, exclude_linked=False
        )

        assert set(out.keys()) == {s1, s2}

    async def test_missing_embedding_maps_to_empty_list(self, store: DuckDBStore) -> None:
        missing = "00000000-0000-0000-0000-000000000000"
        out = await store.find_similar_by_ids(
            [missing], threshold=0.5, limit=5, exclude_linked=False
        )
        assert out == {missing: []}

    async def test_self_exclusion(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("alpha", _UNIT_A)
        embedding_provider.register("alpha twin", _UNIT_A)
        s1 = await store.store(make_entry(content="alpha"))
        twin = await store.store(make_entry(content="alpha twin"))

        out = await store.find_similar_by_ids([s1], threshold=0.5, limit=5, exclude_linked=False)

        result_ids = {sr.entry.id for sr in out[s1]}
        assert s1 not in result_ids, "seed must never appear in its own results"
        assert twin in result_ids

    async def test_exclude_linked_removes_linked_entries(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("src", _UNIT_A)
        embedding_provider.register("linked", _UNIT_A)
        embedding_provider.register("unlinked", _UNIT_A)
        src = await store.store(make_entry(content="src"))
        linked = await store.store(make_entry(content="linked"))
        unlinked = await store.store(make_entry(content="unlinked"))
        await store.add_relation(src, linked, "link")

        out = await store.find_similar_by_ids([src], threshold=0.5, limit=5, exclude_linked=True)
        result_ids = {sr.entry.id for sr in out[src]}

        assert linked not in result_ids, "linked entry must be excluded"
        assert unlinked in result_ids
        assert src not in result_ids

    async def test_exclude_linked_incoming_direction(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        # Relation points TO the seed (seed is to_id) — must still be excluded.
        embedding_provider.register("seedX", _UNIT_A)
        embedding_provider.register("inbound", _UNIT_A)
        seed = await store.store(make_entry(content="seedX"))
        inbound = await store.store(make_entry(content="inbound"))
        await store.add_relation(inbound, seed, "link")

        out = await store.find_similar_by_ids([seed], threshold=0.5, limit=5, exclude_linked=True)
        result_ids = {sr.entry.id for sr in out[seed]}
        assert inbound not in result_ids

    async def test_threshold_honored(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("base", _UNIT_A)
        embedding_provider.register("aligned", _UNIT_A)
        embedding_provider.register("orthogonal", _UNIT_B)
        seed = await store.store(make_entry(content="base"))
        aligned = await store.store(make_entry(content="aligned"))
        orthogonal = await store.store(make_entry(content="orthogonal"))

        # _UNIT_A vs _UNIT_B cosine = 0 -> normalized score 0.5; threshold 0.9
        # keeps only the aligned (score 1.0) match.
        out = await store.find_similar_by_ids([seed], threshold=0.9, limit=5, exclude_linked=False)
        result_ids = {sr.entry.id for sr in out[seed]}
        assert aligned in result_ids
        assert orthogonal not in result_ids

    async def test_limit_honored(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("hub", _UNIT_A)
        seed = await store.store(make_entry(content="hub"))
        for i in range(6):
            text = f"match {i}"
            embedding_provider.register(text, _UNIT_A)
            await store.store(make_entry(content=text))

        out = await store.find_similar_by_ids([seed], threshold=0.5, limit=3, exclude_linked=False)
        assert len(out[seed]) == 3


# ===========================================================================
# Store: find_similar_by_id (single-seed convenience)
# ===========================================================================


class TestFindSimilarById:
    async def test_returns_matches_for_existing_embedding(
        self, store: DuckDBStore, embedding_provider: ControlledEmbeddingProvider
    ) -> None:
        embedding_provider.register("anchor", _UNIT_A)
        embedding_provider.register("near", _UNIT_A)
        anchor = await store.store(make_entry(content="anchor"))
        near = await store.store(make_entry(content="near"))

        results = await store.find_similar_by_id(anchor, threshold=0.5, limit=5)
        assert results is not None
        result_ids = {sr.entry.id for sr in results}
        # NOTE: find_similar_by_id does NOT self-exclude (the handler does).
        assert near in result_ids

    async def test_returns_none_when_entry_missing(self, store: DuckDBStore) -> None:
        results = await store.find_similar_by_id(
            "00000000-0000-0000-0000-000000000000", threshold=0.5, limit=5
        )
        assert results is None


# ===========================================================================
# MCP handler: batch path
# ===========================================================================


class TestHandlerBatch:
    async def test_payload_shape(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("seedA", _UNIT_A)
        embedding_provider.register("matchA", _UNIT_A)
        seed = await store.store(make_entry(content="seedA"))
        match = await store.store(make_entry(content="matchA"))

        response = await _handle_find_similar(
            store,
            {"source_entry_ids": [seed], "threshold": 0.5, "limit": 5},
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        assert data["seed_count"] == 1
        assert data["threshold"] == 0.5
        assert seed in data["results_by_seed"]
        seed_block = data["results_by_seed"][seed]
        assert set(seed_block.keys()) == {"results", "count", "excluded_count"}
        result_ids = {r["entry"]["id"] for r in seed_block["results"]}
        assert match in result_ids
        assert seed not in result_ids
        # Each result carries score + entry dict.
        for r in seed_block["results"]:
            assert "score" in r and "entry" in r

    async def test_batch_spends_no_embedding_budget(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        embedding_provider.register("seedB", _UNIT_A)
        seed = await store.store(make_entry(content="seedB"))

        embed_calls = 0
        original_embed = embedding_provider.embed

        def _counting_embed(text: str) -> list[float]:
            nonlocal embed_calls
            embed_calls += 1
            return original_embed(text)

        monkeypatch.setattr(embedding_provider, "embed", _counting_embed)

        record_calls = 0
        original_record = store.record_embedding_usage

        async def _counting_record(*args: object, **kwargs: object) -> int:
            nonlocal record_calls
            record_calls += 1
            return await original_record(*args, **kwargs)

        monkeypatch.setattr(store, "record_embedding_usage", _counting_record)

        response = await _handle_find_similar(
            store, {"source_entry_ids": [seed], "threshold": 0.5}, cfg=cfg
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        assert embed_calls == 0, "batch mode must not re-embed"
        assert record_calls == 0, "batch mode must not record embedding usage"

    async def test_missing_seed_maps_to_empty_results(
        self, store: DuckDBStore, cfg: DistilleryConfig
    ) -> None:
        missing = "00000000-0000-0000-0000-000000000000"
        response = await _handle_find_similar(store, {"source_entry_ids": [missing]}, cfg=cfg)
        data = parse_mcp_response(response)
        assert "error" not in data, data
        assert data["results_by_seed"][missing]["results"] == []
        assert data["results_by_seed"][missing]["count"] == 0

    async def test_exclude_linked_per_seed(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("S", _UNIT_A)
        embedding_provider.register("L", _UNIT_A)
        embedding_provider.register("U", _UNIT_A)
        seed = await store.store(make_entry(content="S"))
        linked = await store.store(make_entry(content="L"))
        unlinked = await store.store(make_entry(content="U"))
        await store.add_relation(seed, linked, "link")

        response = await _handle_find_similar(
            store,
            {"source_entry_ids": [seed], "exclude_linked": True, "threshold": 0.5},
            cfg=cfg,
        )
        data = parse_mcp_response(response)
        result_ids = {r["entry"]["id"] for r in data["results_by_seed"][seed]["results"]}
        assert linked not in result_ids
        assert unlinked in result_ids

    @pytest.mark.parametrize(
        "extra",
        [
            {"content": "x"},
            {"source_entry_id": "abc"},
            {"dedup_action": True},
            {"conflict_check": True},
            {"accept_action": "link"},
            {"llm_responses": [{"entry_id": "x", "is_conflict": True}]},
        ],
    )
    async def test_invalid_params_when_combined_with_embed_modes(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
        extra: dict[str, object],
    ) -> None:
        embedding_provider.register("seedC", _UNIT_A)
        seed = await store.store(make_entry(content="seedC"))

        response = await _handle_find_similar(store, {"source_entry_ids": [seed], **extra}, cfg=cfg)
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_invalid_params_empty_list(
        self, store: DuckDBStore, cfg: DistilleryConfig
    ) -> None:
        response = await _handle_find_similar(store, {"source_entry_ids": []}, cfg=cfg)
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_invalid_params_too_many(self, store: DuckDBStore, cfg: DistilleryConfig) -> None:
        ids = [f"id-{i}" for i in range(51)]
        response = await _handle_find_similar(store, {"source_entry_ids": ids}, cfg=cfg)
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_invalid_params_non_string_member(
        self, store: DuckDBStore, cfg: DistilleryConfig
    ) -> None:
        response = await _handle_find_similar(store, {"source_entry_ids": ["ok", ""]}, cfg=cfg)
        data = parse_mcp_response(response)
        assert data.get("error") is True
        assert data["code"] == "INVALID_PARAMS"


# ===========================================================================
# MCP handler: single source_entry_id path now reuses the stored vector
# ===========================================================================


class TestHandlerSingleStoredVector:
    async def test_single_source_entry_id_reuses_stored_vector_no_embed(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        embedding_provider.register("single seed", _UNIT_A)
        embedding_provider.register("single other", _UNIT_A)
        seed = await store.store(make_entry(content="single seed"))
        other = await store.store(make_entry(content="single other"))

        record_calls = 0
        original_record = store.record_embedding_usage

        async def _counting_record(*args: object, **kwargs: object) -> int:
            nonlocal record_calls
            record_calls += 1
            return await original_record(*args, **kwargs)

        monkeypatch.setattr(store, "record_embedding_usage", _counting_record)

        embed_calls = 0
        original_embed = embedding_provider.embed

        def _counting_embed(text: str) -> list[float]:
            nonlocal embed_calls
            embed_calls += 1
            return original_embed(text)

        monkeypatch.setattr(embedding_provider, "embed", _counting_embed)

        response = await _handle_find_similar(
            store,
            {"source_entry_id": seed, "threshold": 0.5},
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        assert record_calls == 0, "single source_entry_id path must not spend budget"
        assert embed_calls == 0, "single source_entry_id path must not re-embed"
        result_ids = {r["entry"]["id"] for r in data["results"]}
        assert seed not in result_ids, "source entry must be self-excluded"
        assert other in result_ids

    async def test_single_source_entry_id_still_excludes_linked(
        self,
        store: DuckDBStore,
        embedding_provider: ControlledEmbeddingProvider,
        cfg: DistilleryConfig,
    ) -> None:
        embedding_provider.register("anchor seed", _UNIT_A)
        embedding_provider.register("linked target", _UNIT_A)
        embedding_provider.register("free target", _UNIT_A)
        seed = await store.store(make_entry(content="anchor seed"))
        linked = await store.store(make_entry(content="linked target"))
        free = await store.store(make_entry(content="free target"))
        await store.add_relation(seed, linked, "link")

        response = await _handle_find_similar(
            store,
            {"source_entry_id": seed, "exclude_linked": True, "threshold": 0.5},
            cfg=cfg,
        )
        data = parse_mcp_response(response)

        assert "error" not in data, data
        result_ids = {r["entry"]["id"] for r in data["results"]}
        assert linked not in result_ids
        assert free in result_ids
        assert seed not in result_ids
        assert data["excluded_linked_count"] >= 1
