"""Tests for the distillery_context MCP tool.

Covers:
  - Context by project
  - Context by tags
  - Context with semantic query
  - Empty results
  - Limit respected
"""

from __future__ import annotations

import pytest

from distillery.config import (
    ClassificationConfig,
    DefaultsConfig,
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.tools.context import _handle_context
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider, make_entry, parse_mcp_response

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="mock-hash-4d", dimensions=4),
        classification=ClassificationConfig(confidence_threshold=0.6),
        defaults=DefaultsConfig(),
    )


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


@pytest.fixture
def config() -> DistilleryConfig:
    return _make_config()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContextByProject:
    """Filter context entries by project."""

    async def test_project_filter(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        e1 = make_entry(content="API refactor notes", project="api-refactor")
        e2 = make_entry(content="Billing service notes", project="billing")
        e3 = make_entry(content="More API work", project="api-refactor")
        await store.store(e1)
        await store.store(e2)
        await store.store(e3)

        result = await _handle_context(
            store=store,
            arguments={"project": "api-refactor"},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        assert data["count"] == 2
        ids = [e["id"] for e in data["entries"]]
        assert e1.id in ids
        assert e3.id in ids
        assert e2.id not in ids

    async def test_project_no_match(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        e1 = make_entry(content="Some entry", project="other")
        await store.store(e1)

        result = await _handle_context(
            store=store,
            arguments={"project": "nonexistent"},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert data["count"] == 0
        assert data["entries"] == []


class TestContextByTags:
    """Filter context entries by tags."""

    async def test_tag_filter(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        e1 = make_entry(content="Architecture decision", tags=["architecture"])
        e2 = make_entry(content="Bug fix notes", tags=["bugfix"])
        e3 = make_entry(content="Architecture review", tags=["architecture", "review"])
        await store.store(e1)
        await store.store(e2)
        await store.store(e3)

        result = await _handle_context(
            store=store,
            arguments={"tags": ["architecture"]},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        ids = [e["id"] for e in data["entries"]]
        assert e1.id in ids
        assert e3.id in ids
        assert e2.id not in ids


class TestContextWithQuery:
    """Semantic query should use search with project/tag filters."""

    async def test_query_with_project(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        e1 = make_entry(content="Caching strategy for API layer", project="api-refactor")
        e2 = make_entry(content="Caching strategy for billing", project="billing")
        await store.store(e1)
        await store.store(e2)

        result = await _handle_context(
            store=store,
            arguments={
                "query": "caching strategy",
                "project": "api-refactor",
            },
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        # All results should be from api-refactor project
        for entry in data["entries"]:
            assert entry["project"] == "api-refactor"
        # Should have relevance scores
        if data["entries"]:
            assert "relevance_score" in data["entries"][0]

    async def test_semantic_scope_requires_query(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        result = await _handle_context(
            store=store,
            arguments={"scope": "semantic"},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert data.get("error") is True
        assert "INVALID_PARAMS" in data["code"]


class TestEmptyResults:
    """Empty database or no matches returns empty list."""

    async def test_empty_database(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        result = await _handle_context(
            store=store,
            arguments={},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert "error" not in data
        assert data["count"] == 0
        assert data["entries"] == []

    async def test_no_match_with_filters(
        self, store: DuckDBStore, config: DistilleryConfig
    ) -> None:
        e1 = make_entry(content="Some entry", project="existing")
        await store.store(e1)

        result = await _handle_context(
            store=store,
            arguments={"project": "nonexistent", "tags": ["missing"]},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert data["count"] == 0


class TestLimitRespected:
    """Limit parameter should cap results."""

    async def test_limit_caps_results(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        for i in range(10):
            await store.store(make_entry(content=f"Entry {i}", project="proj"))

        result = await _handle_context(
            store=store,
            arguments={"project": "proj", "limit": 3},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert data["count"] <= 3

    async def test_default_limit_is_20(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        for i in range(25):
            await store.store(make_entry(content=f"Entry {i}", project="proj"))

        result = await _handle_context(
            store=store,
            arguments={"project": "proj"},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert data["count"] <= 20


class TestScopeValidation:
    """Invalid scope returns error."""

    async def test_invalid_scope(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        result = await _handle_context(
            store=store,
            arguments={"scope": "invalid"},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert data.get("error") is True
        assert "INVALID_PARAMS" in data["code"]


class TestResponseMetadata:
    """Response includes scope, project, tags, query metadata."""

    async def test_metadata_in_response(self, store: DuckDBStore, config: DistilleryConfig) -> None:
        result = await _handle_context(
            store=store,
            arguments={"project": "my-project", "tags": ["arch"], "scope": "tags"},
            cfg=config,
        )
        data = parse_mcp_response(result)
        assert data["scope"] == "tags"
        assert data["project"] == "my-project"
        assert data["tags"] == ["arch"]
        assert data["query"] is None
