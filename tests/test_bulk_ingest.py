"""Tests for bulk ingest: _handle_store_batch and distillery_watch sync_history."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from distillery.mcp.tools.crud import _handle_store_batch
from distillery.mcp.tools.feeds import _handle_watch
from tests.conftest import parse_mcp_response

# ---------------------------------------------------------------------------
# _handle_store_batch tests
# ---------------------------------------------------------------------------


def _make_mock_store(batch_ids: list[str] | None = None) -> AsyncMock:
    """Build a mock store with a store_batch method."""
    store = AsyncMock()
    store.connection = None  # budget check uses this
    if batch_ids is not None:
        store.store_batch.return_value = batch_ids
    return store


@pytest.mark.unit
async def test_handle_store_batch_success() -> None:
    """_handle_store_batch should build entries and call store.store_batch."""
    store = _make_mock_store(["id-1", "id-2"])
    result = await _handle_store_batch(
        store=store,
        arguments={
            "entries": [
                {"content": "First entry", "author": "alice", "entry_type": "inbox"},
                {"content": "Second entry", "author": "bob"},
            ],
        },
    )
    data = parse_mcp_response(result)
    assert data["entry_ids"] == ["id-1", "id-2"]
    assert data["count"] == 2
    store.store_batch.assert_awaited_once()
    # Verify the entries passed to store_batch
    call_args = store.store_batch.call_args[0][0]
    assert len(call_args) == 2
    assert call_args[0].content == "First entry"
    assert call_args[1].entry_type.value == "inbox"  # default


@pytest.mark.unit
async def test_handle_store_batch_project_default() -> None:
    """Project default should be applied to entries without per-entry project."""
    store = _make_mock_store(["id-1"])
    await _handle_store_batch(
        store=store,
        arguments={
            "entries": [{"content": "Entry", "author": "alice"}],
            "project": "my-project",
        },
    )
    call_args = store.store_batch.call_args[0][0]
    assert call_args[0].project == "my-project"


@pytest.mark.unit
async def test_handle_store_batch_per_entry_project_override() -> None:
    """Per-entry project should override the default."""
    store = _make_mock_store(["id-1"])
    await _handle_store_batch(
        store=store,
        arguments={
            "entries": [
                {"content": "Entry", "author": "alice", "project": "override"},
            ],
            "project": "default",
        },
    )
    call_args = store.store_batch.call_args[0][0]
    assert call_args[0].project == "override"


@pytest.mark.unit
async def test_handle_store_batch_missing_content() -> None:
    """Missing content should return INVALID_PARAMS."""
    store = _make_mock_store()
    result = await _handle_store_batch(
        store=store,
        arguments={"entries": [{"author": "alice"}]},
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "content" in data["message"]


@pytest.mark.unit
async def test_handle_store_batch_missing_author() -> None:
    """Missing author should return INVALID_PARAMS."""
    store = _make_mock_store()
    result = await _handle_store_batch(
        store=store,
        arguments={"entries": [{"content": "text"}]},
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "author" in data["message"]


@pytest.mark.unit
async def test_handle_store_batch_invalid_entry_type() -> None:
    """Invalid entry_type should return INVALID_PARAMS."""
    store = _make_mock_store()
    result = await _handle_store_batch(
        store=store,
        arguments={
            "entries": [
                {"content": "text", "author": "alice", "entry_type": "bogus"},
            ],
        },
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"
    assert "bogus" in data["message"]


@pytest.mark.unit
async def test_handle_store_batch_empty_list() -> None:
    """Empty entries list should return count=0 without calling store."""
    store = _make_mock_store()
    result = await _handle_store_batch(
        store=store,
        arguments={"entries": []},
    )
    data = parse_mcp_response(result)
    assert data["entry_ids"] == []
    assert data["count"] == 0
    store.store_batch.assert_not_awaited()


@pytest.mark.unit
async def test_handle_store_batch_not_a_list() -> None:
    """Non-list entries should return INVALID_PARAMS."""
    store = _make_mock_store()
    result = await _handle_store_batch(
        store=store,
        arguments={"entries": "not-a-list"},
    )
    data = parse_mcp_response(result)
    assert data["error"] is True
    assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# distillery_watch sync_history tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeSyncResult:
    repo: str
    created: int
    updated: int
    relations_created: int


@pytest.mark.unit
async def test_watch_add_sync_history() -> None:
    """watch add with sync_history=True should invoke GitHubSyncAdapter.sync()."""
    store = AsyncMock()
    store.add_feed_source.return_value = {"url": "owner/repo", "source_type": "github"}
    store.list_feed_sources.return_value = [{"url": "owner/repo", "source_type": "github"}]

    fake_result = _FakeSyncResult(repo="owner/repo", created=5, updated=2, relations_created=3)

    with patch(
        "distillery.feeds.github_sync.GitHubSyncAdapter",
        autospec=False,
    ) as mock_cls:
        mock_adapter = AsyncMock()
        mock_adapter.sync.return_value = fake_result
        mock_cls.return_value = mock_adapter

        result = await _handle_watch(
            store=store,
            arguments={
                "action": "add",
                "url": "owner/repo",
                "source_type": "github",
                "sync_history": True,
            },
        )

    data = parse_mcp_response(result)
    # With async background sync, the response contains a sync_job dict
    # (status=pending) and a message, not the final sync results.
    assert "sync_job" in data
    assert data["sync_job"]["status"] == "pending"
    assert "message" in data


@pytest.mark.unit
async def test_watch_add_without_sync_history() -> None:
    """watch add without sync_history should not invoke GitHubSyncAdapter."""
    store = AsyncMock()
    store.add_feed_source.return_value = {"url": "owner/repo", "source_type": "github"}
    store.list_feed_sources.return_value = [{"url": "owner/repo", "source_type": "github"}]

    result = await _handle_watch(
        store=store,
        arguments={
            "action": "add",
            "url": "owner/repo",
            "source_type": "github",
        },
    )
    data = parse_mcp_response(result)
    assert "sync" not in data
    assert "added" in data
