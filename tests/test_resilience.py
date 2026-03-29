"""Tests for application resilience: VSS graceful degradation, retry logic, and /health endpoint.

Covers the scenarios in ``docs/specs/11-spec-production-deployment/application-resilience.feature``.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import duckdb
import pytest

from distillery.config import DistilleryConfig, StorageConfig
from distillery.store.duckdb import DuckDBStore
from tests.conftest import MockEmbeddingProvider, make_entry


def _make_config() -> DistilleryConfig:
    """Return a DistilleryConfig using an in-memory DuckDB database."""
    return DistilleryConfig(storage=StorageConfig(database_path=":memory:"))


def _make_no_vss_store(provider: MockEmbeddingProvider) -> DuckDBStore:
    """Create a DuckDBStore that will skip VSS setup."""
    store = DuckDBStore(db_path=":memory:", embedding_provider=provider)
    return store


async def _init_without_vss(store: DuckDBStore) -> None:
    """Initialize store with VSS forced to be unavailable."""

    def _no_vss(self: DuckDBStore, conn: duckdb.DuckDBPyConnection) -> None:
        """Simulate VSS failure by calling the real method wrapper logic."""
        self._vss_available = False
        import logging as _log

        _log.getLogger("distillery.store.duckdb").warning(
            "VSS extension unavailable (%s); falling back to brute-force search",
            "forced failure in test",
        )

    with patch.object(DuckDBStore, "_setup_vss", _no_vss):
        await store.initialize()


# ---------------------------------------------------------------------------
# VSS unavailable -- graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_vss_unavailable_graceful_degradation(
    mock_embedding_provider: MockEmbeddingProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Store initializes when VSS extension is forced to fail."""
    store = _make_no_vss_store(mock_embedding_provider)

    with caplog.at_level(logging.WARNING, logger="distillery.store.duckdb"):
        await _init_without_vss(store)

    assert store._initialized is True
    assert store.vss_available is False
    vss_warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "VSS" in r.message]
    assert len(vss_warnings) >= 1
    await store.close()


@pytest.mark.unit
async def test_hnsw_index_skipped_when_vss_unavailable(
    mock_embedding_provider: MockEmbeddingProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """HNSW index creation is skipped when VSS is unavailable."""
    store = _make_no_vss_store(mock_embedding_provider)

    with caplog.at_level(logging.WARNING, logger="distillery.store.duckdb"):
        await _init_without_vss(store)

    assert store.vss_available is False
    hnsw_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "HNSW index not created" in r.message
    ]
    assert len(hnsw_warnings) >= 1
    await store.close()


# ---------------------------------------------------------------------------
# Search / find_similar without HNSW index (brute-force)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_search_without_hnsw_index(
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Semantic search returns results without HNSW index (brute-force cosine)."""
    store = _make_no_vss_store(mock_embedding_provider)
    await _init_without_vss(store)

    # Store 3 entries.
    for i in range(3):
        await store.store(make_entry(content=f"entry content {i}"))

    results = await store.search(query="entry content 0", filters=None, limit=3)
    assert len(results) == 3
    # Results should be ordered by descending similarity.
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    await store.close()


@pytest.mark.unit
async def test_find_similar_without_hnsw_index(
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """find_similar returns results without HNSW index."""
    store = _make_no_vss_store(mock_embedding_provider)
    await _init_without_vss(store)

    # Store 3 entries.
    for i in range(3):
        await store.store(make_entry(content=f"similar content {i}"))

    results = await store.find_similar(content="similar content 0", threshold=0.0, limit=3)
    assert len(results) >= 1
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    await store.close()


# ---------------------------------------------------------------------------
# Transient connection retry with exponential backoff
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_connection_retry_on_transient_error(
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Store retries initialization on transient connection failure, succeeds on second attempt."""
    store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)

    call_count = 0
    original_open = store._open_connection

    def flaky_open() -> duckdb.DuckDBPyConnection:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise duckdb.IOException("Transient I/O error")
        return original_open()

    with patch.object(store, "_open_connection", side_effect=flaky_open), patch(
        "time.sleep"
    ) as mock_sleep:
        await store.initialize()

    assert store._initialized is True
    assert call_count == 2
    # Verify backoff was applied (first retry delay = 1s).
    mock_sleep.assert_called_once_with(1.0)
    await store.close()


@pytest.mark.unit
async def test_retry_exhausted_with_exponential_backoff(
    mock_embedding_provider: MockEmbeddingProvider,
) -> None:
    """Initialization raises after 3 retry attempts with exponential backoff."""
    store = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)

    call_count = 0

    def always_fail() -> duckdb.DuckDBPyConnection:
        nonlocal call_count
        call_count += 1
        raise duckdb.IOException("Persistent I/O error")

    with (
        patch.object(store, "_open_connection", side_effect=always_fail),
        patch("time.sleep") as mock_sleep,
        pytest.raises(duckdb.IOException, match="Persistent I/O error"),
    ):
        await store.initialize()

    assert call_count == 3
    # Verify exponential backoff: 1s, 2s (only 2 sleeps -- third attempt raises without sleep).
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert delays == [1.0, 2.0]


# ---------------------------------------------------------------------------
# /health endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_health_endpoint() -> None:
    """GET /health returns 200 with status fields."""
    import httpx

    from distillery.mcp.server import create_server

    config = _make_config()
    server = create_server(config=config)

    http_app = server.http_app(path="/mcp", transport="streamable-http", stateless_http=True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=http_app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "vss_available" in body
    assert "store_initialized" in body


@pytest.mark.integration
async def test_health_endpoint_no_auth_required() -> None:
    """GET /health succeeds without any Authorization header.

    FastMCP ``custom_route`` endpoints are mounted outside the auth-protected
    MCP path, so they do not require authentication by design.  This test
    verifies that behaviour by sending a request without credentials.
    """
    import httpx

    from distillery.mcp.server import create_server

    config = _make_config()
    server = create_server(config=config)

    http_app = server.http_app(path="/mcp", transport="streamable-http", stateless_http=True)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=http_app), base_url="http://test"
    ) as client:
        # Explicitly send NO authorization headers.
        resp = await client.get("/health", headers={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "vss_available" in body
