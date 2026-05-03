"""Tests for _handle_search graph-expansion parameters (Phase 4 / #138).

Tests cover the new optional parameters added to _handle_search:
  - expand_graph: bool — when True, BFS-expand seeds via entry_relations
  - expand_hops: int — depth of expansion (1 or 2)

When ``expand_graph=False`` (default) the existing envelope is unchanged —
no ``provenance`` field on results, no ``graph_expansion`` on the envelope.

Mirrors fixture patterns from ``tests/test_find_similar_extended.py``:
ControlledEmbeddingProvider with 8-D unit vectors plus an in-memory store.
"""

from __future__ import annotations

import pytest

from distillery.config import DistilleryConfig, load_config
from distillery.mcp.tools.search import _handle_search
from distillery.models import EntryType
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
    """Return a DistilleryConfig with default settings."""
    return load_config()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_entry(
    store: DuckDBStore,
    content: str,
    *,
    tags: list[str] | None = None,
) -> str:
    """Store an entry (always ``EntryType.INBOX``) and return its id.

    Tests use the ``tags`` filter on ``store.search`` to constrain the seed
    set so we can verify graph expansion in isolation.
    """
    kwargs: dict = {"content": content, "entry_type": EntryType.INBOX}
    if tags is not None:
        kwargs["tags"] = tags
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


def _ids_with_provenance(results: list, provenance: str) -> set[str]:
    """Return the set of entry ids whose result dict has the given provenance."""
    return {r["entry"]["id"] for r in results if r.get("provenance") == provenance}


# ===========================================================================
# Baseline: expand_graph=False keeps the existing envelope unchanged
# ===========================================================================


async def test_expand_graph_false_unchanged(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """With expand_graph omitted/False, the response envelope must NOT contain
    ``graph_expansion`` and individual results must NOT carry ``provenance``."""
    embedding_provider.register("seed entry x", _UNIT_A)
    embedding_provider.register("x", _UNIT_A)
    await _store_entry(store, "seed entry x")

    response = await _handle_search(store, {"query": "x"}, cfg=cfg)
    data = parse_mcp_response(response)

    assert "graph_expansion" not in data
    assert "results" in data
    for r in data["results"]:
        assert "provenance" not in r
        assert "depth" not in r
        assert "parent_id" not in r


# ===========================================================================
# 1-hop expansion
# ===========================================================================


async def test_expand_graph_one_hop(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """A matches the search query; B is related to A but is filtered out
    of the seed set.  With expand_graph=True, expand_hops=1 the response
    must include B at provenance="graph", depth=1, parent_id=A.id.

    Note: ``store.search`` is unthresholded — every stored entry is a
    candidate.  We isolate B from the seed set by giving it a different
    ``entry_type`` and filtering the search to ``entry_type="inbox"``.
    Graph expansion uses ``get_related`` which has no such filter, so B is
    pulled in purely through the relation.
    """
    embedding_provider.register("seed match a", _UNIT_A)
    embedding_provider.register("query a", _UNIT_A)
    embedding_provider.register("unrelated text b", _UNIT_B)

    a_id = await _store_entry(store, "seed match a", tags=["seed"])
    b_id = await _store_entry(store, "unrelated text b", tags=["neighbour"])
    await store.add_relation(a_id, b_id, "link")

    response = await _handle_search(
        store,
        {
            "query": "query a",
            "tags": ["seed"],
            "expand_graph": True,
            "expand_hops": 1,
        },
        cfg=cfg,
    )
    data = parse_mcp_response(response)

    assert "graph_expansion" in data
    search_ids = _ids_with_provenance(data["results"], "search")
    graph_ids = _ids_with_provenance(data["results"], "graph")

    assert a_id in search_ids
    assert b_id in graph_ids

    b_result = next(r for r in data["results"] if r["entry"]["id"] == b_id)
    assert b_result["depth"] == 1
    assert b_result["parent_id"] == a_id


# ===========================================================================
# 2-hop expansion
# ===========================================================================


async def test_expand_graph_two_hops(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """A→B→C chain. Only A is in the seed set (entry_type filter); C is
    reachable purely through 2-hop graph expansion."""
    embedding_provider.register("chain seed a", _UNIT_A)
    embedding_provider.register("chain query a", _UNIT_A)
    embedding_provider.register("hop b", _UNIT_B)
    embedding_provider.register("hop c", [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    a_id = await _store_entry(store, "chain seed a", tags=["seed"])
    b_id = await _store_entry(store, "hop b", tags=["neighbour"])
    c_id = await _store_entry(store, "hop c", tags=["neighbour"])
    await store.add_relation(a_id, b_id, "link")
    await store.add_relation(b_id, c_id, "link")

    response = await _handle_search(
        store,
        {
            "query": "chain query a",
            "tags": ["seed"],
            "expand_graph": True,
            "expand_hops": 2,
        },
        cfg=cfg,
    )
    data = parse_mcp_response(response)

    graph_ids = _ids_with_provenance(data["results"], "graph")
    assert c_id in graph_ids

    c_result = next(r for r in data["results"] if r["entry"]["id"] == c_id)
    assert c_result["depth"] == 2
    assert c_result["parent_id"] == b_id


# ===========================================================================
# No duplicates between seeds and graph expansion
# ===========================================================================


async def test_expand_graph_does_not_duplicate_entries_already_in_seeds(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """Both A and B match the search; A is linked to B. B must appear once
    (provenance="search"), never duplicated as a graph entry."""
    embedding_provider.register("dup seed a", _UNIT_A)
    embedding_provider.register("dup seed b", _UNIT_A)
    embedding_provider.register("dup query", _UNIT_A)

    a_id = await _store_entry(store, "dup seed a")
    b_id = await _store_entry(store, "dup seed b")
    await store.add_relation(a_id, b_id, "link")

    response = await _handle_search(
        store,
        {"query": "dup query", "expand_graph": True, "expand_hops": 1, "limit": 10},
        cfg=cfg,
    )
    data = parse_mcp_response(response)

    # B should appear exactly once, with provenance="search".
    b_results = [r for r in data["results"] if r["entry"]["id"] == b_id]
    assert len(b_results) == 1
    assert b_results[0]["provenance"] == "search"
    # And B must not also appear as a graph entry.
    assert b_id not in _ids_with_provenance(data["results"], "graph")


# ===========================================================================
# Final result list respects ``limit``
# ===========================================================================


async def test_expand_graph_respects_limit(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """With many seeds + many neighbours and limit=5, the merged result list
    must be truncated to 5 entries (sorted by descending score).

    Seeds carry tag ``"seed"`` and the search filters on it; neighbours
    carry tag ``"neighbour"`` and only enter the result list via graph
    expansion.
    """
    embedding_provider.register("limit query", _UNIT_A)

    seed_ids: list[str] = []
    for i in range(4):
        text = f"limit seed {i}"
        embedding_provider.register(text, _UNIT_A)
        seed_ids.append(await _store_entry(store, text, tags=["seed"]))

    # 12 unique neighbours; not in the seed set because of the tags filter.
    neighbour_ids: list[str] = []
    for i in range(12):
        text = f"limit neighbour {i}"
        embedding_provider.register(text, _UNIT_B)
        neighbour_ids.append(await _store_entry(store, text, tags=["neighbour"]))

    # Wire each seed to 3 distinct neighbours.
    idx = 0
    for s_id in seed_ids:
        for _ in range(3):
            await store.add_relation(s_id, neighbour_ids[idx], "link")
            idx += 1

    response = await _handle_search(
        store,
        {
            "query": "limit query",
            "tags": ["seed"],
            "expand_graph": True,
            "expand_hops": 1,
            "limit": 5,
        },
        cfg=cfg,
    )
    data = parse_mcp_response(response)

    assert len(data["results"]) <= 5
    assert data["count"] == len(data["results"])
    # results must be sorted by descending score
    scores = [r["score"] for r in data["results"]]
    assert scores == sorted(scores, reverse=True)
    # We had 4 seeds + 12 candidate graph entries; limit must truncate.
    assert data["graph_expansion"]["seed_count"] == 4
    assert data["graph_expansion"]["expanded_count"] == 12


# ===========================================================================
# Score discount: depth-1 neighbour gets parent_score * 0.5
# ===========================================================================


async def test_expand_graph_score_discount(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """A neighbour at depth=1 receives a score equal to parent_score * 0.5."""
    embedding_provider.register("discount seed", _UNIT_A)
    embedding_provider.register("discount query", _UNIT_A)
    embedding_provider.register("discount neighbour", _UNIT_B)

    a_id = await _store_entry(store, "discount seed", tags=["seed"])
    b_id = await _store_entry(store, "discount neighbour", tags=["neighbour"])
    await store.add_relation(a_id, b_id, "link")

    response = await _handle_search(
        store,
        {
            "query": "discount query",
            "tags": ["seed"],
            "expand_graph": True,
            "expand_hops": 1,
        },
        cfg=cfg,
    )
    data = parse_mcp_response(response)

    a_result = next(r for r in data["results"] if r["entry"]["id"] == a_id)
    b_result = next(r for r in data["results"] if r["entry"]["id"] == b_id)

    assert a_result["provenance"] == "search"
    assert b_result["provenance"] == "graph"
    # The seed score is rounded to 6 decimals in the response; the discount
    # is applied to the un-rounded raw score in the handler, so allow a
    # small tolerance via pytest.approx.
    assert b_result["score"] == pytest.approx(a_result["score"] * 0.5, abs=1e-6)


# ===========================================================================
# Validation: invalid expand_hops
# ===========================================================================


@pytest.mark.parametrize(
    ("bad_value", "expected_msg"),
    [
        (0, "expand_hops must be 1 or 2"),
        (3, "expand_hops must be 1 or 2"),
        (True, "expand_hops must be an integer"),
    ],
)
async def test_invalid_expand_hops_returns_invalid_params(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
    bad_value: object,
    expected_msg: str,
) -> None:
    """expand_hops out of [1, 2] (or a bool) must surface INVALID_PARAMS."""
    embedding_provider.register("invalid hops", _UNIT_A)
    response = await _handle_search(
        store,
        {"query": "invalid hops", "expand_graph": True, "expand_hops": bad_value},
        cfg=cfg,
    )
    data = parse_mcp_response(response)
    assert data.get("error") is True
    assert data["code"] == "INVALID_PARAMS"
    assert expected_msg in data["message"]


# ===========================================================================
# Envelope shape: graph_expansion summary
# ===========================================================================


async def test_graph_expansion_field_in_envelope(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """When expand_graph=True the envelope must contain
    ``graph_expansion: {seed_count, expanded_count}``."""
    embedding_provider.register("envelope seed", _UNIT_A)
    embedding_provider.register("envelope query", _UNIT_A)
    embedding_provider.register("envelope neighbour", _UNIT_B)

    a_id = await _store_entry(store, "envelope seed", tags=["seed"])
    b_id = await _store_entry(store, "envelope neighbour", tags=["neighbour"])
    await store.add_relation(a_id, b_id, "link")

    response = await _handle_search(
        store,
        {
            "query": "envelope query",
            "tags": ["seed"],
            "expand_graph": True,
            "expand_hops": 1,
        },
        cfg=cfg,
    )
    data = parse_mcp_response(response)

    assert "graph_expansion" in data
    ge = data["graph_expansion"]
    assert isinstance(ge.get("seed_count"), int)
    assert isinstance(ge.get("expanded_count"), int)
    assert ge["seed_count"] >= 1
    assert ge["expanded_count"] >= 1
    assert b_id in _ids_with_provenance(data["results"], "graph")


# ===========================================================================
# No relations: expansion silently produces zero extras
# ===========================================================================


async def test_expand_graph_handles_seed_with_no_relations(
    store: DuckDBStore,
    embedding_provider: ControlledEmbeddingProvider,
    cfg: DistilleryConfig,
) -> None:
    """When the seed set has no entry_relations rows, expansion silently
    produces zero extras and the envelope reports ``expanded_count: 0``."""
    embedding_provider.register("orphan seed", _UNIT_A)
    embedding_provider.register("orphan query", _UNIT_A)
    await _store_entry(store, "orphan seed")

    response = await _handle_search(
        store,
        {"query": "orphan query", "expand_graph": True, "expand_hops": 2},
        cfg=cfg,
    )
    data = parse_mcp_response(response)

    assert data["graph_expansion"]["expanded_count"] == 0
    assert data["graph_expansion"]["seed_count"] >= 1
    assert _ids_with_provenance(data["results"], "graph") == set()
