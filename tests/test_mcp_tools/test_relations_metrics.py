"""Unit tests for the ``metrics`` action of ``distillery_relations``.

Covers graph metrics (bridges, communities) over the relations subgraph.
Most tests require NetworkX (gated via ``pytest.importorskip``); one test
exercises the missing-NetworkX path by monkeypatching the module attribute.
"""

from __future__ import annotations

import contextlib
import json

import pytest

from distillery.mcp.tools.relations import _handle_relations
from tests.conftest import make_entry

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


def _parse(result: list) -> dict:  # type: ignore[type-arg]
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


async def _seed_star_relations(store):  # type: ignore[no-untyped-def]
    """Star A->{B,C,D} so betweenness centrality on A is non-zero."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")
    d = await _store_entry(store, content="entry D")
    await store.add_relation(a, b, "link")
    await store.add_relation(a, c, "link")
    await store.add_relation(a, d, "link")
    return a, b, c, d


def _reset_graph_cache() -> None:
    """Drop cached graphs between tests so cache_hit assertions are deterministic."""
    from distillery.graph.cache import default_cache

    cache = default_cache()
    cache._store.clear()


# ---------------------------------------------------------------------------
# Tests requiring NetworkX
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_graph_cache():  # type: ignore[no-untyped-def]
    """Ensure a clean cache for every test."""
    with contextlib.suppress(Exception):
        _reset_graph_cache()
    yield
    with contextlib.suppress(Exception):
        _reset_graph_cache()


async def test_metrics_bridges_global(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    a, _, _, _ = await _seed_star_relations(store)

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "global"}
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["action"] == "metrics"
    assert data["metric"] == "bridges"
    assert data["scope"] == "global"
    assert data["node_count"] >= 4
    assert data["edge_count"] >= 3
    assert isinstance(data["results"], list)
    assert len(data["results"]) > 0
    assert data["count"] == len(data["results"])
    # Each row should carry a node id and a numeric score.
    for row in data["results"]:
        assert "id" in row
        assert "score" in row
    # Cache must report a miss on first call.
    assert data["cache_hit"] is False
    # Centre of the star should be present in the top-k.
    assert any(row["id"] == a for row in data["results"])


async def test_metrics_communities_global(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    # Two separate triangles linked by one bridge edge.
    nodes = {}
    for name in ("A", "B", "C", "X", "Y", "Z"):
        nodes[name] = await _store_entry(store, content=f"entry {name}")
    pairs = [
        ("A", "B"),
        ("B", "C"),
        ("C", "A"),
        ("X", "Y"),
        ("Y", "Z"),
        ("Z", "X"),
        ("C", "X"),  # bridge
    ]
    for src, dst in pairs:
        await store.add_relation(nodes[src], nodes[dst], "link")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "communities", "scope": "global"}
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["metric"] == "communities"
    assert isinstance(data["results"], list)
    assert len(data["results"]) >= 1
    # Each entry is a {"members": [...]} dict.
    for row in data["results"]:
        assert "members" in row
        assert isinstance(row["members"], list)


async def _seed_bowtie(store):  # type: ignore[no-untyped-def]
    """M brokers two otherwise-disconnected pairs {A,B} and {X,Y}. Returns id map."""
    ids = {name: await _store_entry(store, content=f"entry {name}") for name in "MABXY"}
    pairs = [("M", "A"), ("M", "B"), ("A", "B"), ("M", "X"), ("M", "Y"), ("X", "Y")]
    for src, dst in pairs:
        await store.add_relation(ids[src], ids[dst], "link")
    return ids


async def test_metrics_constraint_broker_first(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    ids = await _seed_bowtie(store)
    result = await _handle_relations(
        store, {"action": "metrics", "metric": "constraint", "scope": "global"}
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["metric"] == "constraint"
    assert isinstance(data["results"], list) and data["results"]
    for row in data["results"]:
        assert "id" in row and "score" in row
    # The broker M has the lowest Burt constraint -> ranked first.
    assert data["results"][0]["id"] == ids["M"]


async def test_metrics_link_prediction_with_source(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    # A and B share neighbours C, D but are not directly connected.
    ids = {name: await _store_entry(store, content=f"entry {name}") for name in "ABCD"}
    for src, dst in [("A", "C"), ("A", "D"), ("B", "C"), ("B", "D")]:
        await store.add_relation(ids[src], ids[dst], "link")

    result = await _handle_relations(
        store,
        {"action": "metrics", "metric": "link_prediction", "scope": "global", "entry_id": ids["A"]},
    )
    data = _parse(result)

    assert data.get("error") is not True
    assert data["metric"] == "link_prediction"
    assert isinstance(data["results"], list) and data["results"]
    top = data["results"][0]
    assert top["source"] == ids["A"]
    assert top["target"] == ids["B"]
    assert top["score"] > 0


async def test_metrics_invalid_metric_rejected(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "pagerank", "scope": "global"}
    )
    data = _parse(result)
    assert data.get("error") is True
    assert data["code"] == "INVALID_PARAMS"
    # Error message should enumerate the now-expanded metric set.
    assert "constraint" in data["message"] and "link_prediction" in data["message"]


async def test_metrics_invalid_metric_returns_invalid_params(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bogus", "scope": "global"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "metric" in data["message"]


async def test_metrics_invalid_scope_returns_invalid_params(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "galactic"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "scope" in data["message"]


async def test_metrics_ego_scope_requires_entry_id(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "ego"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "entry_id" in data["message"]


async def test_metrics_ego_scope_unknown_entry_id_returns_not_found(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    result = await _handle_relations(
        store,
        {
            "action": "metrics",
            "metric": "bridges",
            "scope": "ego",
            "entry_id": "no-such-uuid",
        },
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "NOT_FOUND"


async def test_metrics_response_envelope_shape(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    await _seed_star_relations(store)
    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "global"}
    )
    data = _parse(result)

    expected_keys = {
        "action",
        "metric",
        "scope",
        "node_count",
        "edge_count",
        "results",
        "count",
        "computed_at",
        "cache_hit",
    }
    assert expected_keys.issubset(set(data.keys()))


async def test_metrics_cache_hit_flips_on_second_call(store) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("networkx")

    await _seed_star_relations(store)

    first = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "bridges", "scope": "global"}
        )
    )
    second = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "bridges", "scope": "global"}
        )
    )

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True


# ---------------------------------------------------------------------------
# Graph-health: total_entries / graph_node_count / orphan_rate (issue #635).
# ---------------------------------------------------------------------------


async def test_metrics_includes_graph_health_fields(store) -> None:  # type: ignore[no-untyped-def]
    """Metrics response carries total_entries, graph_node_count, edge_count,
    orphan_rate (issue #635)."""
    pytest.importorskip("networkx")

    await _seed_star_relations(store)  # 4 entries, all linked

    data = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "bridges", "scope": "global"}
        )
    )
    assert data.get("error") is not True
    assert data["total_entries"] == 4
    assert data["graph_node_count"] == 4
    assert data["edge_count"] == 3
    # All 4 entries are linked -> no orphans.
    assert data["orphan_rate"] == 0.0


async def test_metrics_orphan_rate_high_when_few_linked(store) -> None:  # type: ignore[no-untyped-def]
    """8 entries, only 2 linked -> orphan_rate 0.75 (issue #635 acceptance)."""
    pytest.importorskip("networkx")

    ids = [await _store_entry(store, content=f"entry {i}") for i in range(8)]
    # Link only the first two; the remaining six are orphans.
    await store.add_relation(ids[0], ids[1], "link")

    data = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "bridges", "scope": "global"}
        )
    )
    assert data.get("error") is not True
    assert data["total_entries"] == 8
    assert data["graph_node_count"] == 2
    assert data["orphan_rate"] == 0.75


async def test_metrics_orphan_rate_never_negative_with_archived_linked(store) -> None:  # type: ignore[no-untyped-def]
    """An archived-but-still-linked entry is a graph node but not counted in
    total_entries; orphan_rate must clamp to >= 0.0 rather than go negative
    (issue #635 review: reproduced orphan_rate=-1.0)."""
    pytest.importorskip("networkx")

    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    await store.add_relation(a, b, "link")
    # Archive one endpoint: it stays in the graph (the relation still exists)
    # but drops out of total_entries -> graph_node_count (2) > total_entries (1).
    await store.update(a, {"status": "archived"})

    data = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "bridges", "scope": "global"}
        )
    )
    assert data.get("error") is not True
    assert data["total_entries"] == 1
    assert data["graph_node_count"] == 2
    assert data["orphan_rate"] >= 0.0
    assert data["orphan_rate"] == 0.0


async def test_metrics_orphan_rate_filtered_uses_scoped_denominator(store) -> None:  # type: ignore[no-untyped-def]
    """With a project filter, total_entries must be scoped to that project too,
    so a fully-linked project reads orphan_rate 0.0 — not inflated by unrelated
    entries (issue #635 review: reproduced 0.833 for a zero-orphan project)."""
    pytest.importorskip("networkx")

    p1 = await _store_entry(store, content="P1", project="proj-x")
    p2 = await _store_entry(store, content="P2", project="proj-x")
    await store.add_relation(p1, p2, "link")
    # Ten unrelated entries with no project — must NOT inflate proj-x's rate.
    for i in range(10):
        await _store_entry(store, content=f"other {i}")

    data = _parse(
        await _handle_relations(
            store,
            {
                "action": "metrics",
                "metric": "bridges",
                "scope": "global",
                "project": "proj-x",
            },
        )
    )
    assert data.get("error") is not True
    assert data["total_entries"] == 2
    assert data["graph_node_count"] == 2
    assert data["orphan_rate"] == 0.0


async def test_metrics_ego_scope_ignores_entry_filters_for_denominator(store) -> None:  # type: ignore[no-untyped-def]
    """Ego scope builds the subgraph around the root and ignores the entry-side
    filters (project/tags/date_*); total_entries / orphan_rate must use the same
    unfiltered, all-non-archived population so the rate stays consistent with the
    graph (issue #635 review: filtered denominator over an unfiltered ego graph).
    """
    pytest.importorskip("networkx")

    # Ego root + neighbour share a project; a third unrelated entry has none.
    root = await _store_entry(store, content="root", project="proj-x")
    neighbour = await _store_entry(store, content="neighbour", project="proj-x")
    await store.add_relation(root, neighbour, "link")
    await _store_entry(store, content="unrelated", project="proj-y")

    data = _parse(
        await _handle_relations(
            store,
            {
                "action": "metrics",
                "metric": "bridges",
                "scope": "ego",
                "entry_id": root,
                # A filter that, if (incorrectly) applied to the denominator,
                # would shrink total_entries to the 2 proj-x entries.
                "project": "proj-x",
            },
        )
    )
    assert data.get("error") is not True
    assert data["scope"] == "ego"
    # Ego graph = root + its 1-hop neighbour (2 nodes), filters ignored.
    assert data["graph_node_count"] == 2
    # Denominator ignores the project filter too: all 3 non-archived entries.
    assert data["total_entries"] == 3
    # orphan_rate = (3 - 2) / 3, consistent with the unfiltered ego population.
    assert data["orphan_rate"] == round(1 / 3, 6)


async def test_metrics_orphans_returns_unlinked_ids(store) -> None:  # type: ignore[no-untyped-def]
    """metric='orphans' returns entry IDs present in the store but absent
    from the relations graph (issue #635)."""
    pytest.importorskip("networkx")

    ids = [await _store_entry(store, content=f"entry {i}") for i in range(5)]
    # Link the first two; ids[2], ids[3], ids[4] are orphans.
    await store.add_relation(ids[0], ids[1], "link")

    data = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "orphans", "scope": "global"}
        )
    )
    assert data.get("error") is not True
    assert data["metric"] == "orphans"
    returned = {row["id"] for row in data["results"]}
    assert returned == {ids[2], ids[3], ids[4]}
    # Graph-health fields are present alongside the orphan sample.
    assert data["total_entries"] == 5
    assert data["graph_node_count"] == 2
    assert data["orphan_rate"] == 0.6


async def test_metrics_health_returns_consolidated_snapshot(store) -> None:  # type: ignore[no-untyped-def]
    """metric='health' adds mean_degree, connected_component_count and
    largest_component_fraction to the standard totals block (issue #653)."""
    pytest.importorskip("networkx")

    await _seed_star_relations(store)  # star A->{B,C,D}: 4 nodes, 3 edges, 1 component

    data = _parse(
        await _handle_relations(store, {"action": "metrics", "metric": "health", "scope": "global"})
    )
    assert data.get("error") is not True
    assert data["metric"] == "health"
    # Standard totals block.
    assert data["total_entries"] == 4
    assert data["graph_node_count"] == 4
    assert data["edge_count"] == 3
    assert data["orphan_rate"] == 0.0
    # Health-only scalar fields.
    assert data["mean_degree"] == 1.5  # 2 * 3 / 4
    assert data["connected_component_count"] == 1
    assert data["largest_component_fraction"] == 1.0
    # Health carries no per-node results.
    assert data["results"] == []
    assert data["count"] == 0


async def test_metrics_health_empty_graph(store) -> None:  # type: ignore[no-untyped-def]
    """With entries but no relations, health reports an empty graph: zero degree,
    zero components, and an orphan_rate of 1.0."""
    pytest.importorskip("networkx")

    for i in range(3):
        await _store_entry(store, content=f"orphan {i}")

    data = _parse(
        await _handle_relations(store, {"action": "metrics", "metric": "health", "scope": "global"})
    )
    assert data.get("error") is not True
    assert data["graph_node_count"] == 0
    assert data["edge_count"] == 0
    assert data["orphan_rate"] == 1.0
    assert data["mean_degree"] == 0.0
    assert data["connected_component_count"] == 0
    assert data["largest_component_fraction"] == 0.0


async def test_metrics_health_components_fragmented(store) -> None:  # type: ignore[no-untyped-def]
    """Two disjoint edges -> two components, largest holding half the nodes."""
    pytest.importorskip("networkx")

    ids = {name: await _store_entry(store, content=f"entry {name}") for name in "ABXY"}
    await store.add_relation(ids["A"], ids["B"], "link")
    await store.add_relation(ids["X"], ids["Y"], "link")

    data = _parse(
        await _handle_relations(store, {"action": "metrics", "metric": "health", "scope": "global"})
    )
    assert data.get("error") is not True
    assert data["connected_component_count"] == 2
    assert data["largest_component_fraction"] == 0.5
    assert data["mean_degree"] == 1.0  # 2 * 2 / 4


async def test_metrics_health_omits_scalars_for_other_metrics(store) -> None:  # type: ignore[no-untyped-def]
    """The health-only scalar fields must NOT appear on other metrics, keeping
    their response envelope unchanged."""
    pytest.importorskip("networkx")

    await _seed_star_relations(store)
    data = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "bridges", "scope": "global"}
        )
    )
    assert "mean_degree" not in data
    assert "connected_component_count" not in data
    assert "largest_component_fraction" not in data


async def test_metrics_orphans_sample_is_capped(store, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """metric='orphans' returns at most the sample cap of unlinked IDs."""
    pytest.importorskip("networkx")

    monkeypatch.setattr(
        "distillery.mcp.tools.relations._ORPHANS_SAMPLE_CAP",
        3,
    )
    for i in range(10):
        await _store_entry(store, content=f"orphan {i}")

    data = _parse(
        await _handle_relations(
            store, {"action": "metrics", "metric": "orphans", "scope": "global"}
        )
    )
    assert data.get("error") is not True
    assert len(data["results"]) == 3


# ---------------------------------------------------------------------------
# NetworkX missing — runs even without the [graph] extra installed.
# ---------------------------------------------------------------------------


async def test_metrics_returns_internal_when_nx_missing(  # type: ignore[no-untyped-def]
    store, monkeypatch
) -> None:
    """Even when networkx is installed, simulate the missing-extra path.

    We monkeypatch ``distillery.graph.nx`` to None so the gate in
    ``_handle_metrics`` (via ``is_available()``) reports the extra missing.
    """
    import distillery.graph as graph_pkg

    monkeypatch.setattr(graph_pkg, "nx", None)

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "global"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INTERNAL"
    assert "NetworkX not installed" in data["message"]


# ---------------------------------------------------------------------------
# Pagination + error-handling regressions (CodeRabbit, PR #426).
# ---------------------------------------------------------------------------


async def test_metrics_paginates_large_corpus(store, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Global-scope metrics must paginate ``list_entries`` so large corpora are
    not silently truncated by a single 10k-row page (CodeRabbit, PR #426).
    """
    pytest.importorskip("networkx")

    # Force a tiny page size so pagination is exercised even with a few entries.
    monkeypatch.setattr(
        "distillery.mcp.tools.relations._GRAPH_METRICS_PAGE_SIZE",
        2,
    )

    # Seed five entries on a single project, fully connected in a star pattern.
    project = "paginate-me"
    ids: list[str] = []
    for i in range(5):
        ids.append(await _store_entry(store, content=f"node {i}", project=project))
    for j in range(1, 5):
        await store.add_relation(ids[0], ids[j], "link")

    result = await _handle_relations(
        store,
        {
            "action": "metrics",
            "metric": "bridges",
            "scope": "global",
            "project": project,
        },
    )
    data = _parse(result)
    assert data.get("error") is not True
    # All 5 nodes must appear in the graph despite the page size of 2 — that
    # only happens if pagination loops past the first page.
    assert data["node_count"] == 5
    assert data["edge_count"] == 4


async def test_metrics_runtime_error_returns_generic_message(  # type: ignore[no-untyped-def]
    store, monkeypatch
) -> None:
    """A RuntimeError raised during graph build must NOT leak its message text
    to the client; the handler logs it server-side and returns a generic
    INTERNAL response (CodeRabbit, PR #426).
    """
    pytest.importorskip("networkx")

    secret = "super secret internal detail xyzzy"

    def _boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError(secret)

    # Patch the symbol referenced inside ``_handle_metrics`` (it does a local
    # import, so we patch it on the source module).
    monkeypatch.setattr("distillery.graph.builders.build_relations_graph", _boom)

    result = await _handle_relations(
        store, {"action": "metrics", "metric": "bridges", "scope": "global"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INTERNAL"
    assert secret not in data["message"], "raw exception text must not leak"
