"""Tests for extended status flags (verified, testing).

Covers:
  - Create entries with verified/testing status
  - Transition between statuses
  - Filter by new statuses in list/search
"""

from __future__ import annotations

import pytest

from distillery.mcp.tools.crud import _handle_update
from distillery.models import EntryStatus
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider() -> MockEmbeddingProvider:
    return MockEmbeddingProvider()


@pytest.fixture
async def store(embedding_provider: MockEmbeddingProvider) -> DuckDBStore:  # type: ignore[return]
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateWithExtendedStatus:
    """Create entries with the new verified and testing statuses."""

    async def test_create_verified_entry(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Verified fact", status=EntryStatus.VERIFIED)
        entry_id = await store.store(entry)
        fetched = await store.get(entry_id)
        assert fetched is not None
        assert fetched.status is EntryStatus.VERIFIED

    async def test_create_testing_entry(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Experimental hypothesis", status=EntryStatus.TESTING)
        entry_id = await store.store(entry)
        fetched = await store.get(entry_id)
        assert fetched is not None
        assert fetched.status is EntryStatus.TESTING

    def test_enum_values(self) -> None:
        assert EntryStatus.VERIFIED.value == "verified"
        assert EntryStatus.TESTING.value == "testing"
        assert EntryStatus("verified") is EntryStatus.VERIFIED
        assert EntryStatus("testing") is EntryStatus.TESTING


class TestStatusTransitions:
    """Transition between all status values."""

    async def test_active_to_verified(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Will be verified")
        await store.store(entry)
        updated = await store.update(entry.id, {"status": EntryStatus.VERIFIED})
        assert updated.status is EntryStatus.VERIFIED

    async def test_testing_to_verified(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Testing entry", status=EntryStatus.TESTING)
        await store.store(entry)
        updated = await store.update(entry.id, {"status": EntryStatus.VERIFIED})
        assert updated.status is EntryStatus.VERIFIED

    async def test_verified_to_archived(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Verified then archived", status=EntryStatus.VERIFIED)
        await store.store(entry)
        updated = await store.update(entry.id, {"status": EntryStatus.ARCHIVED})
        assert updated.status is EntryStatus.ARCHIVED

    async def test_update_status_via_mcp_handler(self, store: DuckDBStore) -> None:
        entry = make_entry(content="MCP status update test")
        await store.store(entry)
        result = await _handle_update(
            store=store,
            arguments={"entry_id": entry.id, "status": "verified"},
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        assert data["status"] == "verified"

    async def test_update_to_testing_via_mcp_handler(self, store: DuckDBStore) -> None:
        entry = make_entry(content="MCP testing status")
        await store.store(entry)
        result = await _handle_update(
            store=store,
            arguments={"entry_id": entry.id, "status": "testing"},
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        assert data["status"] == "testing"


class TestFilterByStatus:
    """Filter entries by the new status values in list_entries."""

    async def test_list_verified_entries(self, store: DuckDBStore) -> None:
        e1 = make_entry(content="Verified one", status=EntryStatus.VERIFIED)
        e2 = make_entry(content="Active one", status=EntryStatus.ACTIVE)
        e3 = make_entry(content="Verified two", status=EntryStatus.VERIFIED)
        await store.store(e1)
        await store.store(e2)
        await store.store(e3)

        results = await store.list_entries(filters={"status": "verified"}, limit=10, offset=0)
        ids = [e.id for e in results]
        assert e1.id in ids
        assert e3.id in ids
        assert e2.id not in ids

    async def test_list_testing_entries(self, store: DuckDBStore) -> None:
        e1 = make_entry(content="Testing one", status=EntryStatus.TESTING)
        e2 = make_entry(content="Active one", status=EntryStatus.ACTIVE)
        await store.store(e1)
        await store.store(e2)

        results = await store.list_entries(filters={"status": "testing"}, limit=10, offset=0)
        ids = [e.id for e in results]
        assert e1.id in ids
        assert e2.id not in ids

    async def test_search_filters_by_status(self, store: DuckDBStore) -> None:
        e1 = make_entry(
            content="Verified searchable content alpha",
            status=EntryStatus.VERIFIED,
        )
        e2 = make_entry(
            content="Active searchable content alpha",
            status=EntryStatus.ACTIVE,
        )
        await store.store(e1)
        await store.store(e2)

        results = await store.search(
            "searchable content alpha",
            filters={"status": "verified"},
            limit=10,
        )
        ids = [r.entry.id for r in results]
        assert e1.id in ids
        assert e2.id not in ids
