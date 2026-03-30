"""Tests for store-layer security hardening.

Covers:
  - Column name whitelist in _sync_update() (T01)
  - Entry ownership fields (T02)
  - Per-tool authorization (T03)
"""

from __future__ import annotations

import pytest

from distillery.store.duckdb import DuckDBStore
from tests.conftest import make_entry

# ---------------------------------------------------------------------------
# T01: Column name whitelist
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_update_rejects_invalid_column_names(store: DuckDBStore) -> None:
    """_sync_update() raises ValueError for column names not in the whitelist."""
    entry = make_entry(content="Test entry")
    entry_id = await store.store(entry)

    with pytest.raises(ValueError, match="Cannot update unknown column"):
        await store.update(entry_id, {"status = 'x'; DROP TABLE entries; --": "bad"})


@pytest.mark.unit
async def test_update_accepts_all_valid_columns(store: DuckDBStore) -> None:
    """All 7 allowed columns are individually accepted by _sync_update()."""
    entry = make_entry(content="Test entry", author="alice", project="proj")
    entry_id = await store.store(entry)

    # Each of these should succeed without ValueError.
    await store.update(entry_id, {"content": "Updated content"})
    await store.update(entry_id, {"entry_type": "reference"})
    await store.update(entry_id, {"author": "bob"})
    await store.update(entry_id, {"project": "new-proj"})
    await store.update(entry_id, {"tags": ["tag-a"]})
    await store.update(entry_id, {"status": "archived"})
    await store.update(entry_id, {"metadata": {"key": "value"}})


@pytest.mark.unit
async def test_update_immutable_check_precedes_whitelist(store: DuckDBStore) -> None:
    """_IMMUTABLE_FIELDS check runs before the whitelist check.

    When both an immutable field and an unknown column are in updates,
    the immutable error should be raised first.
    """
    entry = make_entry(content="Test entry")
    entry_id = await store.store(entry)

    with pytest.raises(ValueError, match="Cannot update immutable field"):
        await store.update(entry_id, {"id": "new-id", "bogus_col": "bad"})


# ---------------------------------------------------------------------------
# T02: Entry ownership
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_store_sets_created_by(store: DuckDBStore) -> None:
    """Storing an entry with created_by populates the field on retrieval."""
    entry = make_entry(content="Owned entry", created_by="alice")
    entry_id = await store.store(entry)

    retrieved = await store.get(entry_id)
    assert retrieved is not None
    assert retrieved.created_by == "alice"


@pytest.mark.unit
async def test_update_sets_last_modified_by(store: DuckDBStore) -> None:
    """Updating an entry sets last_modified_by."""
    entry = make_entry(content="Modifiable entry")
    entry_id = await store.store(entry)

    await store.update(entry_id, {"content": "Changed", "last_modified_by": "bob"})

    retrieved = await store.get(entry_id)
    assert retrieved is not None
    assert retrieved.last_modified_by == "bob"


@pytest.mark.unit
async def test_legacy_entry_has_empty_ownership(store: DuckDBStore) -> None:
    """Entries created without ownership fields default to empty strings."""
    entry = make_entry(content="Legacy entry")
    entry_id = await store.store(entry)

    retrieved = await store.get(entry_id)
    assert retrieved is not None
    assert retrieved.created_by == ""
    assert retrieved.last_modified_by == ""
