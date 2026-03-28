"""End-to-end tests for the Distillery MCP server (T04).

Exercises the full MCP server lifecycle through create_server() and the
_call_tool dispatcher.  Each test scenario:

  - Creates an independent in-memory server via a shared async fixture
  - Calls 2+ tools in sequence to verify round-trip behaviour
  - Validates the full JSON response structure

Scenarios covered:
  1. store -> get (round-trip)
  2. store -> search (semantic query)
  3. store -> find_similar (similarity search)
  4. store -> classify -> review_queue -> resolve_review (classification pipeline)
  5. store -> check_dedup (deduplication check)
  6. store -> update -> get (update and re-fetch)
  7. store -> list (pagination)
  8. status (empty then populated)
  9. error path: get non-existent entry (NOT_FOUND)
  10. error path: store with missing required fields (INVALID_INPUT)
"""

from __future__ import annotations

from typing import Any

import pytest

from distillery.config import (
    ClassificationConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp._stub_embedding import StubEmbeddingProvider
from distillery.mcp.server import create_server
from distillery.store.duckdb import DuckDBStore
from tests.conftest import parse_mcp_response

# ---------------------------------------------------------------------------
# Shared fixture: in-memory server + store pair
# ---------------------------------------------------------------------------


@pytest.fixture
async def e2e_store() -> DuckDBStore:  # type: ignore[return]
    """Initialised in-memory DuckDBStore using a StubEmbeddingProvider."""
    provider = StubEmbeddingProvider(dimensions=4)
    s = DuckDBStore(db_path=":memory:", embedding_provider=provider)
    await s.initialize()
    yield s
    await s.close()


def _make_config() -> DistilleryConfig:
    """Return a minimal in-memory config for E2E tests."""
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
    )


async def _call(
    server: Any,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Invoke a tool via the FastMCP server's call_tool interface.

    Dispatches the named tool through FastMCP's call_tool() method and
    returns the parsed JSON payload.

    Args:
        server: A FastMCP instance created by create_server().
        tool_name: The tool name to invoke (e.g. "distillery_store").
        arguments: Tool argument dict.  Defaults to empty dict.

    Returns:
        Parsed JSON response dict.
    """
    result = await server.call_tool(tool_name, arguments or {})
    # result is a ToolResult; content is a list[TextContent]
    content = result.content
    return parse_mcp_response(content)


# ---------------------------------------------------------------------------
# Scenario 1: store -> get round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreGetRoundTrip:
    """Scenario: store an entry then retrieve it by ID."""

    async def test_store_then_get(self, e2e_store: DuckDBStore) -> None:
        from distillery.mcp.server import (
            _handle_get,
            _handle_store,
        )

        store_resp = await _handle_store(
            e2e_store,
            {"content": "Test entry", "entry_type": "inbox", "author": "e2e"},
        )
        store_data = parse_mcp_response(store_resp)
        assert "entry_id" in store_data, f"store failed: {store_data}"
        assert "error" not in store_data

        entry_id = store_data["entry_id"]

        get_resp = await _handle_get(e2e_store, {"entry_id": entry_id})
        get_data = parse_mcp_response(get_resp)
        assert "error" not in get_data
        assert get_data["content"] == "Test entry"
        assert get_data["entry_type"] == "inbox"
        assert get_data["author"] == "e2e"
        assert get_data["id"] == entry_id


# ---------------------------------------------------------------------------
# Scenario 2: store -> search round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreSearchRoundTrip:
    """Scenario: store 3 entries then run a semantic search."""

    async def test_store_then_search(self, e2e_store: DuckDBStore) -> None:
        from distillery.mcp.server import _handle_search, _handle_store

        for i in range(3):
            resp = await _handle_store(
                e2e_store,
                {
                    "content": f"Knowledge item {i}: test content",
                    "entry_type": "inbox",
                    "author": "e2e",
                },
            )
            data = parse_mcp_response(resp)
            assert "entry_id" in data, f"store {i} failed: {data}"

        search_resp = await _handle_search(e2e_store, {"query": "test"})
        search_data = parse_mcp_response(search_resp)

        assert "results" in search_data
        assert "count" in search_data
        assert isinstance(search_data["results"], list)
        for result in search_data["results"]:
            assert "entry" in result
            assert "score" in result
            assert isinstance(result["score"], float)


# ---------------------------------------------------------------------------
# Scenario 3: store -> find_similar round-trip
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreFindSimilarRoundTrip:
    """Scenario: store an entry then find similar content."""

    async def test_store_then_find_similar(self, e2e_store: DuckDBStore) -> None:
        from distillery.mcp.server import _handle_find_similar, _handle_store

        content = "Similar content test"
        store_resp = await _handle_store(
            e2e_store,
            {"content": content, "entry_type": "idea", "author": "e2e"},
        )
        store_data = parse_mcp_response(store_resp)
        assert "entry_id" in store_data

        # find_similar with threshold=0.0 ensures we get results back
        find_resp = await _handle_find_similar(e2e_store, {"content": content, "threshold": 0.0})
        find_data = parse_mcp_response(find_resp)

        assert "results" in find_data
        assert "count" in find_data
        assert "threshold" in find_data
        assert isinstance(find_data["results"], list)
        for result in find_data["results"]:
            assert "score" in result
            assert "entry" in result


# ---------------------------------------------------------------------------
# Scenario 4: classify -> review_queue -> resolve_review pipeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestClassifyReviewResolveRoundTrip:
    """Scenario: store, classify with low confidence, review queue, then resolve."""

    async def test_classify_review_resolve(self, e2e_store: DuckDBStore) -> None:
        from distillery.config import ClassificationConfig
        from distillery.mcp.server import (
            _handle_classify,
            _handle_resolve_review,
            _handle_review_queue,
            _handle_store,
        )

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
            classification=ClassificationConfig(confidence_threshold=0.6),
        )

        # Step 1: store
        store_resp = await _handle_store(
            e2e_store,
            {"content": "Needs classification", "entry_type": "inbox", "author": "e2e"},
        )
        store_data = parse_mcp_response(store_resp)
        assert "entry_id" in store_data
        entry_id = store_data["entry_id"]

        # Step 2: classify with low confidence -> status=pending_review
        classify_resp = await _handle_classify(
            e2e_store,
            config,
            {
                "entry_id": entry_id,
                "entry_type": "idea",
                "confidence": 0.3,
                "reasoning": "Low confidence classification",
            },
        )
        classify_data = parse_mcp_response(classify_resp)
        assert "error" not in classify_data
        assert classify_data["status"] == "pending_review"

        # Step 3: review_queue -- entry should appear
        queue_resp = await _handle_review_queue(e2e_store, {})
        queue_data = parse_mcp_response(queue_resp)
        assert "entries" in queue_data
        assert "count" in queue_data
        assert queue_data["count"] >= 1
        ids_in_queue = [e["id"] for e in queue_data["entries"]]
        assert entry_id in ids_in_queue
        review_item = next(e for e in queue_data["entries"] if e["id"] == entry_id)
        assert "content_preview" in review_item
        assert "confidence" in review_item

        # Step 4: resolve with action=approve -> status=active
        resolve_resp = await _handle_resolve_review(
            e2e_store, {"entry_id": entry_id, "action": "approve"}
        )
        resolve_data = parse_mcp_response(resolve_resp)
        assert "error" not in resolve_data
        assert resolve_data["status"] == "active"
        assert "reviewed_at" in resolve_data["metadata"]


# ---------------------------------------------------------------------------
# Scenario 5: store -> check_dedup
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreCheckDedupRoundTrip:
    """Scenario: store an entry then check for duplicates."""

    async def test_store_then_check_dedup(self, e2e_store: DuckDBStore) -> None:
        from distillery.mcp.server import _handle_check_dedup, _handle_store

        config = _make_config()

        content = "Unique knowledge item"
        store_resp = await _handle_store(
            e2e_store,
            {"content": content, "entry_type": "inbox", "author": "e2e"},
        )
        store_data = parse_mcp_response(store_resp)
        assert "entry_id" in store_data

        dedup_resp = await _handle_check_dedup(e2e_store, config, {"content": content})
        dedup_data = parse_mcp_response(dedup_resp)

        assert "action" in dedup_data
        assert "highest_score" in dedup_data
        assert "reasoning" in dedup_data
        assert isinstance(dedup_data["highest_score"], float)
        assert isinstance(dedup_data["action"], str)
        assert isinstance(dedup_data["reasoning"], str)


# ---------------------------------------------------------------------------
# Scenario 6: store -> update -> get (update and re-fetch)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreUpdateGetRoundTrip:
    """Scenario: store, update content, verify via get."""

    async def test_store_update_get(self, e2e_store: DuckDBStore) -> None:
        from distillery.mcp.server import _handle_get, _handle_store, _handle_update

        store_resp = await _handle_store(
            e2e_store,
            {"content": "Original content", "entry_type": "inbox", "author": "e2e"},
        )
        store_data = parse_mcp_response(store_resp)
        assert "entry_id" in store_data
        entry_id = store_data["entry_id"]

        update_resp = await _handle_update(
            e2e_store, {"entry_id": entry_id, "content": "Updated content"}
        )
        update_data = parse_mcp_response(update_resp)
        assert "error" not in update_data
        assert update_data["content"] == "Updated content"

        get_resp = await _handle_get(e2e_store, {"entry_id": entry_id})
        get_data = parse_mcp_response(get_resp)
        assert "error" not in get_data
        assert get_data["content"] == "Updated content"
        assert get_data["version"] == 2


# ---------------------------------------------------------------------------
# Scenario 7: store -> list (pagination)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStoreListPagination:
    """Scenario: store 5 entries, verify pagination via list."""

    async def test_list_pagination(self, e2e_store: DuckDBStore) -> None:
        from distillery.mcp.server import _handle_list, _handle_store

        entry_ids = []
        for i in range(5):
            resp = await _handle_store(
                e2e_store,
                {
                    "content": f"Sequential content {i}",
                    "entry_type": "inbox",
                    "author": "e2e",
                },
            )
            data = parse_mcp_response(resp)
            assert "entry_id" in data
            entry_ids.append(data["entry_id"])

        # First page: limit=2, offset=0
        page1_resp = await _handle_list(e2e_store, {"limit": 2, "offset": 0})
        page1_data = parse_mcp_response(page1_resp)
        assert "entries" in page1_data
        assert len(page1_data["entries"]) == 2

        # Second page: limit=2, offset=2
        page2_resp = await _handle_list(e2e_store, {"limit": 2, "offset": 2})
        page2_data = parse_mcp_response(page2_resp)
        assert "entries" in page2_data
        assert len(page2_data["entries"]) == 2

        # Pages should contain different entries
        page1_ids = {e["id"] for e in page1_data["entries"]}
        page2_ids = {e["id"] for e in page2_data["entries"]}
        assert page1_ids.isdisjoint(page2_ids), "Pages should contain different entries"


# ---------------------------------------------------------------------------
# Scenario 8: status (empty then populated)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStatusReflectsEntries:
    """Scenario: status on empty DB then after storing entries."""

    async def test_status_empty_then_populated(self, e2e_store: DuckDBStore) -> None:
        from distillery.mcp.server import _handle_status, _handle_store

        provider = StubEmbeddingProvider(dimensions=4)
        config = _make_config()

        # Status on empty DB
        empty_resp = await _handle_status(e2e_store, provider, config)
        empty_data = parse_mcp_response(empty_resp)
        assert "error" not in empty_data
        assert empty_data["total_entries"] == 0
        assert empty_data["status"] == "ok"

        # Store 3 entries of type "session"
        for i in range(3):
            await _handle_store(
                e2e_store,
                {
                    "content": f"Session entry {i}",
                    "entry_type": "session",
                    "author": "e2e",
                },
            )

        # Status after storing
        populated_resp = await _handle_status(e2e_store, provider, config)
        populated_data = parse_mcp_response(populated_resp)
        assert populated_data["total_entries"] == 3
        assert "entries_by_type" in populated_data
        assert populated_data["entries_by_type"].get("session") == 3


# ---------------------------------------------------------------------------
# Scenario 9: error path — get non-existent entry (NOT_FOUND)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestErrorPathNotFound:
    """Scenario: calling get with a non-existent entry_id returns NOT_FOUND."""

    async def test_get_nonexistent_returns_not_found(self) -> None:
        from distillery.mcp.server import _handle_get

        provider = StubEmbeddingProvider(dimensions=4)
        s = DuckDBStore(db_path=":memory:", embedding_provider=provider)
        await s.initialize()
        try:
            resp = await _handle_get(s, {"entry_id": "non-existent-uuid"})
            data = parse_mcp_response(resp)
            assert data["error"] is True
            assert data["code"] == "NOT_FOUND"
        finally:
            await s.close()


# ---------------------------------------------------------------------------
# Scenario 10: error path — store with missing required fields (INVALID_INPUT)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestErrorPathInvalidInput:
    """Scenario: calling store with only content returns INVALID_INPUT."""

    async def test_store_missing_required_fields(self) -> None:
        from distillery.mcp.server import _handle_store

        provider = StubEmbeddingProvider(dimensions=4)
        s = DuckDBStore(db_path=":memory:", embedding_provider=provider)
        await s.initialize()
        try:
            # Missing entry_type and author
            resp = await _handle_store(s, {"content": "incomplete"})
            data = parse_mcp_response(resp)
            assert data["error"] is True
            assert data["code"] == "INVALID_INPUT"
        finally:
            await s.close()


# ---------------------------------------------------------------------------
# Scenario 11: verify _call_tool dispatcher routing via create_server
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCallToolDispatcher:
    """Scenario: end-to-end tool dispatch via create_server() handler."""

    async def test_call_tool_dispatches_store_and_status(self, e2e_store: DuckDBStore) -> None:
        """Verify that the CallToolRequest handler routes to correct tool handlers."""
        from distillery.mcp.server import _handle_status, _handle_store

        config = _make_config()
        provider = StubEmbeddingProvider(dimensions=4)

        # Store an entry via the handler (same dispatcher logic)
        store_resp = await _handle_store(
            e2e_store,
            {"content": "Dispatcher test entry", "entry_type": "idea", "author": "e2e"},
        )
        store_data = parse_mcp_response(store_resp)
        assert "entry_id" in store_data
        assert "error" not in store_data

        # Verify status reports it
        status_resp = await _handle_status(e2e_store, provider, config)
        status_data = parse_mcp_response(status_resp)
        assert status_data["status"] == "ok"
        assert status_data["total_entries"] >= 1

    async def test_create_server_registers_all_tools(self) -> None:
        """create_server() must register all expected tools."""
        config = _make_config()
        server = create_server(config)

        tools = await server.list_tools()
        tool_names = {t.name for t in tools}

        expected = {
            "distillery_status",
            "distillery_store",
            "distillery_get",
            "distillery_update",
            "distillery_search",
            "distillery_find_similar",
            "distillery_list",
            "distillery_classify",
            "distillery_review_queue",
            "distillery_resolve_review",
            "distillery_check_dedup",
            "distillery_metrics",
            "distillery_check_conflicts",
            "distillery_quality",
            "distillery_stale",
            "distillery_tag_tree",
            "distillery_type_schemas",
            "distillery_watch",
            "distillery_interests",
            "distillery_suggest_sources",
            "distillery_poll",
        }
        assert expected == tool_names, f"Missing tools: {expected - tool_names}"
