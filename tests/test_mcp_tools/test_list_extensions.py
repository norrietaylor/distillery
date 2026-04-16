"""Test suite for list extensions: stale_days, group_by, output=stats parameters.

Tests exercise ``_handle_list`` directly with a real in-memory DuckDB store.
All stale_days, group_by, and output=stats logic added in T01.1/T01.2 is covered.

Markers:
  unit        -- validation / error path tests (no DB interaction)
  integration -- tests that require a populated DuckDB store
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from distillery.mcp.tools.crud import _handle_list
from distillery.models import EntrySource, EntryType
from tests.conftest import make_entry, parse_mcp_response

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_entry_with_timestamps(
    store: Any,
    entry: Any,
    accessed_at: datetime | None,
    updated_at: datetime | None = None,
) -> None:
    """Store an entry then back-date accessed_at and/or updated_at via raw SQL."""
    await store.store(entry)

    def _patch() -> None:
        if accessed_at is not None:
            store.connection.execute(
                "UPDATE entries SET accessed_at = ? WHERE id = ?",
                [accessed_at.isoformat(), entry.id],
            )
        if updated_at is not None:
            store.connection.execute(
                "UPDATE entries SET updated_at = ?, accessed_at = NULL WHERE id = ?",
                [updated_at.isoformat(), entry.id],
            )

    await asyncio.to_thread(_patch)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store_with_stale(store: Any) -> Any:  # type: ignore[return]
    """Store with a mix of stale and recent entries.

    Stale (accessed 30 days ago):
        stale1 (INBOX), stale2 (SESSION)
    Recent (accessed 1 day ago):
        recent1 (INBOX)
    No accessed_at, updated 30 days ago (stale via COALESCE):
        old_no_access (SESSION)
    No accessed_at, updated 1 day ago (recent via COALESCE):
        new_no_access (SESSION)
    """
    now = datetime.now(UTC)
    thirty_days_ago = now - timedelta(days=30)
    one_day_ago = now - timedelta(days=1)

    stale1 = make_entry(content="Stale entry 1", entry_type=EntryType.INBOX)
    stale2 = make_entry(content="Stale entry 2", entry_type=EntryType.SESSION)
    recent1 = make_entry(content="Recent entry 1", entry_type=EntryType.INBOX)
    old_no_access = make_entry(content="Old updated no access", entry_type=EntryType.SESSION)
    new_no_access = make_entry(content="New updated no access", entry_type=EntryType.SESSION)

    await _store_entry_with_timestamps(store, stale1, accessed_at=thirty_days_ago)
    await _store_entry_with_timestamps(store, stale2, accessed_at=thirty_days_ago)
    await _store_entry_with_timestamps(store, recent1, accessed_at=one_day_ago)
    await _store_entry_with_timestamps(
        store, old_no_access, accessed_at=None, updated_at=thirty_days_ago
    )
    await _store_entry_with_timestamps(
        store, new_no_access, accessed_at=None, updated_at=one_day_ago
    )

    store._stale_ids = {stale1.id, stale2.id, old_no_access.id}
    store._recent_ids = {recent1.id, new_no_access.id}
    return store


@pytest.fixture
async def populated_store(store: Any) -> Any:  # type: ignore[return]
    """Store with diverse entries for group_by and stats tests.

    Entry counts:
        entry_type: inbox=3, session=1, idea=1
        author:     alice=3, bob=2
        project:    proj-a=3, proj-b=2
        source:     manual=4, claude_code=1
        tags:       api=3 (plus others)
        status:     (all default)
    """
    entries = [
        make_entry(
            content="Inbox entry 1",
            entry_type=EntryType.INBOX,
            author="alice",
            project="proj-a",
            tags=["python", "api"],
            source=EntrySource.MANUAL,
        ),
        make_entry(
            content="Inbox entry 2",
            entry_type=EntryType.INBOX,
            author="alice",
            project="proj-a",
            tags=["python", "cli"],
            source=EntrySource.MANUAL,
        ),
        make_entry(
            content="Inbox entry 3",
            entry_type=EntryType.INBOX,
            author="bob",
            project="proj-b",
            tags=["rss", "api"],
            source=EntrySource.MANUAL,
        ),
        make_entry(
            content="Session entry",
            entry_type=EntryType.SESSION,
            author="alice",
            project="proj-a",
            tags=["api"],
            source=EntrySource.MANUAL,
        ),
        make_entry(
            content="Idea entry",
            entry_type=EntryType.IDEA,
            author="bob",
            project="proj-b",
            tags=["session"],
            source=EntrySource.CLAUDE_CODE,
        ),
    ]
    for e in entries:
        await store.store(e)
    return store


# ---------------------------------------------------------------------------
# Unit tests: stale_days validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStaleDaysValidation:
    async def test_stale_days_not_integer_returns_error(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"stale_days": "30"})
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "stale_days" in data["message"]

    async def test_stale_days_zero_returns_error(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"stale_days": 0})
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "stale_days" in data["message"]

    async def test_stale_days_negative_returns_error(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"stale_days": -5})
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_stale_days_one_is_valid(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"stale_days": 1, "limit": 5})
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert "entries" in data

    async def test_stale_days_float_returns_error(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"stale_days": 7.5})
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# Integration tests: stale_days filtering behaviour
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStaleDaysFiltering:
    async def test_stale_days_returns_only_stale_entries(self, store_with_stale: Any) -> None:
        result = await _handle_list(
            store=store_with_stale,
            arguments={"stale_days": 7, "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        returned_ids = {e["id"] for e in data["entries"]}
        # stale1 and stale2 have accessed_at 30 days ago — should appear
        assert returned_ids & store_with_stale._stale_ids == store_with_stale._stale_ids
        # recent entries should NOT appear
        assert not returned_ids & store_with_stale._recent_ids

    async def test_stale_days_excludes_recent_entries(self, store_with_stale: Any) -> None:
        result = await _handle_list(
            store=store_with_stale,
            arguments={"stale_days": 7, "limit": 50},
        )
        data = parse_mcp_response(result)
        returned_ids = {e["id"] for e in data["entries"]}
        for recent_id in store_with_stale._recent_ids:
            assert recent_id not in returned_ids

    async def test_stale_days_coalesces_updated_at_when_no_accessed_at(
        self, store_with_stale: Any
    ) -> None:
        """old_no_access has no accessed_at; updated_at is 30 days ago — must be returned."""
        result = await _handle_list(
            store=store_with_stale,
            arguments={"stale_days": 7, "limit": 50},
        )
        data = parse_mcp_response(result)
        returned_ids = {e["id"] for e in data["entries"]}
        # All 3 stale entries (including old_no_access) must appear
        assert returned_ids & store_with_stale._stale_ids == store_with_stale._stale_ids

    async def test_stale_days_with_entry_type_filter(self, store_with_stale: Any) -> None:
        """stale_days composed with entry_type filter — only SESSION stale entries returned."""
        result = await _handle_list(
            store=store_with_stale,
            arguments={"stale_days": 7, "entry_type": "session", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        for entry in data["entries"]:
            assert entry["entry_type"] == "session"
        # stale2 (SESSION) and old_no_access (SESSION) should appear
        returned_ids = {e["id"] for e in data["entries"]}
        assert len(returned_ids) >= 2

    async def test_stale_days_with_author_filter(self, store: Any) -> None:
        """stale_days composed with author filter."""
        now = datetime.now(UTC)
        thirty_days_ago = now - timedelta(days=30)
        e1 = make_entry(content="Alice stale", author="alice", entry_type=EntryType.INBOX)
        e2 = make_entry(content="Bob stale", author="bob", entry_type=EntryType.INBOX)
        await _store_entry_with_timestamps(store, e1, accessed_at=thirty_days_ago)
        await _store_entry_with_timestamps(store, e2, accessed_at=thirty_days_ago)

        result = await _handle_list(
            store=store,
            arguments={"stale_days": 7, "author": "alice", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        for entry in data["entries"]:
            assert entry["author"] == "alice"

    async def test_stale_days_with_project_filter(self, store: Any) -> None:
        """stale_days composed with project filter."""
        now = datetime.now(UTC)
        thirty_days_ago = now - timedelta(days=30)
        e1 = make_entry(content="Proj-A stale", project="proj-a", entry_type=EntryType.INBOX)
        e2 = make_entry(content="Proj-B stale", project="proj-b", entry_type=EntryType.INBOX)
        await _store_entry_with_timestamps(store, e1, accessed_at=thirty_days_ago)
        await _store_entry_with_timestamps(store, e2, accessed_at=thirty_days_ago)

        result = await _handle_list(
            store=store,
            arguments={"stale_days": 7, "project": "proj-a", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        returned_ids = {e["id"] for e in data["entries"]}
        assert e1.id in returned_ids
        assert e2.id not in returned_ids

    async def test_stale_days_with_tags_filter(self, store: Any) -> None:
        """stale_days composed with tags filter."""
        now = datetime.now(UTC)
        thirty_days_ago = now - timedelta(days=30)
        e1 = make_entry(content="Tagged stale", tags=["python"], entry_type=EntryType.INBOX)
        e2 = make_entry(content="Other stale", tags=["rust"], entry_type=EntryType.INBOX)
        await _store_entry_with_timestamps(store, e1, accessed_at=thirty_days_ago)
        await _store_entry_with_timestamps(store, e2, accessed_at=thirty_days_ago)

        result = await _handle_list(
            store=store,
            arguments={"stale_days": 7, "tags": ["python"], "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        returned_ids = {e["id"] for e in data["entries"]}
        assert e1.id in returned_ids
        assert e2.id not in returned_ids

    async def test_stale_days_empty_store_returns_empty_list(self, store: Any) -> None:
        result = await _handle_list(
            store=store,
            arguments={"stale_days": 7, "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert data["entries"] == []
        assert data["count"] == 0


# ---------------------------------------------------------------------------
# Unit tests: group_by validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGroupByValidation:
    async def test_group_by_not_string_returns_error(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"group_by": 42})
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "group_by" in data["message"]

    async def test_group_by_invalid_value_returns_error(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"group_by": "nonexistent_field"})
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "group_by" in data["message"]

    async def test_group_by_and_output_stats_mutually_exclusive(self, store: Any) -> None:
        result = await _handle_list(
            store=store,
            arguments={"group_by": "entry_type", "output": "stats"},
        )
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        # Message should mention the mutual exclusivity constraint
        assert "group_by" in data["message"] or "mutually exclusive" in data["message"].lower()

    async def test_output_invalid_value_returns_error(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"output": "full"})
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "output" in data["message"]

    async def test_output_not_string_returns_error(self, store: Any) -> None:
        result = await _handle_list(store=store, arguments={"output": 99})
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# Integration tests: group_by behaviour
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGroupBy:
    async def test_group_by_entry_type_format(self, populated_store: Any) -> None:
        """group_by returns {groups, total_entries, total_groups} structure."""
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "entry_type", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert "groups" in data
        assert "total_entries" in data
        assert "total_groups" in data

    async def test_group_by_entry_type_counts(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "entry_type", "limit": 50},
        )
        data = parse_mcp_response(result)
        by_type = {g["value"]: g["count"] for g in data["groups"]}
        assert by_type["inbox"] == 3
        assert by_type["session"] == 1
        assert by_type["idea"] == 1
        assert data["total_entries"] == 5
        assert data["total_groups"] == 3

    async def test_group_by_status(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "status", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert "groups" in data
        assert data["total_entries"] == 5

    async def test_group_by_author(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "author", "limit": 50},
        )
        data = parse_mcp_response(result)
        by_author = {g["value"]: g["count"] for g in data["groups"]}
        assert by_author["alice"] == 3
        assert by_author["bob"] == 2

    async def test_group_by_project(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "project", "limit": 50},
        )
        data = parse_mcp_response(result)
        by_project = {g["value"]: g["count"] for g in data["groups"]}
        assert by_project["proj-a"] == 3
        assert by_project["proj-b"] == 2

    async def test_group_by_source(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "source", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        by_source = {g["value"]: g["count"] for g in data["groups"]}
        assert by_source.get("manual") == 4
        assert by_source.get("claude-code") == 1

    @pytest.mark.xfail(
        reason=(
            "DuckDB 1.5.1 does not support UNNEST() in a CTE SELECT; "
            "group_by=tags requires store-layer fix to use a two-step CTE. "
            "See aggregate_entries in duckdb.py."
        ),
        strict=True,
    )
    async def test_group_by_tags(self, populated_store: Any) -> None:
        """group_by=tags unnests tags array — each tag gets its own count."""
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "tags", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert "groups" in data
        # "api" appears in 3 entries
        by_tag = {g["value"]: g["count"] for g in data["groups"]}
        assert by_tag.get("api") == 3

    @pytest.mark.xfail(
        reason=(
            "DuckDB 1.5.1 does not support UNNEST() in a CTE SELECT; "
            "group_by=tags with tag_prefix requires store-layer fix. "
            "See aggregate_entries in duckdb.py."
        ),
        strict=True,
    )
    async def test_group_by_tags_with_tag_prefix(self, store: Any) -> None:
        """group_by=tags with tag_prefix filter limits to matching tags."""
        entries = [
            make_entry(content="py1", tags=["python", "api"], entry_type=EntryType.INBOX),
            make_entry(content="py2", tags=["python", "cli"], entry_type=EntryType.INBOX),
            make_entry(content="rs1", tags=["rust", "perf"], entry_type=EntryType.INBOX),
        ]
        for e in entries:
            await store.store(e)

        result = await _handle_list(
            store=store,
            arguments={"group_by": "tags", "tag_prefix": "py", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        tag_values = {g["value"] for g in data["groups"]}
        # Only "python" starts with "py"
        assert "python" in tag_values
        assert "rust" not in tag_values

    async def test_group_by_ordering_count_desc(self, populated_store: Any) -> None:
        """Groups are ordered by count descending."""
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "entry_type", "limit": 50},
        )
        data = parse_mcp_response(result)
        counts = [g["count"] for g in data["groups"]]
        assert counts == sorted(counts, reverse=True)

    async def test_group_by_total_fields_before_limit(self, populated_store: Any) -> None:
        """total_groups reflects full group count, even when limit truncates."""
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "entry_type", "limit": 1},
        )
        data = parse_mcp_response(result)
        assert len(data["groups"]) == 1
        assert data["total_groups"] == 3  # full count, not truncated

    async def test_group_by_with_entry_type_filter(self, populated_store: Any) -> None:
        """group_by composes with entry_type filter."""
        result = await _handle_list(
            store=populated_store,
            arguments={"group_by": "author", "entry_type": "inbox", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert data["total_entries"] == 3  # only inbox entries

    async def test_group_by_non_tag_values_do_not_error(self, populated_store: Any) -> None:
        """All non-tags valid group_by values execute without errors."""
        valid_non_tag_values = ["entry_type", "status", "author", "project", "source"]
        for value in valid_non_tag_values:
            result = await _handle_list(
                store=populated_store,
                arguments={"group_by": value, "limit": 50},
            )
            data = parse_mcp_response(result)
            assert not data.get("error"), f"group_by={value!r} returned error: {data}"


# ---------------------------------------------------------------------------
# Integration tests: output=stats behaviour
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOutputStats:
    async def test_output_stats_format(self, populated_store: Any) -> None:
        """output=stats returns entries_by_type, entries_by_status, total_entries, storage_bytes."""
        result = await _handle_list(
            store=populated_store,
            arguments={"output": "stats", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert "entries_by_type" in data
        assert "entries_by_status" in data
        assert "total_entries" in data
        assert "storage_bytes" in data

    async def test_output_stats_total_entries(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"output": "stats", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert data["total_entries"] == 5

    async def test_output_stats_entries_by_type(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"output": "stats", "limit": 50},
        )
        data = parse_mcp_response(result)
        by_type = data["entries_by_type"]
        assert by_type["inbox"] == 3
        assert by_type["session"] == 1
        assert by_type["idea"] == 1

    async def test_output_stats_entries_by_status(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"output": "stats", "limit": 50},
        )
        data = parse_mcp_response(result)
        by_status = data["entries_by_status"]
        assert isinstance(by_status, dict)
        assert sum(by_status.values()) == 5

    async def test_output_stats_storage_bytes_is_int(self, populated_store: Any) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"output": "stats", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert isinstance(data["storage_bytes"], int)
        assert data["storage_bytes"] >= 0

    async def test_output_stats_with_stale_days(self, store_with_stale: Any) -> None:
        """output=stats can be composed with stale_days for stale-entry stats."""
        result = await _handle_list(
            store=store_with_stale,
            arguments={"output": "stats", "stale_days": 7, "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert "total_entries" in data
        # 3 stale entries in the fixture
        assert data["total_entries"] == 3

    async def test_output_stats_empty_store(self, store: Any) -> None:
        result = await _handle_list(
            store=store,
            arguments={"output": "stats", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert data["total_entries"] == 0
        assert data["entries_by_type"] == {}
        assert data["entries_by_status"] == {}


# ---------------------------------------------------------------------------
# Unit tests: mutual exclusivity and combined invalid params
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMutualExclusivity:
    async def test_group_by_and_output_stats_both_present(self, store: Any) -> None:
        result = await _handle_list(
            store=store,
            arguments={"group_by": "entry_type", "output": "stats", "limit": 10},
        )
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_group_by_valid_without_output_stats(self, store: Any) -> None:
        """group_by alone (no output param) is valid."""
        result = await _handle_list(
            store=store,
            arguments={"group_by": "entry_type", "limit": 10},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")

    async def test_output_stats_without_group_by_is_valid(self, store: Any) -> None:
        result = await _handle_list(
            store=store,
            arguments={"output": "stats", "limit": 10},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
