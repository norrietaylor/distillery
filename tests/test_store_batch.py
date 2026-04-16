"""Tests for store_batch on the DuckDB backend."""

from __future__ import annotations

import pytest

from tests.conftest import make_entry


@pytest.mark.unit
async def test_store_batch_returns_entry_ids(store):  # type: ignore[no-untyped-def]
    """store_batch should return a list of IDs matching the input entries."""
    entries = [
        make_entry(content="Batch entry one"),
        make_entry(content="Batch entry two"),
        make_entry(content="Batch entry three"),
    ]
    ids = await store.store_batch(entries)
    assert len(ids) == 3
    assert ids == [e.id for e in entries]


@pytest.mark.unit
async def test_store_batch_entries_searchable(store):  # type: ignore[no-untyped-def]
    """Entries stored via store_batch should be retrievable by get."""
    entries = [
        make_entry(content="Alpha searchable batch"),
        make_entry(content="Beta searchable batch"),
    ]
    ids = await store.store_batch(entries)
    for entry_id in ids:
        retrieved = await store.get(entry_id)
        assert retrieved is not None
        assert retrieved.id == entry_id


@pytest.mark.unit
async def test_store_batch_empty_list(store):  # type: ignore[no-untyped-def]
    """store_batch with an empty list should return an empty result."""
    ids = await store.store_batch([])
    assert ids == []


@pytest.mark.unit
async def test_store_batch_preserves_fields(store):  # type: ignore[no-untyped-def]
    """store_batch should preserve entry fields like tags and metadata."""
    entries = [
        make_entry(
            content="Tagged batch entry",
            tags=["batch", "test"],
            metadata={"key": "value"},
            project="test-project",
        ),
    ]
    ids = await store.store_batch(entries)
    retrieved = await store.get(ids[0])
    assert retrieved is not None
    assert retrieved.tags == ["batch", "test"]
    assert retrieved.metadata == {"key": "value"}
    assert retrieved.project == "test-project"
