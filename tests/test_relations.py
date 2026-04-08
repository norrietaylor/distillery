"""Unit tests for entry relations store methods.

Covers:
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
"""

from __future__ import annotations

import pytest

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
