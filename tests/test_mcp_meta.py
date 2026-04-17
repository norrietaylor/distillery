"""Unit tests for the ``distillery_status`` MCP tool handler (issue #313)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from distillery import __version__
from distillery.config import (
    DistilleryConfig,
    EmbeddingConfig,
    StorageConfig,
)
from distillery.mcp.tools.meta import _handle_status
from distillery.store.duckdb import DuckDBStore

pytestmark = pytest.mark.unit


def _parse(result: list[Any]) -> dict[str, Any]:
    """Parse the JSON payload from a single-item MCP TextContent list."""
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


class _FakeEmbeddingProvider:
    """Minimal stand-in with a ``model_name`` attribute."""

    model_name = "fake-embed-v1"
    dimensions = 4


@pytest.fixture
async def store(mock_embedding_provider):  # type: ignore[no-untyped-def]
    """Initialised in-memory DuckDBStore."""
    s = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def config() -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
    )


class TestDistilleryStatus:
    """Verify the ``distillery_status`` payload shape and basic semantics."""

    async def test_returns_expected_top_level_keys(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        """The response must expose the keys the /setup skill depends on."""
        result = await _handle_status(
            store=store,
            config=config,
            embedding_provider=_FakeEmbeddingProvider(),
            tool_count=16,
            transport="stdio",
            started_at=datetime.now(UTC) - timedelta(seconds=5),
        )
        data = _parse(result)

        # Required top-level keys.
        for key in (
            "status",
            "version",
            "transport",
            "tool_count",
            "store",
            "embedding_provider",
            "last_feed_poll",
        ):
            assert key in data, f"missing top-level key: {key!r}"

        # Shape / type assertions (no hard-coded counts for entries/sources).
        assert data["status"] == "ok"
        assert data["version"] == __version__
        assert data["transport"] == "stdio"
        assert isinstance(data["tool_count"], int)
        assert data["tool_count"] >= 1

        assert isinstance(data["store"], dict)
        assert "entry_count" in data["store"]
        assert "db_size_bytes" in data["store"]
        assert isinstance(data["store"]["entry_count"], int)
        assert data["store"]["entry_count"] >= 0

        assert isinstance(data["embedding_provider"], str)
        assert data["embedding_provider"]  # non-empty

        assert isinstance(data["last_feed_poll"], dict)
        assert "source_count" in data["last_feed_poll"]
        assert "last_poll_at" in data["last_feed_poll"]
        assert isinstance(data["last_feed_poll"]["source_count"], int)
        assert data["last_feed_poll"]["source_count"] >= 0

        # Uptime should be reported when started_at was passed.
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0

    async def test_unknown_transport_when_not_provided(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        """Missing transport info should surface as 'unknown'."""
        result = await _handle_status(
            store=store,
            config=config,
            embedding_provider=_FakeEmbeddingProvider(),
            tool_count=16,
            transport=None,
            started_at=None,
        )
        data = _parse(result)
        assert data["transport"] == "unknown"
        # uptime_seconds omitted when started_at is None.
        assert "uptime_seconds" not in data

    async def test_http_transport_is_reported(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        result = await _handle_status(
            store=store,
            config=config,
            embedding_provider=_FakeEmbeddingProvider(),
            tool_count=16,
            transport="http",
            started_at=None,
        )
        data = _parse(result)
        assert data["transport"] == "http"

    async def test_embedding_provider_falls_back_to_class_name(
        self,
        store: DuckDBStore,
        config: DistilleryConfig,
    ) -> None:
        """When the provider lacks ``model_name``, the class name is used."""

        class _Nameless:
            pass

        result = await _handle_status(
            store=store,
            config=config,
            embedding_provider=_Nameless(),
            tool_count=1,
            transport="stdio",
            started_at=None,
        )
        data = _parse(result)
        assert data["embedding_provider"] == "_Nameless"


class TestDistilleryStatusRegistration:
    """The tool must be registered alongside the existing 15 tools."""

    async def test_distillery_status_registered(self) -> None:
        from distillery.mcp.server import create_server

        server = create_server(
            DistilleryConfig(
                storage=StorageConfig(database_path=":memory:"),
                embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
            )
        )
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert "distillery_status" in names
