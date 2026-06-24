"""Unit tests for entry relations store methods and distillery_relations MCP tool.

Covers store methods:
  - add_relation creates a row and returns a UUID
  - add_relation raises ValueError when from_id does not exist
  - add_relation raises ValueError when to_id does not exist
  - get_related with direction='outgoing' returns only outgoing relations
  - get_related with direction='incoming' returns only incoming relations
  - get_related with direction='both' returns all relations
  - get_related with relation_type filter restricts results
  - get_related returns empty list when no relations exist
  - remove_relation deletes the row and returns True
  - remove_relation returns False for unknown relation_id

Covers MCP tool (_handle_relations):
  - add action: success, missing fields, not-found entries, unexpected error
  - get action: success, missing entry_id, invalid direction, optional filters
  - remove action: success (removed=True), not found (removed=False), missing relation_id
  - invalid action returns INVALID_ACTION error
  - null action returns INVALID_ACTION error
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from distillery.mcp.tools.relations import _handle_relations
from tests.conftest import make_entry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_entry(store, **kwargs):  # type: ignore[no-untyped-def]
    """Store a minimal entry, return its id."""
    entry = make_entry(**kwargs)
    await store.store(entry)
    return entry.id


# ---------------------------------------------------------------------------
# add_relation
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_add_relation_returns_uuid(store) -> None:  # type: ignore[no-untyped-def]
    """add_relation returns a non-empty UUID string when both entries exist."""
    from_id = await _store_entry(store, content="entry A")
    to_id = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation(from_id, to_id, "link")

    assert isinstance(relation_id, str)
    assert len(relation_id) > 0


@pytest.mark.unit
async def test_add_relation_invalid_from_id(store) -> None:  # type: ignore[no-untyped-def]
    """add_relation raises ValueError when from_id does not exist."""
    to_id = await _store_entry(store, content="entry B")

    with pytest.raises(ValueError, match="from_id"):
        await store.add_relation("nonexistent-from-id", to_id, "link")


@pytest.mark.unit
async def test_add_relation_invalid_to_id(store) -> None:  # type: ignore[no-untyped-def]
    """add_relation raises ValueError when to_id does not exist."""
    from_id = await _store_entry(store, content="entry A")

    with pytest.raises(ValueError, match="to_id"):
        await store.add_relation(from_id, "nonexistent-to-id", "link")


@pytest.mark.unit
async def test_add_relation_both_invalid(store) -> None:  # type: ignore[no-untyped-def]
    """add_relation raises ValueError when both IDs are missing."""
    with pytest.raises(ValueError):
        await store.add_relation("bad-from", "bad-to", "link")


@pytest.mark.unit
async def test_add_relation_stores_relation_type(store) -> None:  # type: ignore[no-untyped-def]
    """The relation_type passed to add_relation is persisted correctly."""
    from_id = await _store_entry(store, content="entry A")
    to_id = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation(from_id, to_id, "blocks")

    related = await store.get_related(from_id, direction="outgoing")
    assert len(related) == 1
    assert related[0]["id"] == relation_id
    assert related[0]["relation_type"] == "blocks"


# ---------------------------------------------------------------------------
# add_relation read-path alignment (issue #515 — _sync_add_relation must accept
# any entry the read path can return, including archived rows).
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_add_relation_accepts_archived_entries(store) -> None:  # type: ignore[no-untyped-def]
    """Archived entries are still valid endpoints for add_relation.

    Prevents regression of the asymmetry described in issue #515:
    ``relations.add`` must align with the read path's permissive
    existence check (``include_archived=True``) so historical edges
    can still be inserted against soft-deleted rows.
    """
    from_id = await _store_entry(store, content="entry A (will be archived)")
    to_id = await _store_entry(store, content="entry B (will be archived)")

    # Archive both endpoints — store.delete is a soft-delete (status="archived").
    assert await store.delete(from_id) is True
    assert await store.delete(to_id) is True

    # Sanity: default include_archived=False hides them from the get path,
    # but include_archived=True still returns them.
    assert await store.get(from_id) is None
    assert await store.get(to_id) is None
    assert await store.get(from_id, include_archived=True) is not None
    assert await store.get(to_id, include_archived=True) is not None

    # add_relation must succeed: archived endpoints are still in entries.
    relation_id = await store.add_relation(from_id, to_id, "link")
    assert isinstance(relation_id, str)
    assert len(relation_id) > 0


@pytest.mark.unit
async def test_add_relation_uses_shared_existence_helper(store) -> None:  # type: ignore[no-untyped-def]
    """_sync_add_relation routes its existence check through _sync_entry_exists.

    Locks in the structural alignment that closes issue #515. If a future
    refactor reintroduces a divergent SELECT in _sync_add_relation, this
    test (which monkeypatches the helper) will fail.
    """
    from_id = await _store_entry(store, content="entry A")
    to_id = await _store_entry(store, content="entry B")

    # Force the helper to reject every id — _sync_add_relation must observe
    # that and raise. If _sync_add_relation bypasses the helper with its
    # own inline SELECT, the call would succeed and this test would fail.
    def _always_missing(_entry_id: str) -> bool:
        return False

    store._sync_entry_exists = _always_missing  # type: ignore[method-assign]
    try:
        with pytest.raises(ValueError, match="Entry not found"):
            await store.add_relation(from_id, to_id, "link")
    finally:
        # Restore the bound method so subsequent fixture teardown is clean.
        del store._sync_entry_exists


@pytest.mark.unit
async def test_add_relation_error_carries_diagnostic(store) -> None:  # type: ignore[no-untyped-def]
    """The NOT_FOUND ValueError surfaces a diagnostic dict for operators.

    Issue #515's hardest property to debug in production was the absence
    of any signal about *why* the existence check disagreed with the
    read path. The error message now embeds a ``diagnostic`` dict
    enumerating visibility from the read path, base-table count, and
    relation-endpoint presence so the next investigation has data on
    the first try.
    """
    to_id = await _store_entry(store, content="real entry")
    missing_id = "00000000-0000-0000-0000-000000000000"

    with pytest.raises(ValueError) as excinfo:
        await store.add_relation(missing_id, to_id, "link")

    msg = str(excinfo.value)
    assert "from_id" in msg
    assert "diagnostic=" in msg
    # The four core diagnostic probes are always recorded, even when
    # their underlying tables are empty.
    assert "entries_count" in msg
    assert "visible_via_get" in msg
    assert "relation_endpoint" in msg


@pytest.mark.unit
async def test_sync_diagnose_missing_entry_reports_orphaned_edge(store) -> None:  # type: ignore[no-untyped-def]
    """Diagnostic helper flags the orphaned-edge case from issue #515.

    Simulates the prod state hypothesised in the issue: a row that was
    deleted from ``entries`` but still appears as an endpoint in
    ``entry_relations``. The diagnostic must report
    ``entries_count == 0`` while ``relation_endpoint`` is True so an
    operator can tell at a glance that the row was orphaned by a
    maintenance pass.
    """
    a = await _store_entry(store, content="endpoint A")
    b = await _store_entry(store, content="endpoint B")
    await store.add_relation(a, b, "link")

    # Hard-delete ``a`` from entries directly (bypass the soft-delete path)
    # to mirror the prod symptom: edges intact, base row gone.
    conn = store.connection
    conn.execute("DELETE FROM entries WHERE id = ?", [a])

    diag = await store._run_sync(store._sync_diagnose_missing_entry, a)
    assert diag["entries_count"] == 0
    assert diag["visible_via_get"] is False
    assert diag["relation_endpoint"] is True


# ---------------------------------------------------------------------------
# get_related
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_related_outgoing(store) -> None:  # type: ignore[no-untyped-def]
    """get_related(direction='outgoing') returns only relations where entry is from_id."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "link")
    await store.add_relation(c, a, "link")

    results = await store.get_related(a, direction="outgoing")
    assert len(results) == 1
    assert results[0]["from_id"] == a
    assert results[0]["to_id"] == b


@pytest.mark.unit
async def test_get_related_incoming(store) -> None:  # type: ignore[no-untyped-def]
    """get_related(direction='incoming') returns only relations where entry is to_id."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "link")
    await store.add_relation(c, b, "link")
    await store.add_relation(b, c, "link")

    results = await store.get_related(b, direction="incoming")
    from_ids = {r["from_id"] for r in results}
    assert from_ids == {a, c}
    assert all(r["to_id"] == b for r in results)


@pytest.mark.unit
async def test_get_related_both(store) -> None:  # type: ignore[no-untyped-def]
    """get_related(direction='both') returns outgoing and incoming relations."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "link")
    await store.add_relation(c, a, "link")

    results = await store.get_related(a, direction="both")
    assert len(results) == 2


@pytest.mark.unit
async def test_get_related_default_direction_is_both(store) -> None:  # type: ignore[no-untyped-def]
    """get_related with no direction argument defaults to 'both'."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "link")
    await store.add_relation(c, a, "link")

    results = await store.get_related(a)
    assert len(results) == 2


@pytest.mark.unit
async def test_get_related_relation_type_filter(store) -> None:  # type: ignore[no-untyped-def]
    """relation_type filter restricts get_related results to matching rows only."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "blocks")
    await store.add_relation(a, c, "link")

    blocks = await store.get_related(a, direction="outgoing", relation_type="blocks")
    links = await store.get_related(a, direction="outgoing", relation_type="link")

    assert len(blocks) == 1
    assert blocks[0]["to_id"] == b
    assert len(links) == 1
    assert links[0]["to_id"] == c


@pytest.mark.unit
async def test_get_related_empty_when_no_relations(store) -> None:  # type: ignore[no-untyped-def]
    """get_related returns an empty list when no relations exist for an entry."""
    a = await _store_entry(store, content="lonely entry")

    results = await store.get_related(a)
    assert results == []


@pytest.mark.unit
async def test_get_related_row_structure(store) -> None:  # type: ignore[no-untyped-def]
    """Each dict returned by get_related has the required keys."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation(a, b, "link")

    results = await store.get_related(a)
    assert len(results) == 1
    row = results[0]
    assert set(row.keys()) == {
        "id",
        "from_id",
        "to_id",
        "relation_type",
        "created_at",
        "weight",
        "valid_at",
        "invalid_at",
        "metadata",
    }
    assert row["id"] == relation_id
    assert row["from_id"] == a
    assert row["to_id"] == b
    assert row["relation_type"] == "link"
    assert isinstance(row["created_at"], str)
    # New edge attributes default to None when unspecified.
    assert row["weight"] is None
    assert row["valid_at"] is None
    assert row["invalid_at"] is None
    assert row["metadata"] is None


@pytest.mark.unit
async def test_add_relation_edge_attributes_round_trip(store) -> None:  # type: ignore[no-untyped-def]
    """weight, valid_at, invalid_at, and metadata persist and read back."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    await store.add_relation(
        a,
        b,
        "related",
        weight=0.75,
        valid_at="2026-01-01T00:00:00",
        invalid_at="2026-06-01T12:30:00",
        metadata={"source": "spike", "n": 3},
    )

    (row,) = await store.get_related(a)
    assert row["weight"] == 0.75
    assert row["valid_at"] == "2026-01-01T00:00:00Z"
    assert row["invalid_at"] == "2026-06-01T12:30:00Z"
    assert row["metadata"] == {"source": "spike", "n": 3}

    # list_relations returns the same shape.
    (listed,) = await store.list_relations()
    assert listed["weight"] == 0.75
    assert listed["metadata"] == {"source": "spike", "n": 3}


@pytest.mark.unit
async def test_add_relation_rejects_inverted_validity_window(store) -> None:  # type: ignore[no-untyped-def]
    """invalid_at earlier than valid_at is rejected."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    with pytest.raises(ValueError, match="invalid_at must be greater than or equal to valid_at"):
        await store.add_relation(
            a,
            b,
            "related",
            valid_at="2026-06-01T00:00:00",
            invalid_at="2026-01-01T00:00:00",
        )


@pytest.mark.unit
async def test_add_relation_reassert_upserts_attributes(store) -> None:  # type: ignore[no-untyped-def]
    """Re-asserting an existing edge upserts supplied attrs, stays idempotent on the triple."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    first = await store.add_relation(a, b, "related", weight=0.1)
    second = await store.add_relation(a, b, "related", weight=0.9, invalid_at="2026-06-01T00:00:00")

    assert first == second  # same row, no duplicate
    (row,) = await store.get_related(a)
    assert row["weight"] == 0.9  # upserted
    assert row["invalid_at"] == "2026-06-01T00:00:00Z"


@pytest.mark.unit
async def test_relations_tool_add_with_edge_attributes(store) -> None:  # type: ignore[no-untyped-def]
    """The MCP add action accepts and echoes weight/valid_at/invalid_at/metadata."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    result = await _handle_relations(
        store,
        {
            "action": "add",
            "from_id": a,
            "to_id": b,
            "relation_type": "link",
            "weight": 2.5,
            "valid_at": "2026-03-01T00:00:00",
            "metadata": {"k": "v"},
        },
    )
    payload = json.loads(result[0].text)
    assert payload["weight"] == 2.5
    assert payload["valid_at"] == "2026-03-01T00:00:00"
    assert payload["metadata"] == {"k": "v"}

    (row,) = await store.get_related(a)
    assert row["weight"] == 2.5
    assert row["valid_at"] == "2026-03-01T00:00:00Z"
    assert row["metadata"] == {"k": "v"}


@pytest.mark.unit
async def test_relations_tool_add_rejects_bad_attributes(store) -> None:  # type: ignore[no-untyped-def]
    """Non-numeric weight and unparseable timestamps are rejected with INVALID_PARAMS."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    bad_weight = await _handle_relations(
        store,
        {"action": "add", "from_id": a, "to_id": b, "relation_type": "link", "weight": "heavy"},
    )
    assert json.loads(bad_weight[0].text)["code"] == "INVALID_PARAMS"

    bad_ts = await _handle_relations(
        store,
        {
            "action": "add",
            "from_id": a,
            "to_id": b,
            "relation_type": "link",
            "valid_at": "not-a-date",
        },
    )
    assert json.loads(bad_ts[0].text)["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# remove_relation
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_remove_relation_returns_true(store) -> None:  # type: ignore[no-untyped-def]
    """remove_relation returns True and deletes the row when relation exists."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation(a, b, "link")
    result = await store.remove_relation(relation_id)

    assert result is True
    remaining = await store.get_related(a)
    assert remaining == []


@pytest.mark.unit
async def test_remove_relation_returns_false_for_unknown(store) -> None:  # type: ignore[no-untyped-def]
    """remove_relation returns False when the relation_id does not exist."""
    result = await store.remove_relation("nonexistent-relation-id")
    assert result is False


@pytest.mark.unit
async def test_remove_relation_idempotent_second_call(store) -> None:  # type: ignore[no-untyped-def]
    """Calling remove_relation twice returns False on the second call."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation(a, b, "link")
    first = await store.remove_relation(relation_id)
    second = await store.remove_relation(relation_id)

    assert first is True
    assert second is False


@pytest.mark.unit
async def test_multiple_relations_between_same_entries(store) -> None:  # type: ignore[no-untyped-def]
    """Multiple relations of different types can exist between the same pair of entries."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    rel1 = await store.add_relation(a, b, "link")
    rel2 = await store.add_relation(a, b, "blocks")

    assert rel1 != rel2
    results = await store.get_related(a, direction="outgoing")
    assert len(results) == 2
    types = {r["relation_type"] for r in results}
    assert types == {"link", "blocks"}


# ===========================================================================
# MCP tool tests — _handle_relations
# ===========================================================================


def _parse(result: list) -> dict:  # type: ignore[type-arg]
    """Parse MCP TextContent list into a plain dict."""
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Validation — invalid / missing action
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_handle_relations_null_action() -> None:
    """Passing action=None returns INVALID_ACTION error."""
    result = await _handle_relations(AsyncMock(), {"action": None})
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"


@pytest.mark.unit
async def test_handle_relations_unknown_action() -> None:
    """Passing an unrecognised action returns INVALID_ACTION error."""
    result = await _handle_relations(AsyncMock(), {"action": "delete"})
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "delete" in data["message"]


# ---------------------------------------------------------------------------
# action == "add"
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_handle_relations_add_success(store) -> None:  # type: ignore[no-untyped-def]
    """add action creates a relation and returns its ID."""
    from_id = await _store_entry(store, content="entry A")
    to_id = await _store_entry(store, content="entry B")

    result = await _handle_relations(
        store,
        {"action": "add", "from_id": from_id, "to_id": to_id, "relation_type": "link"},
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert isinstance(data["relation_id"], str)
    assert data["from_id"] == from_id
    assert data["to_id"] == to_id
    assert data["relation_type"] == "link"


@pytest.mark.unit
async def test_handle_relations_add_missing_from_id() -> None:
    """add action without from_id returns MISSING_FIELD error."""
    result = await _handle_relations(
        AsyncMock(),
        {"action": "add", "to_id": "some-id", "relation_type": "link"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "from_id" in data["message"]


@pytest.mark.unit
async def test_handle_relations_add_missing_to_id() -> None:
    """add action without to_id returns MISSING_FIELD error."""
    result = await _handle_relations(
        AsyncMock(),
        {"action": "add", "from_id": "some-id", "relation_type": "link"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "to_id" in data["message"]


@pytest.mark.unit
async def test_handle_relations_add_missing_relation_type() -> None:
    """add action without relation_type returns MISSING_FIELD error."""
    result = await _handle_relations(
        AsyncMock(),
        {"action": "add", "from_id": "a", "to_id": "b"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "relation_type" in data["message"]


@pytest.mark.unit
async def test_handle_relations_add_entry_not_found(store) -> None:  # type: ignore[no-untyped-def]
    """add action with a non-existent from_id returns NOT_FOUND error."""
    to_id = await _store_entry(store, content="entry B")

    result = await _handle_relations(
        store,
        {"action": "add", "from_id": "nonexistent-uuid", "to_id": to_id, "relation_type": "link"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "NOT_FOUND"


@pytest.mark.unit
async def test_handle_relations_add_unexpected_error() -> None:
    """add action propagates unexpected store errors as RELATIONS_ERROR."""
    fake_store = AsyncMock()
    fake_store.add_relation.side_effect = RuntimeError("db exploded")

    result = await _handle_relations(
        fake_store,
        {"action": "add", "from_id": "a", "to_id": "b", "relation_type": "link"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INTERNAL"


# ---------------------------------------------------------------------------
# action == "get"
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_handle_relations_get_success(store) -> None:  # type: ignore[no-untyped-def]
    """get action returns relations for the given entry."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    await store.add_relation(a, b, "link")

    result = await _handle_relations(
        store,
        {"action": "get", "entry_id": a},
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["entry_id"] == a
    assert data["direction"] == "both"
    assert data["count"] == 1
    assert len(data["relations"]) == 1


@pytest.mark.unit
async def test_handle_relations_get_missing_entry_id() -> None:
    """get action without entry_id returns MISSING_FIELD error."""
    result = await _handle_relations(AsyncMock(), {"action": "get"})
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "entry_id" in data["message"]


@pytest.mark.unit
async def test_handle_relations_get_invalid_direction() -> None:
    """get action with an unrecognised direction returns INVALID_FIELD error."""
    result = await _handle_relations(
        AsyncMock(),
        {"action": "get", "entry_id": "some-id", "direction": "sideways"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "direction" in data["message"]


@pytest.mark.unit
async def test_handle_relations_get_with_direction_filter(store) -> None:  # type: ignore[no-untyped-def]
    """get action with direction='outgoing' returns only outgoing relations."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "link")  # outgoing from a
    await store.add_relation(c, a, "link")  # incoming to a

    result = await _handle_relations(
        store,
        {"action": "get", "entry_id": a, "direction": "outgoing"},
    )
    data = _parse(result)
    assert data["count"] == 1
    assert data["relations"][0]["from_id"] == a


@pytest.mark.unit
async def test_handle_relations_get_with_relation_type_filter(store) -> None:  # type: ignore[no-untyped-def]
    """get action with relation_type filter restricts results."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "blocks")
    await store.add_relation(a, c, "link")

    result = await _handle_relations(
        store,
        {"action": "get", "entry_id": a, "relation_type": "blocks"},
    )
    data = _parse(result)
    assert data["count"] == 1
    assert data["relations"][0]["relation_type"] == "blocks"


@pytest.mark.unit
async def test_handle_relations_get_empty(store) -> None:  # type: ignore[no-untyped-def]
    """get action returns empty list when no relations exist."""
    a = await _store_entry(store, content="lonely entry")

    result = await _handle_relations(store, {"action": "get", "entry_id": a})
    data = _parse(result)
    assert data["count"] == 0
    assert data["relations"] == []


@pytest.mark.unit
async def test_handle_relations_get_unexpected_error() -> None:
    """get action propagates unexpected store errors as RELATIONS_ERROR."""
    fake_store = AsyncMock()
    fake_store.get_related.side_effect = RuntimeError("db exploded")

    result = await _handle_relations(
        fake_store,
        {"action": "get", "entry_id": "some-id"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INTERNAL"


# ---------------------------------------------------------------------------
# action == "remove"
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_handle_relations_remove_success(store) -> None:  # type: ignore[no-untyped-def]
    """remove action deletes the relation and returns removed=True."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    relation_id = await store.add_relation(a, b, "link")

    result = await _handle_relations(
        store,
        {"action": "remove", "relation_id": relation_id},
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["removed"] is True
    assert data["relation_id"] == relation_id


@pytest.mark.unit
async def test_handle_relations_remove_not_found(store) -> None:  # type: ignore[no-untyped-def]
    """remove action returns removed=False when relation_id does not exist."""
    result = await _handle_relations(
        store,
        {"action": "remove", "relation_id": "nonexistent-relation-uuid"},
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["removed"] is False


@pytest.mark.unit
async def test_handle_relations_remove_missing_relation_id() -> None:
    """remove action without relation_id returns MISSING_FIELD error."""
    result = await _handle_relations(AsyncMock(), {"action": "remove"})
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "relation_id" in data["message"]


@pytest.mark.unit
async def test_handle_relations_remove_unexpected_error() -> None:
    """remove action propagates unexpected store errors as RELATIONS_ERROR."""
    fake_store = AsyncMock()
    fake_store.remove_relation.side_effect = RuntimeError("db exploded")

    result = await _handle_relations(
        fake_store,
        {"action": "remove", "relation_id": "some-id"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INTERNAL"


# ===========================================================================
# T02.1: Store-layer pending candidates (R2.1 / R2.2 / R2.4)
# ===========================================================================


@pytest.mark.unit
async def test_add_relation_candidate_returns_uuid(store) -> None:  # type: ignore[no-untyped-def]
    """add_relation_candidate persists a pending row and returns a UUID (R2.1)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation_candidate(a, b, "related", 0.72)

    assert isinstance(relation_id, str)
    assert len(relation_id) > 0


@pytest.mark.unit
async def test_add_relation_candidate_metadata_fields(store) -> None:  # type: ignore[no-untyped-def]
    """Pending candidate row carries review_status='pending' and suggestion_score (R2.1)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation_candidate(a, b, "related", 0.72)

    conn = store.connection
    row = conn.execute(
        "SELECT metadata FROM entry_relations WHERE id = ?", [relation_id]
    ).fetchone()
    assert row is not None
    meta = json.loads(row[0])
    assert meta["review_status"] == "pending"
    assert meta["suggestion_score"] == 0.72


@pytest.mark.unit
async def test_add_relation_candidate_no_new_table(store) -> None:  # type: ignore[no-untyped-def]
    """Pending candidates use entry_relations — no new table is created (R2.1)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    await store.add_relation_candidate(a, b, "related", 0.65)

    conn = store.connection
    tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
    assert "entry_relations" in tables
    assert not any("candidate" in t for t in tables)


@pytest.mark.unit
async def test_add_relation_candidate_idempotent(store) -> None:  # type: ignore[no-untyped-def]
    """Calling add_relation_candidate twice for the same triple returns same id (R2.1)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    first = await store.add_relation_candidate(a, b, "related", 0.72)
    second = await store.add_relation_candidate(a, b, "related", 0.80)

    assert first == second


@pytest.mark.unit
async def test_add_relation_candidate_idempotent_when_live_edge_exists(store) -> None:  # type: ignore[no-untyped-def]
    """add_relation_candidate is a no-op when a live edge already exists (R2.1)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    live_id = await store.add_relation(a, b, "related")
    candidate_id = await store.add_relation_candidate(a, b, "related", 0.90)

    assert live_id == candidate_id


@pytest.mark.unit
async def test_add_relation_candidate_invalid_from_id(store) -> None:  # type: ignore[no-untyped-def]
    """add_relation_candidate raises ValueError when from_id does not exist."""
    b = await _store_entry(store, content="entry B")

    with pytest.raises(ValueError, match="from_id"):
        await store.add_relation_candidate("nonexistent-id", b, "related", 0.72)


@pytest.mark.unit
async def test_add_relation_candidate_invalid_to_id(store) -> None:  # type: ignore[no-untyped-def]
    """add_relation_candidate raises ValueError when to_id does not exist."""
    a = await _store_entry(store, content="entry A")

    with pytest.raises(ValueError, match="to_id"):
        await store.add_relation_candidate(a, "nonexistent-id", "related", 0.72)


@pytest.mark.unit
async def test_list_relation_candidates_returns_pending_only(store) -> None:  # type: ignore[no-untyped-def]
    """list_relation_candidates returns only pending rows, not live edges (R2.2)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation_candidate(a, b, "related", 0.72)
    await store.add_relation(a, c, "related")

    candidates = await store.list_relation_candidates()

    assert len(candidates) == 1
    assert candidates[0]["from_id"] == a
    assert candidates[0]["to_id"] == b


@pytest.mark.unit
async def test_list_relation_candidates_ordered_by_score_descending(store) -> None:  # type: ignore[no-untyped-def]
    """list_relation_candidates returns candidates ordered by score descending (R2.2)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation_candidate(a, b, "related", 0.65)
    await store.add_relation_candidate(a, c, "related", 0.72)

    candidates = await store.list_relation_candidates()

    assert len(candidates) == 2
    assert candidates[0]["suggestion_score"] == 0.72
    assert candidates[1]["suggestion_score"] == 0.65
    assert candidates[0]["to_id"] == c
    assert candidates[1]["to_id"] == b


@pytest.mark.unit
async def test_list_relation_candidates_fields(store) -> None:  # type: ignore[no-untyped-def]
    """Each candidate dict has the expected fields including suggestion_score (R2.2)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    await store.add_relation_candidate(a, b, "related", 0.75)

    candidates = await store.list_relation_candidates()
    assert len(candidates) == 1
    row = candidates[0]
    assert "id" in row
    assert row["from_id"] == a
    assert row["to_id"] == b
    assert row["relation_type"] == "related"
    assert row["suggestion_score"] == 0.75
    assert "created_at" in row


@pytest.mark.unit
async def test_get_related_excludes_pending_candidates(store) -> None:  # type: ignore[no-untyped-def]
    """get_related (default) does not return pending candidates (R2.4)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    await store.add_relation_candidate(a, b, "related", 0.72)

    related = await store.get_related(a)
    assert related == []

    candidates = await store.list_relation_candidates()
    assert len(candidates) == 1
    assert candidates[0]["from_id"] == a


@pytest.mark.unit
async def test_get_related_still_returns_live_edges_when_candidate_also_exists(store) -> None:  # type: ignore[no-untyped-def]
    """Live edges appear in get_related even when a pending candidate exists for a different pair."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "related")
    await store.add_relation_candidate(a, c, "related", 0.72)

    related = await store.get_related(a)
    to_ids = {r["to_id"] for r in related}
    assert b in to_ids
    assert c not in to_ids


# ===========================================================================
# T02.2: MCP list_candidates + resolve_candidate actions (R2.3)
# ===========================================================================


@pytest.mark.unit
async def test_handle_relations_list_candidates_empty(store) -> None:  # type: ignore[no-untyped-def]
    """list_candidates returns an empty list when no pending candidates exist."""
    result = await _handle_relations(store, {"action": "list_candidates"})
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["action"] == "list_candidates"
    assert data["candidates"] == []
    assert data["count"] == 0


@pytest.mark.unit
async def test_handle_relations_list_candidates_returns_pending_rows(store) -> None:  # type: ignore[no-untyped-def]
    """list_candidates returns pending rows sorted by score descending (R2.3)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation_candidate(a, b, "related", 0.65)
    await store.add_relation_candidate(a, c, "related", 0.80)

    result = await _handle_relations(store, {"action": "list_candidates"})
    data = _parse(result)
    assert data["count"] == 2
    # Ordered by score descending.
    assert data["candidates"][0]["suggestion_score"] == 0.80
    assert data["candidates"][1]["suggestion_score"] == 0.65


@pytest.mark.unit
async def test_handle_relations_list_candidates_excludes_live_edges(store) -> None:  # type: ignore[no-untyped-def]
    """list_candidates does not return live edges, only pending candidates."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")
    c = await _store_entry(store, content="entry C")

    await store.add_relation(a, b, "related")  # live edge
    await store.add_relation_candidate(a, c, "related", 0.75)  # pending

    result = await _handle_relations(store, {"action": "list_candidates"})
    data = _parse(result)
    assert data["count"] == 1
    assert data["candidates"][0]["to_id"] == c


@pytest.mark.unit
async def test_handle_relations_list_candidates_unexpected_error() -> None:
    """list_candidates propagates unexpected store errors as INTERNAL."""
    fake_store = AsyncMock()
    fake_store.list_relation_candidates.side_effect = RuntimeError("db exploded")

    result = await _handle_relations(fake_store, {"action": "list_candidates"})
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INTERNAL"


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_missing_relation_id() -> None:
    """resolve_candidate without relation_id returns INVALID_PARAMS."""
    result = await _handle_relations(AsyncMock(), {"action": "resolve_candidate", "decision": "accept"})
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "relation_id" in data["message"]


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_missing_decision() -> None:
    """resolve_candidate without decision returns INVALID_PARAMS."""
    result = await _handle_relations(
        AsyncMock(), {"action": "resolve_candidate", "relation_id": "some-id"}
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "decision" in data["message"]


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_invalid_decision() -> None:
    """resolve_candidate with unknown decision returns INVALID_PARAMS."""
    result = await _handle_relations(
        AsyncMock(),
        {"action": "resolve_candidate", "relation_id": "some-id", "decision": "maybe"},
    )
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "decision" in data["message"]


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_reject(store) -> None:  # type: ignore[no-untyped-def]
    """resolve_candidate(decision=reject) deletes the pending row."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation_candidate(a, b, "related", 0.75)

    result = await _handle_relations(
        store,
        {"action": "resolve_candidate", "relation_id": relation_id, "decision": "reject"},
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["decision"] == "reject"
    assert data["removed"] is True

    # Candidate is gone.
    candidates = await store.list_relation_candidates()
    assert candidates == []


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_reject_idempotent(store) -> None:  # type: ignore[no-untyped-def]
    """resolve_candidate(decision=reject) is a no-op on already-rejected candidate (returns removed=False)."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation_candidate(a, b, "related", 0.75)

    # Reject once.
    await _handle_relations(
        store,
        {"action": "resolve_candidate", "relation_id": relation_id, "decision": "reject"},
    )
    # Reject again — should be a no-op success.
    result = await _handle_relations(
        store,
        {"action": "resolve_candidate", "relation_id": relation_id, "decision": "reject"},
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["removed"] is False


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_accept(store) -> None:  # type: ignore[no-untyped-def]
    """resolve_candidate(decision=accept) promotes the candidate to a live edge."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation_candidate(a, b, "related", 0.75)

    result = await _handle_relations(
        store,
        {"action": "resolve_candidate", "relation_id": relation_id, "decision": "accept"},
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["decision"] == "accept"
    assert data["promoted"] is True
    assert data["from_id"] == a
    assert data["to_id"] == b
    assert data["relation_type"] == "related"

    # The edge is now live: get_related returns it.
    related = await store.get_related(a)
    assert len(related) == 1
    assert related[0]["to_id"] == b

    # No more pending candidates.
    candidates = await store.list_relation_candidates()
    assert candidates == []


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_accept_idempotent(store) -> None:  # type: ignore[no-untyped-def]
    """resolve_candidate(decision=accept) is a no-op when candidate is already accepted."""
    a = await _store_entry(store, content="entry A")
    b = await _store_entry(store, content="entry B")

    relation_id = await store.add_relation_candidate(a, b, "related", 0.75)

    # Accept once.
    await _handle_relations(
        store,
        {"action": "resolve_candidate", "relation_id": relation_id, "decision": "accept"},
    )
    # Accept again — candidate no longer in pending list; should return promoted=False.
    result = await _handle_relations(
        store,
        {"action": "resolve_candidate", "relation_id": relation_id, "decision": "accept"},
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["promoted"] is False

    # Live edge is still there.
    related = await store.get_related(a)
    assert len(related) == 1


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_accept_nonexistent_is_noop(store) -> None:  # type: ignore[no-untyped-def]
    """resolve_candidate(decision=accept) for a nonexistent ID is a no-op success."""
    result = await _handle_relations(
        store,
        {
            "action": "resolve_candidate",
            "relation_id": "00000000-0000-0000-0000-000000000000",
            "decision": "accept",
        },
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["promoted"] is False


@pytest.mark.unit
async def test_handle_relations_resolve_candidate_reject_nonexistent_is_noop(store) -> None:  # type: ignore[no-untyped-def]
    """resolve_candidate(decision=reject) for a nonexistent ID is a no-op success (removed=False)."""
    result = await _handle_relations(
        store,
        {
            "action": "resolve_candidate",
            "relation_id": "00000000-0000-0000-0000-000000000000",
            "decision": "reject",
        },
    )
    data = _parse(result)
    assert "error" not in data or data.get("error") is False
    assert data["removed"] is False
