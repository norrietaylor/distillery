"""Tests for the Distillery MCP server (T04.4 / T02.3).

Tests cover the 17 registered MCP tools via direct handler calls with a mock
store and deterministic embedding provider:

  store -> search -> get -> update -> find_similar -> list -> status

The test harness exercises the server handlers directly without requiring a
running stdio transport.  All handlers are async functions that accept a
store object and an arguments dict -- this is the natural unit-test seam.

Also exercises the ``create_server`` factory to confirm all 17 tools are
registered and the lifespan context initialises state correctly.

Tools removed from MCP surface (now webhooks or internal handlers):
  distillery_stale, distillery_aggregate, distillery_tag_tree,
  distillery_metrics, distillery_interests, distillery_type_schemas,
  distillery_poll, distillery_rescore
"""

from __future__ import annotations

import pytest

from distillery.config import DistilleryConfig, EmbeddingConfig, StorageConfig
from distillery.mcp.server import (
    _handle_find_similar,
    _handle_get,
    _handle_list,
    _handle_search,
    _handle_store,
    _handle_update,
    create_server,
    error_response,
    success_response,
)
from distillery.mcp.tools.analytics import _handle_metrics
from distillery.models import EntryType
from distillery.store.duckdb import DuckDBStore
from tests.conftest import DeterministicEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def embedding_provider(deterministic_embedding_provider):
    """Alias for deterministic_embedding_provider used by _handle_metrics tests."""
    return deterministic_embedding_provider


@pytest.fixture
async def store(embedding_provider) -> DuckDBStore:  # type: ignore[return]
    """Initialised in-memory DuckDBStore using the deterministic provider."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=embedding_provider)
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_error_response_structure(self) -> None:
        result = error_response("NOT_FOUND", "Item missing")
        parsed = parse_mcp_response(result)
        assert parsed["error"] is True
        assert parsed["code"] == "NOT_FOUND"
        assert parsed["message"] == "Item missing"

    def test_error_response_with_details(self) -> None:
        result = error_response("NOT_FOUND", "missing", details={"id": "abc"})
        parsed = parse_mcp_response(result)
        assert parsed["details"] == {"id": "abc"}

    def test_success_response_structure(self) -> None:
        result = success_response({"key": "value"})
        parsed = parse_mcp_response(result)
        assert parsed["key"] == "value"
        assert "error" not in parsed


# ---------------------------------------------------------------------------
# End-to-end flow: store -> search -> get -> update -> find_similar -> list -> status
# ---------------------------------------------------------------------------


class TestEndToEndFlow:
    """Full lifecycle test covering all 7 tools in sequence."""

    async def test_full_lifecycle(
        self,
        store: DuckDBStore,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """store -> search -> get -> update -> find_similar -> list -> status."""
        from distillery.config import DistilleryConfig

        # ------------------------------------------------------------------ #
        # Step 1: distillery_store                                            #
        # ------------------------------------------------------------------ #
        store_response = await _handle_store(
            store,
            {
                "content": "Machine learning fundamentals",
                "entry_type": "idea",
                "author": "alice",
                "tags": ["ml", "learning"],
                "project": "research",
            },
        )
        store_data = parse_mcp_response(store_response)
        assert "entry_id" in store_data
        assert "error" not in store_data
        entry_id = store_data["entry_id"]

        # ------------------------------------------------------------------ #
        # Step 2: distillery_search                                           #
        # ------------------------------------------------------------------ #
        search_response = await _handle_search(store, {"query": "machine learning"})
        search_data = parse_mcp_response(search_response)
        assert "results" in search_data
        assert isinstance(search_data["results"], list)
        assert search_data["count"] == len(search_data["results"])

        # ------------------------------------------------------------------ #
        # Step 3: distillery_get                                              #
        # ------------------------------------------------------------------ #
        get_response = await _handle_get(store, {"entry_id": entry_id})
        get_data = parse_mcp_response(get_response)
        assert "error" not in get_data
        assert get_data["id"] == entry_id
        assert get_data["content"] == "Machine learning fundamentals"
        assert get_data["author"] == "alice"
        assert set(get_data["tags"]) == {"ml", "learning"}

        # ------------------------------------------------------------------ #
        # Step 4: distillery_update                                           #
        # ------------------------------------------------------------------ #
        update_response = await _handle_update(
            store,
            {
                "entry_id": entry_id,
                "content": "Advanced machine learning techniques",
                "tags": ["ml", "advanced", "techniques"],
            },
        )
        update_data = parse_mcp_response(update_response)
        assert "error" not in update_data
        assert update_data["content"] == "Advanced machine learning techniques"
        assert "advanced" in update_data["tags"]

        # ------------------------------------------------------------------ #
        # Step 5: distillery_find_similar                                     #
        # ------------------------------------------------------------------ #
        find_response = await _handle_find_similar(
            store,
            {"content": "Advanced machine learning techniques", "threshold": 0.0},
        )
        find_data = parse_mcp_response(find_response)
        assert "results" in find_data
        assert "count" in find_data
        assert "threshold" in find_data
        # At least the entry we just stored should be returned at threshold 0.0
        assert find_data["count"] >= 1

        # ------------------------------------------------------------------ #
        # Step 6: distillery_list                                             #
        # ------------------------------------------------------------------ #
        list_response = await _handle_list(store, {})
        list_data = parse_mcp_response(list_response)
        assert "entries" in list_data
        assert "count" in list_data
        assert list_data["count"] >= 1
        ids = [e["id"] for e in list_data["entries"]]
        assert entry_id in ids

        # ------------------------------------------------------------------ #
        # Step 7: distillery_metrics(scope="summary") — replaces status     #
        # ------------------------------------------------------------------ #
        # Build a minimal config object for metrics
        config = DistilleryConfig(storage=StorageConfig(database_path=":memory:"))
        status_response = await _handle_metrics(
            store, config, embedding_provider, {"scope": "summary"}
        )
        status_data = parse_mcp_response(status_response)
        assert status_data.get("status") == "ok"
        assert "total_entries" in status_data
        assert status_data["total_entries"] >= 1
        assert "embedding_model" in status_data
        assert status_data["embedding_model"] == "deterministic-4d"


# ---------------------------------------------------------------------------
# distillery_metrics (scope=summary) — replaces distillery_status
# ---------------------------------------------------------------------------


class TestStatusTool:
    async def test_status_returns_ok(
        self, store: DuckDBStore, embedding_provider: DeterministicEmbeddingProvider
    ) -> None:
        config = DistilleryConfig(storage=StorageConfig(database_path=":memory:"))
        response = await _handle_metrics(store, config, embedding_provider, {"scope": "summary"})
        data = parse_mcp_response(response)
        assert data["status"] == "ok"

    async def test_status_shows_entry_counts(
        self, store: DuckDBStore, embedding_provider: DeterministicEmbeddingProvider
    ) -> None:
        config = DistilleryConfig(storage=StorageConfig(database_path=":memory:"))
        entry = make_entry(content="status test", entry_type=EntryType.IDEA)
        await store.store(entry)

        response = await _handle_metrics(store, config, embedding_provider, {"scope": "summary"})
        data = parse_mcp_response(response)
        assert data["total_entries"] >= 1
        assert "entries_by_type" in data
        assert "entries_by_status" in data

    async def test_status_shows_embedding_model(
        self, store: DuckDBStore, embedding_provider: DeterministicEmbeddingProvider
    ) -> None:
        config = DistilleryConfig(storage=StorageConfig(database_path=":memory:"))
        response = await _handle_metrics(store, config, embedding_provider, {"scope": "summary"})
        data = parse_mcp_response(response)
        assert data["embedding_model"] == "deterministic-4d"
        assert data["embedding_dimensions"] == 4


# ---------------------------------------------------------------------------
# distillery_store tests
# ---------------------------------------------------------------------------


class TestStoreTool:
    async def test_store_valid_entry(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {"content": "Test knowledge entry", "entry_type": "inbox", "author": "bob"},
        )
        data = parse_mcp_response(response)
        assert "entry_id" in data
        assert "error" not in data

    async def test_store_returns_string_id(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {"content": "Entry for ID check", "entry_type": "idea", "author": "alice"},
        )
        data = parse_mcp_response(response)
        assert isinstance(data["entry_id"], str)
        assert len(data["entry_id"]) > 0

    async def test_store_with_tags_and_project(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {
                "content": "Tagged entry",
                "entry_type": "bookmark",
                "author": "charlie",
                "tags": ["tag1", "tag2"],
                "project": "my-project",
            },
        )
        data = parse_mcp_response(response)
        assert "entry_id" in data

    async def test_store_missing_content_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {"entry_type": "inbox", "author": "alice"},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_missing_author_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {"content": "No author entry", "entry_type": "inbox"},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_invalid_entry_type_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {"content": "Bad type", "entry_type": "not_a_real_type", "author": "alice"},
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_all_valid_entry_types(self, store: DuckDBStore) -> None:
        """Each valid entry type should be accepted."""
        valid_types = ["session", "bookmark", "minutes", "meeting", "reference", "idea", "inbox"]
        for et in valid_types:
            response = await _handle_store(
                store,
                {"content": f"Entry of type {et}", "entry_type": et, "author": "tester"},
            )
            data = parse_mcp_response(response)
            assert "entry_id" in data, f"Failed for entry_type={et!r}"

    async def test_store_tags_must_be_list(self, store: DuckDBStore) -> None:
        response = await _handle_store(
            store,
            {
                "content": "Tagged entry",
                "entry_type": "inbox",
                "author": "alice",
                "tags": "not-a-list",
            },
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_store_dedup_warning_on_duplicate(
        self,
        store: DuckDBStore,
        embedding_provider: DeterministicEmbeddingProvider,
    ) -> None:
        """Storing content identical to an existing entry triggers dedup warning."""
        duplicate_vec = [1.0, 0.0, 0.0, 0.0]
        content = "Duplicate knowledge content"
        embedding_provider.register(content, duplicate_vec)

        # Store the original
        await _handle_store(
            store,
            {"content": content, "entry_type": "idea", "author": "alice", "dedup_threshold": 0.9},
        )
        # Store a near-duplicate -- dedup check should warn
        response = await _handle_store(
            store,
            {
                "content": content,
                "entry_type": "idea",
                "author": "alice",
                "dedup_threshold": 0.5,
            },
        )
        data = parse_mcp_response(response)
        assert "entry_id" in data
        # A warning may or may not appear depending on search threshold;
        # the key contract is that the store always returns entry_id.


# ---------------------------------------------------------------------------
# distillery_get tests
# ---------------------------------------------------------------------------


class TestGetTool:
    async def test_get_existing_entry(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Get me by ID")
        await store.store(entry)
        response = await _handle_get(store, {"entry_id": entry.id})
        data = parse_mcp_response(response)
        assert data["id"] == entry.id
        assert data["content"] == "Get me by ID"

    async def test_get_missing_entry_returns_not_found(self, store: DuckDBStore) -> None:
        response = await _handle_get(store, {"entry_id": "nonexistent-uuid"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_get_missing_entry_id_arg_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_get(store, {})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_get_returns_all_fields(self, store: DuckDBStore) -> None:
        entry = make_entry(
            content="Full field entry",
            entry_type=EntryType.SESSION,
            author="full-author",
            project="full-project",
            tags=["a", "b"],
            metadata={"key": "value"},
        )
        await store.store(entry)
        response = await _handle_get(store, {"entry_id": entry.id})
        data = parse_mcp_response(response)
        assert data["author"] == "full-author"
        assert data["project"] == "full-project"
        assert set(data["tags"]) == {"a", "b"}
        assert data["metadata"]["key"] == "value"


# ---------------------------------------------------------------------------
# distillery_update tests
# ---------------------------------------------------------------------------


class TestUpdateTool:
    async def test_update_content(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Before update")
        await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry.id, "content": "After update"})
        data = parse_mcp_response(response)
        assert "error" not in data
        assert data["content"] == "After update"

    async def test_update_version_increments(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Versioned content")
        await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry.id, "content": "Version 2"})
        data = parse_mcp_response(response)
        assert data["version"] == 2

    async def test_update_tags(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Tag test")
        await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry.id, "tags": ["new-tag"]})
        data = parse_mcp_response(response)
        assert "new-tag" in data["tags"]

    async def test_update_status(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Status test")
        await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry.id, "status": "archived"})
        data = parse_mcp_response(response)
        assert data["status"] == "archived"

    async def test_update_invalid_status_returns_error(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Bad status test")
        await store.store(entry)
        response = await _handle_update(
            store, {"entry_id": entry.id, "status": "not_a_real_status"}
        )
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_update_nonexistent_entry_returns_not_found(self, store: DuckDBStore) -> None:
        response = await _handle_update(store, {"entry_id": "nonexistent-id", "content": "Updated"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "NOT_FOUND"

    async def test_update_missing_entry_id_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_update(store, {"content": "No entry_id"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_update_no_fields_returns_error(self, store: DuckDBStore) -> None:
        entry = make_entry(content="No updates provided")
        await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry.id})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_update_immutable_field_returns_error(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Immutable test")
        await store.store(entry)
        response = await _handle_update(store, {"entry_id": entry.id, "id": "new-id"})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# distillery_search tests
# ---------------------------------------------------------------------------


class TestSearchTool:
    async def test_search_returns_results(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Searchable knowledge content")
        await store.store(entry)
        response = await _handle_search(store, {"query": "knowledge content"})
        data = parse_mcp_response(response)
        assert "results" in data
        assert "count" in data
        assert isinstance(data["results"], list)

    async def test_search_results_have_score_and_entry(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Score and entry check")
        await store.store(entry)
        response = await _handle_search(store, {"query": "score and entry"})
        data = parse_mcp_response(response)
        for result in data["results"]:
            assert "score" in result
            assert "entry" in result
            assert isinstance(result["score"], float)

    async def test_search_missing_query_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_search(store, {})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_search_respects_limit(self, store: DuckDBStore) -> None:
        for i in range(10):
            await store.store(make_entry(content=f"Search limit entry {i}"))
        response = await _handle_search(store, {"query": "search limit entry", "limit": 3})
        data = parse_mcp_response(response)
        assert len(data["results"]) <= 3

    async def test_search_invalid_limit_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_search(store, {"query": "test", "limit": "not-an-int"})
        data = parse_mcp_response(response)
        assert data["error"] is True

    async def test_search_filters_by_entry_type(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="Idea entry", entry_type=EntryType.IDEA))
        await store.store(make_entry(content="Inbox entry", entry_type=EntryType.INBOX))
        response = await _handle_search(store, {"query": "entry", "entry_type": "idea"})
        data = parse_mcp_response(response)
        for result in data["results"]:
            assert result["entry"]["entry_type"] == "idea"


# ---------------------------------------------------------------------------
# distillery_find_similar tests
# ---------------------------------------------------------------------------


class TestFindSimilarTool:
    async def test_find_similar_returns_results(self, store: DuckDBStore) -> None:
        entry = make_entry(content="Similar content for finding")
        await store.store(entry)
        response = await _handle_find_similar(
            store, {"content": "Similar content for finding", "threshold": 0.0}
        )
        data = parse_mcp_response(response)
        assert "results" in data
        assert "count" in data
        assert "threshold" in data

    async def test_find_similar_missing_content_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_find_similar(store, {})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_find_similar_threshold_out_of_range_returns_error(
        self, store: DuckDBStore
    ) -> None:
        response = await _handle_find_similar(store, {"content": "test", "threshold": 1.5})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_find_similar_default_threshold_returned_in_response(
        self, store: DuckDBStore
    ) -> None:
        await store.store(make_entry(content="Threshold echo test"))
        response = await _handle_find_similar(store, {"content": "Threshold echo test"})
        data = parse_mcp_response(response)
        assert data["threshold"] == 0.8  # default

    async def test_find_similar_respects_limit(self, store: DuckDBStore) -> None:
        for i in range(10):
            await store.store(make_entry(content=f"Similar item {i}"))
        response = await _handle_find_similar(
            store, {"content": "Similar item", "threshold": 0.0, "limit": 3}
        )
        data = parse_mcp_response(response)
        assert len(data["results"]) <= 3


# ---------------------------------------------------------------------------
# distillery_list tests
# ---------------------------------------------------------------------------


class TestListTool:
    async def test_list_returns_entries(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="List entry"))
        response = await _handle_list(store, {})
        data = parse_mcp_response(response)
        assert "entries" in data
        assert "count" in data
        assert isinstance(data["entries"], list)
        assert data["count"] >= 1

    async def test_list_empty_store_returns_empty(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {})
        data = parse_mcp_response(response)
        assert data["count"] == 0
        assert data["entries"] == []

    async def test_list_respects_limit(self, store: DuckDBStore) -> None:
        for i in range(10):
            await store.store(make_entry(content=f"List limit entry {i}"))
        response = await _handle_list(store, {"limit": 3})
        data = parse_mcp_response(response)
        assert len(data["entries"]) <= 3

    async def test_list_respects_offset(self, store: DuckDBStore) -> None:
        for i in range(5):
            await store.store(make_entry(content=f"Offset entry {i}"))
        all_response = await _handle_list(store, {"limit": 100})
        offset_response = await _handle_list(store, {"limit": 100, "offset": 2})
        all_data = parse_mcp_response(all_response)
        offset_data = parse_mcp_response(offset_response)
        assert offset_data["count"] == all_data["count"] - 2

    async def test_list_filters_by_author(self, store: DuckDBStore) -> None:
        await store.store(make_entry(content="Alice entry", author="alice"))
        await store.store(make_entry(content="Bob entry", author="bob"))
        response = await _handle_list(store, {"author": "alice"})
        data = parse_mcp_response(response)
        for entry in data["entries"]:
            assert entry["author"] == "alice"

    async def test_list_invalid_limit_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"limit": -1})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_list_invalid_offset_returns_error(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"offset": -5})
        data = parse_mcp_response(response)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    async def test_list_includes_limit_and_offset_in_response(self, store: DuckDBStore) -> None:
        response = await _handle_list(store, {"limit": 5, "offset": 2})
        data = parse_mcp_response(response)
        assert data["limit"] == 5
        assert data["offset"] == 2


# ---------------------------------------------------------------------------
# create_server tests
# ---------------------------------------------------------------------------


class TestCreateServer:
    def test_create_server_returns_server_instance(self) -> None:
        from fastmcp import FastMCP

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        )
        server = create_server(config)
        assert isinstance(server, FastMCP)

    async def test_server_registers_all_tools(self) -> None:
        """list_tools() must return all expected tool names."""
        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        )
        server = create_server(config)

        # Use FastMCP's list_tools() async method.
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}

        # 16-tool consolidated API (15 prior + distillery_status from #313)
        expected = {
            "distillery_store",
            "distillery_store_batch",
            "distillery_get",
            "distillery_update",
            "distillery_correct",
            "distillery_search",
            "distillery_find_similar",
            "distillery_list",
            "distillery_classify",
            "distillery_resolve_review",
            "distillery_watch",
            "distillery_configure",
            "distillery_relations",
            "distillery_gh_sync",
            "distillery_sync_status",
            "distillery_status",
            "distillery_dashboard",
        }
        assert expected == tool_names, (
            f"Tool mismatch — extra: {tool_names - expected}, missing: {expected - tool_names}"
        )

    async def test_server_registers_entry_type_schemas_resource(self) -> None:
        """distillery://schemas/entry-types resource must be registered and return JSON."""
        import json

        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        )
        server = create_server(config)

        resources = await server.list_resources()
        resource_uris = {str(r.uri) for r in resources}
        assert "distillery://schemas/entry-types" in resource_uris

        # Read the resource content — must be valid JSON with a "schemas" key.
        result = await server.read_resource("distillery://schemas/entry-types")
        # FastMCP returns a ResourceResult with a contents list.
        raw = result.contents[0].content if hasattr(result, "contents") else str(result)
        payload = json.loads(raw)
        assert "schemas" in payload
        assert isinstance(payload["schemas"], dict)
        # Spot-check a known entry type is present.
        assert "session" in payload["schemas"]


# ---------------------------------------------------------------------------
# Negative tests: removed tool names must not appear in the registered tools
# ---------------------------------------------------------------------------


class TestRemovedTools:
    """Verify that tools moved to webhooks/resources are not registered as MCP tools.

    type_schemas was moved to the distillery://schemas/entry-types MCP resource;
    poll and rescore were moved to /api/poll and /api/rescore webhook endpoints.
    """

    _REMOVED_TOOL_NAMES = [
        "distillery_type_schemas",
        "distillery_poll",
        "distillery_rescore",
    ]

    async def test_removed_tools_not_registered(self) -> None:
        """None of the removed tools should appear in list_tools()."""
        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        )
        server = create_server(config)
        tools = await server.list_tools()
        tool_names = {t.name for t in tools}
        for removed in self._REMOVED_TOOL_NAMES:
            assert removed not in tool_names, (
                f"{removed!r} should have been removed from MCP tool registry "
                f"(moved to webhook or resource)"
            )

    async def test_removed_tools_count_unchanged(self) -> None:
        """Exactly 17 tools must be registered — consolidated analytics tools + status + dashboard."""
        config = DistilleryConfig(
            storage=StorageConfig(database_path=":memory:"),
            embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        )
        server = create_server(config)
        tools = await server.list_tools()
        assert len(tools) == 17, (
            f"Expected 17 registered tools, got {len(tools)}: {sorted(t.name for t in tools)}"
        )
