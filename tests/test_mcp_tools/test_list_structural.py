"""Tests for distillery_list ``structural`` filter (Phase 3, issue #141 partial).

The ``structural`` parameter accepts a list of named anomaly filters.  The
first supported value is ``"orphans"`` — entries with zero rows in
``entry_relations`` (no relation in either direction).  Unknown values must
fail loudly with ``INVALID_PARAMS`` rather than silently no-op.

Filters AND together with the existing project/tags/status/date filters.

Mirrors the fixture style of ``tests/test_list_archived_default.py`` and
``tests/test_list_output_modes.py``.
"""

from __future__ import annotations

import pytest

from distillery.mcp.tools.crud import _handle_list
from tests.conftest import make_entry, parse_mcp_response

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    """Create + persist an entry, returning the stored object with its id."""
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry


# ---------------------------------------------------------------------------
# Behaviour tests
# ---------------------------------------------------------------------------


async def test_orphans_returns_only_unrelated_entries(store) -> None:  # type: ignore[no-untyped-def]
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    # Link A <-> B; C remains orphaned.
    await store.add_relation(a.id, b.id, "link")

    result = await _handle_list(
        store=store,
        arguments={"limit": 50, "structural": ["orphans"], "output_mode": "ids"},
    )
    data = parse_mcp_response(result)
    assert data.get("error") is not True, data

    returned_ids = {e["id"] for e in data["entries"]}
    assert returned_ids == {c.id}
    assert a.id not in returned_ids
    assert b.id not in returned_ids
    assert data["count"] == 1
    assert data["total_count"] == 1


async def test_orphans_combines_with_existing_filters(store) -> None:  # type: ignore[no-untyped-def]
    # Two orphans across two different projects.
    orphan_x = await _store_entry(store, content="orphan in x", project="x")
    orphan_y = await _store_entry(store, content="orphan in y", project="y")
    # Plus a related pair in project x to confirm relations are still excluded.
    a_x = await _store_entry(store, content="related a in x", project="x")
    b_x = await _store_entry(store, content="related b in x", project="x")
    await store.add_relation(a_x.id, b_x.id, "link")

    result = await _handle_list(
        store=store,
        arguments={
            "limit": 50,
            "structural": ["orphans"],
            "project": "x",
            "output_mode": "ids",
        },
    )
    data = parse_mcp_response(result)
    assert data.get("error") is not True, data

    returned_ids = {e["id"] for e in data["entries"]}
    assert returned_ids == {orphan_x.id}
    assert orphan_y.id not in returned_ids  # filtered by project
    assert a_x.id not in returned_ids  # has a relation
    assert b_x.id not in returned_ids  # has a relation


async def test_unknown_structural_value_returns_invalid_params(store) -> None:  # type: ignore[no-untyped-def]
    result = await _handle_list(
        store=store,
        arguments={"limit": 10, "structural": ["bogus"]},
    )
    data = parse_mcp_response(result)
    assert data.get("error") is True
    assert data.get("code") == "INVALID_PARAMS"
    assert "bogus" in data.get("message", "")


async def test_structural_filter_appears_in_envelope_when_set(store) -> None:  # type: ignore[no-untyped-def]
    await _store_entry(store, content="solo entry")
    result = await _handle_list(
        store=store,
        arguments={"limit": 10, "structural": ["orphans"], "output_mode": "ids"},
    )
    data = parse_mcp_response(result)
    assert data.get("error") is not True, data
    assert data.get("structural_filter") == "orphans"


async def test_structural_filter_omitted_when_unset(store) -> None:  # type: ignore[no-untyped-def]
    await _store_entry(store, content="solo entry")
    result = await _handle_list(
        store=store,
        arguments={"limit": 10, "output_mode": "ids"},
    )
    data = parse_mcp_response(result)
    assert data.get("error") is not True, data
    assert "structural_filter" not in data


async def test_orphans_with_no_orphans_returns_empty(store) -> None:  # type: ignore[no-untyped-def]
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    await store.add_relation(a.id, b.id, "link")

    result = await _handle_list(
        store=store,
        arguments={"limit": 50, "structural": ["orphans"], "output_mode": "ids"},
    )
    data = parse_mcp_response(result)
    assert data.get("error") is not True, data
    assert data["count"] == 0
    assert data["entries"] == []
    assert data["total_count"] == 0


async def test_structural_must_be_list(store) -> None:  # type: ignore[no-untyped-def]
    result = await _handle_list(
        store=store,
        arguments={"limit": 10, "structural": "orphans"},
    )
    data = parse_mcp_response(result)
    assert data.get("error") is True
    assert data.get("code") == "INVALID_PARAMS"
    assert "structural" in data.get("message", "")
