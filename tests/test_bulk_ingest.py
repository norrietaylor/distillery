"""Tests for bulk ingest: _handle_store_batch and distillery_watch sync_history."""

from __future__ import annotations

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
    """Missing content should surface as a per-item error (issue #364)."""
    store = _make_mock_store()
    result = await _handle_store_batch(
        store=store,
        arguments={"entries": [{"author": "alice"}]},
    )
    data = parse_mcp_response(result)
    assert "error" not in data or data["error"] is False
    assert data["count"] == 0
    item_err = data["results"][0]["error"]
    assert item_err["code"] == "INVALID_PARAMS"
    assert "content" in item_err["message"]


@pytest.mark.unit
async def test_handle_store_batch_missing_author() -> None:
    """Missing author should surface as a per-item error (issue #364)."""
    store = _make_mock_store()
    result = await _handle_store_batch(
        store=store,
        arguments={"entries": [{"content": "text"}]},
    )
    data = parse_mcp_response(result)
    assert "error" not in data or data["error"] is False
    assert data["count"] == 0
    item_err = data["results"][0]["error"]
    assert item_err["code"] == "INVALID_PARAMS"
    assert "author" in item_err["message"]


@pytest.mark.unit
async def test_handle_store_batch_invalid_entry_type() -> None:
    """Invalid entry_type for an only-item batch: top-level success, per-item error."""
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
    # Top-level is success (no ``error: true``) — per-item failures now
    # surface via the ``results`` array (issue #364).
    assert "error" not in data or data["error"] is False
    assert data["count"] == 0
    assert data["entry_ids"] == [None]
    assert len(data["results"]) == 1
    item_err = data["results"][0]["error"]
    assert item_err["code"] == "INVALID_PARAMS"
    assert "bogus" in item_err["message"]
    # store.store_batch is never awaited when no valid entries remain.
    store.store_batch.assert_not_awaited()


@pytest.mark.unit
async def test_handle_store_batch_entry_type_note_suggests_inbox() -> None:
    """Issue #345: bulk ingest also surfaces the 'note' -> 'inbox' suggestion."""
    store = _make_mock_store()
    result = await _handle_store_batch(
        store=store,
        arguments={
            "entries": [
                {"content": "text", "author": "alice", "entry_type": "note"},
            ],
        },
    )
    data = parse_mcp_response(result)
    # Per-item failure, not a top-level error (issue #364).
    assert "error" not in data or data["error"] is False
    assert data["count"] == 0
    item_err = data["results"][0]["error"]
    assert item_err["code"] == "INVALID_PARAMS"
    assert item_err["details"]["suggestion"] == "inbox"
    # The prefixed message keeps per-entry context.
    assert "entries[0]" in item_err["message"]


@pytest.mark.unit
async def test_handle_store_batch_partial_success_invalid_middle_item() -> None:
    """Issue #364: a batch of 3 with item 2 invalid should persist items 0 and 2.

    Items 0 and 2 are valid; item 1 has an invalid ``entry_type``.  The call
    should succeed at the top level, persist the two valid entries, and
    report the invalid item as a per-item failure with ``entry_id=None``.
    """
    store = _make_mock_store(["id-0", "id-2"])
    result = await _handle_store_batch(
        store=store,
        arguments={
            "entries": [
                {"content": "first", "author": "alice"},
                {"content": "second (bad)", "author": "bob", "entry_type": "bogus"},
                {"content": "third", "author": "carol"},
            ],
        },
    )
    data = parse_mcp_response(result)
    # Top level is a success response.
    assert "error" not in data or data["error"] is False
    assert data["count"] == 2
    # ``entry_ids`` preserves input order with ``None`` for the failed item.
    assert data["entry_ids"] == ["id-0", None, "id-2"]

    results = data["results"]
    assert len(results) == 3

    # Item 0: persisted successfully.
    assert results[0] == {"entry_id": "id-0", "persisted": True, "dedup_action": "stored"}

    # Item 1: validation failure surfaced per-item, not at the top level.
    assert results[1]["entry_id"] is None
    assert results[1]["persisted"] is False
    assert results[1]["error"]["code"] == "INVALID_PARAMS"
    assert "entries[1]" in results[1]["error"]["message"]
    assert "bogus" in results[1]["error"]["message"]

    # Item 2: persisted successfully.
    assert results[2] == {"entry_id": "id-2", "persisted": True, "dedup_action": "stored"}

    # store_batch was called with only the two valid entries (in input order).
    store.store_batch.assert_awaited_once()
    passed = store.store_batch.call_args[0][0]
    assert len(passed) == 2
    assert passed[0].content == "first"
    assert passed[1].content == "third"


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


@pytest.mark.unit
async def test_watch_add_sync_history() -> None:
    """watch add with sync_history=True should start a background sync job."""
    store = AsyncMock()
    store.add_feed_source.return_value = {"url": "owner/repo", "source_type": "github"}
    store.list_feed_sources.return_value = [{"url": "owner/repo", "source_type": "github"}]

    with patch(
        "distillery.feeds.github_sync.GitHubSyncAdapter",
        autospec=False,
    ) as mock_cls:
        mock_adapter = AsyncMock()
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
    # Verify GitHubSyncAdapter was instantiated — proves sync_history=True
    # actually started a background job rather than silently skipping it.
    mock_cls.assert_called_once()


@pytest.mark.unit
async def test_watch_add_without_sync_history() -> None:
    """watch add without sync_history should not invoke GitHubSyncAdapter."""
    store = AsyncMock()
    store.add_feed_source.return_value = {"url": "owner/repo", "source_type": "github"}
    store.list_feed_sources.return_value = [{"url": "owner/repo", "source_type": "github"}]

    with patch(
        "distillery.feeds.github_sync.GitHubSyncAdapter",
        autospec=False,
    ) as mock_cls:
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
    # Verify GitHubSyncAdapter was NOT instantiated when sync_history is omitted.
    mock_cls.assert_not_called()
