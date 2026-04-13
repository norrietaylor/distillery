"""Tests for the distillery_correct tool handler."""

from __future__ import annotations

import pytest

from distillery.mcp.tools.crud import _handle_correct
from distillery.models import EntrySource, EntryStatus, EntryType
from distillery.store.duckdb import DuckDBStore
from tests.conftest import make_entry, parse_mcp_response

pytestmark = pytest.mark.unit


@pytest.fixture
async def original_entry(store: DuckDBStore) -> str:
    """Store a basic entry and return its ID."""
    entry = make_entry(
        content="The earth is flat.",
        entry_type=EntryType.REFERENCE,
        author="alice",
        project="geography",
        tags=["science"],
        metadata={"confidence": 0.5},
    )
    return await store.store(entry)


async def test_correct_entry(store: DuckDBStore, original_entry: str) -> None:
    """Correcting an entry stores a new entry and archives the original."""
    result = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": original_entry,
            "content": "The earth is roughly spherical.",
        },
    )
    data = parse_mcp_response(result)
    assert "error" not in data
    assert data["archived_entry_id"] == original_entry
    assert "correction_entry_id" in data

    # Original should be archived.
    orig = await store.get(original_entry)
    assert orig is not None
    assert orig.status == EntryStatus.ARCHIVED

    # New entry should be active.
    new = await store.get(data["correction_entry_id"])
    assert new is not None
    assert new.status == EntryStatus.ACTIVE
    assert new.content == "The earth is roughly spherical."

    # Relationship should exist in entry_relations table.
    relations = await store.get_related(data["correction_entry_id"], direction="outgoing")
    assert len(relations) == 1
    assert relations[0]["to_id"] == original_entry
    assert relations[0]["relation_type"] == "corrects"


async def test_correct_inherits_fields(store: DuckDBStore, original_entry: str) -> None:
    """Fields are copied from the original when not provided."""
    result = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": original_entry,
            "content": "Corrected content.",
        },
    )
    data = parse_mcp_response(result)
    new = await store.get(data["correction_entry_id"])
    assert new is not None
    assert new.entry_type == EntryType.REFERENCE
    assert new.author == "alice"
    assert new.project == "geography"
    assert new.tags == ["science"]
    assert new.source == EntrySource.MANUAL


async def test_correct_overrides_fields(store: DuckDBStore, original_entry: str) -> None:
    """User-provided fields override those inherited from the original."""
    result = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": original_entry,
            "content": "Corrected content.",
            "entry_type": "idea",
            "author": "bob",
            "project": "cosmology",
            "tags": ["astrophysics"],
            "metadata": {"extra": "value"},
        },
    )
    data = parse_mcp_response(result)
    new = await store.get(data["correction_entry_id"])
    assert new is not None
    assert new.entry_type == EntryType.IDEA
    assert new.author == "bob"
    assert new.project == "cosmology"
    assert new.tags == ["astrophysics"]
    assert new.metadata["extra"] == "value"

    # Relationship exists in entry_relations table.
    relations = await store.get_related(data["correction_entry_id"], direction="outgoing")
    assert len(relations) == 1
    assert relations[0]["relation_type"] == "corrects"


async def test_correct_nonexistent_entry(store: DuckDBStore) -> None:
    """Correcting a non-existent entry returns NOT_FOUND."""
    result = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": "nonexistent-id",
            "content": "Irrelevant.",
        },
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "NOT_FOUND"


async def test_correct_archived_entry(store: DuckDBStore, original_entry: str) -> None:
    """Correcting an already-archived entry returns INVALID_STATE."""
    await store.update(original_entry, {"status": EntryStatus.ARCHIVED})

    result = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": original_entry,
            "content": "Doesn't matter.",
        },
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "archived" in data["message"].lower()


async def test_correction_chain(store: DuckDBStore, original_entry: str) -> None:
    """A chain of corrections maintains integrity (A -> B -> C)."""
    # First correction: B corrects A.
    r1 = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": original_entry,
            "content": "The earth is an oblate spheroid.",
        },
    )
    d1 = parse_mcp_response(r1)
    entry_b_id = d1["correction_entry_id"]

    # Second correction: C corrects B.
    r2 = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": entry_b_id,
            "content": "The earth is a geoid.",
        },
    )
    d2 = parse_mcp_response(r2)
    entry_c_id = d2["correction_entry_id"]

    # A and B should both be archived.
    a = await store.get(original_entry)
    b = await store.get(entry_b_id)
    c = await store.get(entry_c_id)
    assert a is not None and a.status == EntryStatus.ARCHIVED
    assert b is not None and b.status == EntryStatus.ARCHIVED
    assert c is not None and c.status == EntryStatus.ACTIVE

    # Relations form a chain: C -> B -> A.
    rels_c = await store.get_related(entry_c_id, direction="outgoing", relation_type="corrects")
    assert len(rels_c) == 1
    assert rels_c[0]["to_id"] == entry_b_id

    rels_b = await store.get_related(entry_b_id, direction="outgoing", relation_type="corrects")
    assert len(rels_b) == 1
    assert rels_b[0]["to_id"] == original_entry


async def test_correct_missing_content(store: DuckDBStore, original_entry: str) -> None:
    """Missing content returns INVALID_PARAMS."""
    result = await _handle_correct(
        store=store,
        arguments={"wrong_entry_id": original_entry},
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"


async def test_correct_invalid_entry_type(store: DuckDBStore, original_entry: str) -> None:
    """Invalid entry_type returns INVALID_PARAMS."""
    result = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": original_entry,
            "content": "Fixed.",
            "entry_type": "not_a_type",
        },
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"


async def test_correct_empty_tags_clears(store: DuckDBStore, original_entry: str) -> None:
    """Passing tags=[] explicitly clears tags instead of inheriting."""
    result = await _handle_correct(
        store=store,
        arguments={
            "wrong_entry_id": original_entry,
            "content": "Corrected.",
            "tags": [],
        },
    )
    data = parse_mcp_response(result)
    new = await store.get(data["correction_entry_id"])
    assert new is not None
    assert new.tags == []
