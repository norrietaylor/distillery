"""Tests for distillery_list / distillery_search default archived-exclusion.

Issue #317: by default ``distillery_list`` (and ``distillery_search``) must
hide archived entries. Explicit opt-in is required to see them, via either
``status="archived"`` (archived only), ``status="any"`` (all statuses), or
``include_archived=True`` (default set + archived).
"""

from __future__ import annotations

import pytest

from distillery.mcp.tools.crud import (
    _DEFAULT_VISIBLE_STATUSES,
    _apply_default_status_filter,
    _handle_list,
)
from distillery.mcp.tools.search import _handle_search
from distillery.models import EntryStatus
from tests.conftest import make_entry, parse_mcp_response


@pytest.fixture
async def status_mixed_store(store):  # type: ignore[return]
    """Store with an active, pending_review, and archived entry each."""
    active = make_entry(content="active entry content")
    pending = make_entry(content="pending entry content", status=EntryStatus.PENDING_REVIEW)
    archived = make_entry(content="archived entry content")

    await store.store(active)
    await store.store(pending)
    archived_id = await store.store(archived)
    # Soft-delete the third entry to mark it archived.
    await store.delete(archived_id)
    return store


# ---------------------------------------------------------------------------
# distillery_list
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListDefaultExcludesArchived:
    async def test_default_excludes_archived(self, status_mixed_store) -> None:
        result = await _handle_list(store=status_mixed_store, arguments={"limit": 50, "output_mode": "full"})
        data = parse_mcp_response(result)
        statuses = {e["status"] for e in data["entries"]}
        assert "archived" not in statuses
        assert statuses.issubset({"active", "pending_review"})
        assert data["count"] == 2
        assert data["total_count"] == 2

    async def test_explicit_status_archived_returns_only_archived(self, status_mixed_store) -> None:
        result = await _handle_list(
            store=status_mixed_store,
            arguments={"limit": 50, "status": "archived", "output_mode": "full"},
        )
        data = parse_mcp_response(result)
        assert data["count"] == 1
        assert data["entries"][0]["status"] == "archived"

    async def test_status_any_returns_all(self, status_mixed_store) -> None:
        result = await _handle_list(
            store=status_mixed_store,
            arguments={"limit": 50, "status": "any", "output_mode": "full"},
        )
        data = parse_mcp_response(result)
        statuses = {e["status"] for e in data["entries"]}
        assert statuses == {"active", "pending_review", "archived"}
        assert data["count"] == 3

    async def test_include_archived_returns_all(self, status_mixed_store) -> None:
        result = await _handle_list(
            store=status_mixed_store,
            arguments={"limit": 50, "include_archived": True, "output_mode": "full"},
        )
        data = parse_mcp_response(result)
        statuses = {e["status"] for e in data["entries"]}
        assert statuses == {"active", "pending_review", "archived"}
        assert data["count"] == 3

    async def test_explicit_status_active_excludes_others(self, status_mixed_store) -> None:
        result = await _handle_list(
            store=status_mixed_store,
            arguments={"limit": 50, "status": "active", "output_mode": "full"},
        )
        data = parse_mcp_response(result)
        assert data["count"] == 1
        assert data["entries"][0]["status"] == "active"

    async def test_review_mode_overrides_default(self, status_mixed_store) -> None:
        # review mode filters to pending_review and must not be overridden by
        # the default archived-exclusion logic.
        result = await _handle_list(
            store=status_mixed_store,
            arguments={"limit": 50, "output_mode": "review"},
        )
        data = parse_mcp_response(result)
        assert data["count"] == 1
        assert data["entries"][0]["entry_type"]  # review payload shape

    async def test_include_archived_invalid_type(self, status_mixed_store) -> None:
        result = await _handle_list(
            store=status_mixed_store,
            arguments={"limit": 10, "include_archived": "yes"},
        )
        data = parse_mcp_response(result)
        assert data.get("error") is True
        assert data.get("code") == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# _apply_default_status_filter helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApplyDefaultStatusFilter:
    def test_empty_filters_gets_default(self) -> None:
        out = _apply_default_status_filter(None, {})
        assert isinstance(out, dict)
        assert out["status"] == list(_DEFAULT_VISIBLE_STATUSES)

    def test_explicit_status_preserved(self) -> None:
        out = _apply_default_status_filter({"status": "archived"}, {})
        assert out == {"status": "archived"}

    def test_status_any_strips_key(self) -> None:
        out = _apply_default_status_filter({"status": "any"}, {})
        # Expect filters to end up without a status key (caller includes all).
        assert out is None or "status" not in out

    def test_status_any_with_other_filter_strips_only_status(self) -> None:
        out = _apply_default_status_filter({"status": "any", "author": "x"}, {})
        assert isinstance(out, dict)
        assert out == {"author": "x"}

    def test_include_archived_skips_default(self) -> None:
        out = _apply_default_status_filter(None, {"include_archived": True})
        assert out is None or "status" not in out

    def test_include_archived_invalid_returns_error_response(self) -> None:
        out = _apply_default_status_filter(None, {"include_archived": "yes"})
        # Error responses are lists of TextContent.
        assert isinstance(out, list)


# ---------------------------------------------------------------------------
# distillery_search
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSearchDefaultExcludesArchived:
    async def test_default_search_excludes_archived(self, status_mixed_store) -> None:
        result = await _handle_search(
            store=status_mixed_store,
            arguments={"query": "entry content", "limit": 50},
        )
        data = parse_mcp_response(result)
        statuses = {r["entry"]["status"] for r in data["results"]}
        assert "archived" not in statuses

    async def test_search_status_any_includes_archived(self, status_mixed_store) -> None:
        result = await _handle_search(
            store=status_mixed_store,
            arguments={"query": "entry content", "limit": 50, "status": "any"},
        )
        data = parse_mcp_response(result)
        statuses = {r["entry"]["status"] for r in data["results"]}
        assert "archived" in statuses

    async def test_search_include_archived_flag(self, status_mixed_store) -> None:
        result = await _handle_search(
            store=status_mixed_store,
            arguments={
                "query": "entry content",
                "limit": 50,
                "include_archived": True,
            },
        )
        data = parse_mcp_response(result)
        statuses = {r["entry"]["status"] for r in data["results"]}
        assert "archived" in statuses

    async def test_search_status_archived_returns_only_archived(self, status_mixed_store) -> None:
        result = await _handle_search(
            store=status_mixed_store,
            arguments={
                "query": "entry content",
                "limit": 50,
                "status": "archived",
            },
        )
        data = parse_mcp_response(result)
        statuses = {r["entry"]["status"] for r in data["results"]}
        assert statuses == {"archived"}
