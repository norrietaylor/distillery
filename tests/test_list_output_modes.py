"""Tests for distillery_list output_mode/content_max_length and distillery_aggregate.

Unit tests exercise _handle_list and _handle_aggregate directly with a real
in-memory DuckDB store.

Markers:
  unit        — _handle_list output_mode / content_max_length validation
  integration — _handle_aggregate group-by and filter behaviour
"""

from __future__ import annotations

import pytest

from distillery.mcp.server import _handle_list
from distillery.mcp.tools.search import _handle_aggregate
from distillery.models import EntrySource, EntryType
from tests.conftest import make_entry, parse_mcp_response


@pytest.fixture
async def populated_store(store):  # type: ignore[return]
    """Store with a mix of entry types for aggregation tests."""
    entries = [
        make_entry(
            content="Feed item one " * 20,
            entry_type=EntryType.FEED,
            source=EntrySource.MANUAL,
            author="alice",
            metadata={"source_url": "https://github.com/org/repo", "source_type": "github"},
        ),
        make_entry(
            content="Feed item two " * 20,
            entry_type=EntryType.FEED,
            source=EntrySource.MANUAL,
            author="alice",
            metadata={"source_url": "https://github.com/org/repo", "source_type": "github"},
        ),
        make_entry(
            content="RSS feed item",
            entry_type=EntryType.FEED,
            source=EntrySource.MANUAL,
            author="bob",
            metadata={"source_url": "https://example.com/rss", "source_type": "rss"},
        ),
        make_entry(
            content="Inbox item",
            entry_type=EntryType.INBOX,
            source=EntrySource.MANUAL,
            author="alice",
        ),
        make_entry(
            content="Session note",
            entry_type=EntryType.SESSION,
            source=EntrySource.CLAUDE_CODE,
            author="bob",
        ),
    ]
    for e in entries:
        await store.store(e)
    return store


# ---------------------------------------------------------------------------
# Unit tests: output_mode and content_max_length
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListOutputModes:
    async def test_full_mode_includes_content(self, populated_store) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"limit": 10, "output_mode": "full"},
        )
        data = parse_mcp_response(result)
        assert data["output_mode"] == "full"
        assert all("content" in e for e in data["entries"])

    async def test_summary_mode_excludes_content(self, populated_store) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"limit": 10, "output_mode": "summary"},
        )
        data = parse_mcp_response(result)
        assert data["output_mode"] == "summary"
        assert all("content" not in e for e in data["entries"])
        # Summary shape — issue #311 — id/title/tags/project/author/created_at
        # plus a ~200-char content_preview (+ metadata for dedup callers).
        for entry in data["entries"]:
            assert "id" in entry
            assert "title" in entry
            assert "entry_type" in entry
            assert "created_at" in entry
            assert "metadata" in entry
            assert "tags" in entry
            assert "project" in entry
            assert "author" in entry
            assert "content_preview" in entry

    async def test_ids_mode_minimal_fields(self, populated_store) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"limit": 10, "output_mode": "ids"},
        )
        data = parse_mcp_response(result)
        assert data["output_mode"] == "ids"
        for entry in data["entries"]:
            assert set(entry.keys()) == {"id", "entry_type", "created_at"}

    async def test_invalid_output_mode_returns_error(self, populated_store) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"limit": 10, "output_mode": "nope"},
        )
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "output_mode" in data["message"]

    async def test_content_max_length_truncates(self, populated_store) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"limit": 10, "output_mode": "full", "content_max_length": 10},
        )
        data = parse_mcp_response(result)
        for entry in data["entries"]:
            content = entry["content"]
            # Truncated entries end with the ellipsis character or are <= 11 chars
            assert len(content) <= 11  # 10 chars + "…"

    async def test_content_max_length_no_truncation_when_short(self, store) -> None:
        short_entry = make_entry(content="Hi")
        await store.store(short_entry)
        result = await _handle_list(
            store=store,
            arguments={"limit": 5, "output_mode": "full", "content_max_length": 200},
        )
        data = parse_mcp_response(result)
        entries_with_id = [e for e in data["entries"] if e["id"] == short_entry.id]
        assert len(entries_with_id) == 1
        assert entries_with_id[0]["content"] == "Hi"

    async def test_content_max_length_ignored_in_summary_mode(self, populated_store) -> None:
        # content_max_length should not cause errors in summary mode (content absent anyway)
        result = await _handle_list(
            store=populated_store,
            arguments={"limit": 5, "output_mode": "summary", "content_max_length": 10},
        )
        data = parse_mcp_response(result)
        assert not data.get("error")
        assert all("content" not in e for e in data["entries"])

    async def test_default_mode_is_summary(self, store) -> None:
        # Default output_mode is "summary" (see issue #311) to keep list
        # responses compact enough to avoid flooding agent context.
        entry = make_entry(content="Hello world")
        await store.store(entry)
        result = await _handle_list(store=store, arguments={"limit": 5})
        data = parse_mcp_response(result)
        assert data["output_mode"] == "summary"
        assert all("content" not in e for e in data["entries"])
        assert all("content_preview" in e for e in data["entries"])

    async def test_content_max_length_invalid_type_returns_error(self, store) -> None:
        result = await _handle_list(
            store=store,
            arguments={"limit": 5, "output_mode": "full", "content_max_length": "big"},
        )
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_content_max_length_zero_returns_error(self, store) -> None:
        result = await _handle_list(
            store=store,
            arguments={"limit": 5, "output_mode": "full", "content_max_length": 0},
        )
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_total_count_present_in_response(self, populated_store) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"limit": 2},
        )
        data = parse_mcp_response(result)
        assert "total_count" in data
        assert data["count"] == 2
        assert data["total_count"] == 5  # populated_store has 5 entries total

    async def test_total_count_with_filter(self, populated_store) -> None:
        result = await _handle_list(
            store=populated_store,
            arguments={"limit": 100, "entry_type": "feed"},
        )
        data = parse_mcp_response(result)
        assert data["count"] == 3  # 3 feed entries in populated_store
        assert data["total_count"] == 3

    async def test_total_count_empty_result(self, store) -> None:
        result = await _handle_list(
            store=store,
            arguments={"limit": 10, "entry_type": "feed"},
        )
        data = parse_mcp_response(result)
        assert data["total_count"] == 0
        assert data["count"] == 0

    # ------------------------------------------------------------------
    # Issue #311 — summary-mode shape and content_preview truncation
    # ------------------------------------------------------------------

    async def test_summary_content_preview_truncated_with_ellipsis(self, store) -> None:
        long = "A" * 500
        await store.store(make_entry(content=long))
        result = await _handle_list(store=store, arguments={"limit": 5})
        data = parse_mcp_response(result)
        assert data["output_mode"] == "summary"
        assert len(data["entries"]) == 1
        preview = data["entries"][0]["content_preview"]
        # 200 character preview + single ellipsis glyph.
        assert preview.endswith("…")
        assert len(preview) == 201
        assert preview[:200] == "A" * 200

    async def test_summary_content_preview_not_truncated_for_short_content(self, store) -> None:
        await store.store(make_entry(content="short body"))
        result = await _handle_list(store=store, arguments={"limit": 5})
        data = parse_mcp_response(result)
        preview = data["entries"][0]["content_preview"]
        assert preview == "short body"
        assert not preview.endswith("…")

    async def test_summary_title_derived_from_first_line(self, store) -> None:
        await store.store(make_entry(content="My Heading\n\nBody goes here."))
        result = await _handle_list(store=store, arguments={"limit": 5})
        data = parse_mcp_response(result)
        assert data["entries"][0]["title"] == "My Heading"

    async def test_summary_title_uses_metadata_title_when_present(self, store) -> None:
        await store.store(
            make_entry(
                content="Body line one\nBody line two",
                metadata={"title": "Explicit Title"},
            )
        )
        result = await _handle_list(store=store, arguments={"limit": 5})
        data = parse_mcp_response(result)
        assert data["entries"][0]["title"] == "Explicit Title"

    async def test_full_mode_still_available_via_explicit_flag(self, store) -> None:
        body = "Full body content that must round-trip verbatim."
        await store.store(make_entry(content=body))
        result = await _handle_list(
            store=store,
            arguments={"limit": 5, "output_mode": "full"},
        )
        data = parse_mcp_response(result)
        assert data["output_mode"] == "full"
        assert data["entries"][0]["content"] == body


# ---------------------------------------------------------------------------
# Integration tests: count_entries store method
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCountEntries:
    async def test_count_all(self, populated_store) -> None:
        count = await populated_store.count_entries(filters=None)
        assert count == 5  # populated_store fixture has 5 entries

    async def test_count_with_type_filter(self, populated_store) -> None:
        count = await populated_store.count_entries(filters={"entry_type": "feed"})
        assert count == 3  # 3 feed entries in populated_store

    async def test_count_empty_store(self, store) -> None:
        count = await store.count_entries(filters=None)
        assert count == 0


# ---------------------------------------------------------------------------
# Integration tests: distillery_aggregate
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAggregate:
    async def test_aggregate_by_entry_type(self, populated_store) -> None:
        result = await _handle_aggregate(
            store=populated_store,
            arguments={"group_by": "entry_type", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert data["group_by"] == "entry_type"
        assert "groups" in data
        assert "total_entries" in data
        assert "total_groups" in data

        by_type = {g["value"]: g["count"] for g in data["groups"]}
        assert by_type.get("feed") == 3
        assert by_type.get("inbox") == 1
        assert by_type.get("session") == 1
        assert data["total_entries"] == 5
        assert data["total_groups"] == 3

    async def test_aggregate_by_metadata_source_url(self, populated_store) -> None:
        result = await _handle_aggregate(
            store=populated_store,
            arguments={"group_by": "metadata.source_url", "limit": 50},
        )
        data = parse_mcp_response(result)
        by_url = {g["value"]: g["count"] for g in data["groups"]}
        assert by_url.get("https://github.com/org/repo") == 2
        assert by_url.get("https://example.com/rss") == 1
        # Entries with no source_url have value None
        assert data["total_groups"] >= 2

    async def test_aggregate_with_entry_type_filter(self, populated_store) -> None:
        result = await _handle_aggregate(
            store=populated_store,
            arguments={
                "group_by": "metadata.source_url",
                "entry_type": "feed",
                "limit": 50,
            },
        )
        data = parse_mcp_response(result)
        assert data["total_entries"] == 3

    async def test_aggregate_invalid_group_by_returns_error(self, populated_store) -> None:
        result = await _handle_aggregate(
            store=populated_store,
            arguments={"group_by": "nonexistent_field", "limit": 50},
        )
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "group_by" in data["message"]

    async def test_aggregate_missing_group_by_returns_error(self, populated_store) -> None:
        result = await _handle_aggregate(
            store=populated_store,
            arguments={"limit": 50},
        )
        data = parse_mcp_response(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_aggregate_sorted_by_count_desc(self, populated_store) -> None:
        result = await _handle_aggregate(
            store=populated_store,
            arguments={"group_by": "entry_type", "limit": 50},
        )
        data = parse_mcp_response(result)
        counts = [g["count"] for g in data["groups"]]
        assert counts == sorted(counts, reverse=True)

    async def test_aggregate_limit_respected(self, populated_store) -> None:
        result = await _handle_aggregate(
            store=populated_store,
            arguments={"group_by": "entry_type", "limit": 2},
        )
        data = parse_mcp_response(result)
        assert len(data["groups"]) <= 2

    async def test_aggregate_by_author(self, populated_store) -> None:
        result = await _handle_aggregate(
            store=populated_store,
            arguments={"group_by": "author", "limit": 50},
        )
        data = parse_mcp_response(result)
        by_author = {g["value"]: g["count"] for g in data["groups"]}
        assert by_author.get("alice") == 3
        assert by_author.get("bob") == 2
