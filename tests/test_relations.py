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
    assert set(row.keys()) == {"id", "from_id", "to_id", "relation_type", "created_at"}
    assert row["id"] == relation_id
    assert row["from_id"] == a
    assert row["to_id"] == b
    assert row["relation_type"] == "link"
    assert isinstance(row["created_at"], str)


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
    assert data["code"] == "INVALID_ACTION"


@pytest.mark.unit
async def test_handle_relations_unknown_action() -> None:
    """Passing an unrecognised action returns INVALID_ACTION error."""
    result = await _handle_relations(AsyncMock(), {"action": "delete"})
    data = _parse(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_ACTION"
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
    assert data["code"] == "MISSING_FIELD"
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
    assert data["code"] == "MISSING_FIELD"
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
    assert data["code"] == "MISSING_FIELD"
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
    assert data["code"] == "RELATIONS_ERROR"


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
    assert data["code"] == "MISSING_FIELD"
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
    assert data["code"] == "INVALID_FIELD"
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
    assert data["code"] == "RELATIONS_ERROR"


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
    assert data["code"] == "MISSING_FIELD"
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
    assert data["code"] == "RELATIONS_ERROR"
