"""Tests for session_id as a first-class Entry field.

Covers:
  - session_id stored and retrieved correctly
  - session_id defaults to None when not provided
  - session_id filter in list_entries, search, and aggregate
  - session_id update via store.update()
  - session_id in to_dict() / from_dict() roundtrip
  - session_id accepted via distillery_store and distillery_list MCP tools
  - Migration 11 adds session_id column to entries table
"""

from __future__ import annotations

import pytest

from distillery.models import Entry, EntryType
from distillery.store.migrations import MIGRATIONS
from tests.conftest import make_entry, parse_mcp_response

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Store and retrieve
# ---------------------------------------------------------------------------


class TestSessionIdStoreAndGet:
    """Entries stored with/without session_id are persisted correctly."""

    async def test_store_with_session_id(self, store: object) -> None:
        entry = make_entry(content="session entry", session_id="sess-abc-123")
        entry_id = await store.store(entry)  # type: ignore[attr-defined]
        fetched = await store.get(entry_id)  # type: ignore[attr-defined]
        assert fetched is not None
        assert fetched.session_id == "sess-abc-123"

    async def test_store_without_session_id(self, store: object) -> None:
        entry = make_entry(content="no session entry")
        entry_id = await store.store(entry)  # type: ignore[attr-defined]
        fetched = await store.get(entry_id)  # type: ignore[attr-defined]
        assert fetched is not None
        assert fetched.session_id is None

    async def test_session_id_none_by_default(self) -> None:
        entry = make_entry(content="default session")
        assert entry.session_id is None


# ---------------------------------------------------------------------------
# Filter by session_id in list_entries
# ---------------------------------------------------------------------------


class TestSessionIdListFilter:
    """list_entries filtered by session_id returns only matching entries."""

    async def test_filter_by_session_id(self, store: object) -> None:
        for i in range(3):
            await store.store(make_entry(content=f"sess-001 entry {i}", session_id="sess-001"))  # type: ignore[attr-defined]
        for i in range(2):
            await store.store(make_entry(content=f"sess-002 entry {i}", session_id="sess-002"))  # type: ignore[attr-defined]

        results = await store.list_entries(filters={"session_id": "sess-001"}, limit=10, offset=0)  # type: ignore[attr-defined]
        assert len(results) == 3
        assert all(e.session_id == "sess-001" for e in results)

    async def test_filter_excludes_other_sessions(self, store: object) -> None:
        await store.store(make_entry(content="in session", session_id="sess-A"))  # type: ignore[attr-defined]
        await store.store(make_entry(content="no session"))  # type: ignore[attr-defined]

        results = await store.list_entries(filters={"session_id": "sess-A"}, limit=10, offset=0)  # type: ignore[attr-defined]
        assert len(results) == 1
        assert results[0].session_id == "sess-A"

    async def test_no_filter_returns_all(self, store: object) -> None:
        await store.store(make_entry(content="with session", session_id="sess-X"))  # type: ignore[attr-defined]
        await store.store(make_entry(content="without session"))  # type: ignore[attr-defined]

        results = await store.list_entries(filters=None, limit=10, offset=0)  # type: ignore[attr-defined]
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Filter by session_id in search
# ---------------------------------------------------------------------------


class TestSessionIdSearchFilter:
    """search filtered by session_id returns only matching entries."""

    async def test_search_filter_by_session_id(self, store: object) -> None:
        await store.store(make_entry(content="alpha pattern discovery", session_id="sess-alpha"))  # type: ignore[attr-defined]
        await store.store(make_entry(content="beta pattern discovery"))  # type: ignore[attr-defined]

        results = await store.search(  # type: ignore[attr-defined]
            query="pattern discovery",
            filters={"session_id": "sess-alpha"},
            limit=10,
        )
        assert len(results) >= 1
        assert all(sr.entry.session_id == "sess-alpha" for sr in results)


# ---------------------------------------------------------------------------
# Filter by session_id in aggregate
# ---------------------------------------------------------------------------


class TestSessionIdAggregateFilter:
    """aggregate_entries filtered by session_id reflects only matching entries."""

    async def test_aggregate_filter_by_session_id(self, store: object) -> None:
        await store.store(make_entry(content="sess-A idea", entry_type=EntryType.IDEA, session_id="sess-A"))  # type: ignore[attr-defined]
        await store.store(make_entry(content="sess-A inbox", entry_type=EntryType.INBOX, session_id="sess-A"))  # type: ignore[attr-defined]
        await store.store(make_entry(content="sess-B reference", entry_type=EntryType.REFERENCE, session_id="sess-B"))  # type: ignore[attr-defined]

        result = await store.aggregate_entries(  # type: ignore[attr-defined]
            group_by="entry_type",
            filters={"session_id": "sess-A"},
            limit=10,
        )
        total = result["total_entries"]
        assert total == 2

        group_names = {g["value"] for g in result["groups"]}
        assert "idea" in group_names or "inbox" in group_names
        assert "reference" not in group_names


# ---------------------------------------------------------------------------
# Update session_id
# ---------------------------------------------------------------------------


class TestSessionIdUpdate:
    """session_id can be updated via store.update()."""

    async def test_update_session_id(self, store: object) -> None:
        entry = make_entry(content="update session", session_id="sess-old")
        entry_id = await store.store(entry)  # type: ignore[attr-defined]

        updated = await store.update(entry_id, {"session_id": "sess-new"})  # type: ignore[attr-defined]
        assert updated.session_id == "sess-new"

        fetched = await store.get(entry_id)  # type: ignore[attr-defined]
        assert fetched is not None
        assert fetched.session_id == "sess-new"

    async def test_update_session_id_to_none(self, store: object) -> None:
        entry = make_entry(content="clear session", session_id="sess-to-clear")
        entry_id = await store.store(entry)  # type: ignore[attr-defined]

        updated = await store.update(entry_id, {"session_id": None})  # type: ignore[attr-defined]
        assert updated.session_id is None


# ---------------------------------------------------------------------------
# Roundtrip: to_dict / from_dict
# ---------------------------------------------------------------------------


class TestSessionIdRoundtrip:
    """session_id survives to_dict() / from_dict() serialisation."""

    def test_to_dict_includes_session_id(self) -> None:
        entry = make_entry(content="roundtrip", session_id="sess-export-1")
        d = entry.to_dict()
        assert "session_id" in d
        assert d["session_id"] == "sess-export-1"

    def test_from_dict_restores_session_id(self) -> None:
        entry = make_entry(content="roundtrip", session_id="sess-export-1")
        d = entry.to_dict()
        restored = Entry.from_dict(d)
        assert restored.session_id == "sess-export-1"
        assert restored == entry

    def test_from_dict_without_session_id_defaults_to_none(self) -> None:
        entry = make_entry(content="legacy entry")
        d = entry.to_dict()
        del d["session_id"]

        restored = Entry.from_dict(d)
        assert restored.session_id is None

    def test_to_dict_session_id_none_when_unset(self) -> None:
        entry = make_entry(content="no session")
        d = entry.to_dict()
        assert "session_id" in d
        assert d["session_id"] is None


# ---------------------------------------------------------------------------
# MCP tool: distillery_store
# ---------------------------------------------------------------------------


class TestSessionIdMcpStore:
    """distillery_store accepts session_id parameter."""

    async def test_store_with_session_id(self, store: object) -> None:
        from distillery.mcp.tools.crud import _handle_store

        result = await _handle_store(
            store,
            {
                "content": "mcp session entry",
                "entry_type": "inbox",
                "author": "tester",
                "session_id": "sess-mcp-1",
            },
        )
        parsed = parse_mcp_response(result)
        assert "entry_id" in parsed

        fetched = await store.get(parsed["entry_id"])  # type: ignore[attr-defined]
        assert fetched is not None
        assert fetched.session_id == "sess-mcp-1"

    async def test_store_without_session_id(self, store: object) -> None:
        from distillery.mcp.tools.crud import _handle_store

        result = await _handle_store(
            store,
            {
                "content": "no session mcp entry",
                "entry_type": "inbox",
                "author": "tester",
            },
        )
        parsed = parse_mcp_response(result)
        assert "entry_id" in parsed

        fetched = await store.get(parsed["entry_id"])  # type: ignore[attr-defined]
        assert fetched is not None
        assert fetched.session_id is None


# ---------------------------------------------------------------------------
# MCP tool: distillery_list with session_id filter
# ---------------------------------------------------------------------------


class TestSessionIdMcpList:
    """distillery_list accepts session_id filter."""

    async def test_list_filter_by_session_id(self, store: object) -> None:
        from distillery.mcp.tools.crud import _handle_list, _handle_store

        # Store two entries under session_id "sess-filter"
        for i in range(2):
            await _handle_store(
                store,
                {
                    "content": f"session filter entry {i}",
                    "entry_type": "inbox",
                    "author": "tester",
                    "session_id": "sess-filter",
                },
            )
        # Store one entry without session_id
        await _handle_store(
            store,
            {
                "content": "non-session entry",
                "entry_type": "inbox",
                "author": "tester",
            },
        )

        result = await _handle_list(
            store,
            {"session_id": "sess-filter", "limit": 10},
        )
        parsed = parse_mcp_response(result)
        assert parsed["count"] == 2
        assert all(e.get("session_id") == "sess-filter" for e in parsed["entries"])


# ---------------------------------------------------------------------------
# MCP tool: distillery_update with session_id
# ---------------------------------------------------------------------------


class TestSessionIdMcpUpdate:
    """distillery_update accepts session_id parameter."""

    async def test_update_session_id(self, store: object) -> None:
        from distillery.mcp.tools.crud import _handle_store, _handle_update

        store_result = await _handle_store(
            store,
            {
                "content": "entry to update session",
                "entry_type": "inbox",
                "author": "tester",
            },
        )
        entry_id = parse_mcp_response(store_result)["entry_id"]

        update_result = await _handle_update(
            store,
            {"entry_id": entry_id, "session_id": "sess-updated"},
        )
        parsed = parse_mcp_response(update_result)
        assert parsed.get("session_id") == "sess-updated"


# ---------------------------------------------------------------------------
# Migration 11
# ---------------------------------------------------------------------------


class TestMigration11:
    """Migration 11 adds session_id column to entries."""

    def test_migration_11_registered(self) -> None:
        assert 11 in MIGRATIONS

    async def test_session_id_column_present_after_initialize(self, store: object) -> None:
        """After initialize(), entries table must have a session_id column."""
        conn = store._conn  # type: ignore[attr-defined]
        result = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'entries' AND column_name = 'session_id'"
        ).fetchone()
        assert result is not None, "session_id column missing from entries table"

    async def test_existing_entries_have_null_session_id(self, store: object) -> None:
        """Entries stored without session_id have NULL in the session_id column."""
        entry = make_entry(content="pre-migration style entry")
        entry_id = await store.store(entry)  # type: ignore[attr-defined]

        conn = store._conn  # type: ignore[attr-defined]
        row = conn.execute(
            "SELECT session_id FROM entries WHERE id = ?", [entry_id]
        ).fetchone()
        assert row is not None
        assert row[0] is None
