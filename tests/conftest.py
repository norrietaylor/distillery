"""Shared pytest fixtures and helpers for the Distillery test suite.

Provides:
  - make_entry(**kwargs) -> Entry   factory for minimal valid entries
  - parse_mcp_response(content) -> dict  JSON parser for MCP TextContent lists
  - mock_embedding_provider fixture   hash-based 4D provider
  - deterministic_embedding_provider fixture   registry + hash fallback, 4D
  - controlled_embedding_provider fixture   registry + L2 normalisation, 8D
  - store fixture   async in-memory DuckDBStore, closed after test
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from distillery.models import Entry, EntrySource, EntryType
from distillery.store.duckdb import DuckDBStore

# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def make_entry(**kwargs: Any) -> Entry:
    """Return a minimal valid Entry, optionally overriding any field.

    Defaults:
        content     = "Default content"
        entry_type  = EntryType.INBOX
        source      = EntrySource.MANUAL
        author      = "tester"
    """
    defaults: dict[str, Any] = {
        "content": "Default content",
        "entry_type": EntryType.INBOX,
        "source": EntrySource.MANUAL,
        "author": "tester",
    }
    defaults.update(kwargs)
    return Entry(**defaults)


# ---------------------------------------------------------------------------
# MCP response parser
# ---------------------------------------------------------------------------


def parse_mcp_response(content: list) -> dict:  # type: ignore[type-arg]
    """Parse the JSON payload from a single-item MCP TextContent list.

    Args:
        content: list returned by an MCP tool handler (must have exactly 1 item).

    Returns:
        Parsed dict from ``content[0].text``.
    """
    assert len(content) == 1, f"Expected 1 content item, got {len(content)}"
    return json.loads(content[0].text)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Embedding provider implementations
# ---------------------------------------------------------------------------


class MockEmbeddingProvider:
    """Hash-based 4-dimensional deterministic unit vectors.

    Different input texts produce different vectors with high probability.
    Suitable for basic store/retrieval tests that do not require precise
    similarity control.
    """

    _DIMS = 4

    def _vector_for(self, text: str) -> list[float]:
        h = hash(text) & 0xFFFFFFFF
        parts = [(h >> (8 * i)) & 0xFF for i in range(self._DIMS)]
        floats = [float(p) + 1.0 for p in parts]
        magnitude = math.sqrt(sum(x * x for x in floats))
        return [x / magnitude for x in floats]

    def embed(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMS

    @property
    def model_name(self) -> str:
        return "mock-hash-4d"


class DeterministicEmbeddingProvider:
    """Registry-backed 4-dimensional embedding provider.

    Supports ``register(text, vector)`` for precise vector control.
    Unregistered texts fall back to the hash-based unit vector.
    All registered vectors are L2-normalised on registration.
    """

    _DIMS = 4

    def __init__(self) -> None:
        self._registry: dict[str, list[float]] = {}

    def register(self, text: str, vector: list[float]) -> None:
        """Register a specific (normalised) vector for *text*."""
        mag = math.sqrt(sum(x * x for x in vector))
        self._registry[text] = [x / mag for x in vector]

    def _vector_for(self, text: str) -> list[float]:
        if text in self._registry:
            return self._registry[text]
        h = hash(text) & 0xFFFFFFFF
        parts = [(h >> (8 * i)) & 0xFF for i in range(self._DIMS)]
        floats = [float(p) + 1.0 for p in parts]
        magnitude = math.sqrt(sum(x * x for x in floats))
        return [x / magnitude for x in floats]

    def embed(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMS

    @property
    def model_name(self) -> str:
        return "deterministic-4d"


class ControlledEmbeddingProvider:
    """Registry-backed 8-dimensional embedding provider for threshold testing.

    The 8-dimensional space gives precise control over cosine similarity.
    Registered vectors are L2-normalised; unregistered texts fall back to
    hash-based vectors.
    """

    _DIMS = 8

    def __init__(self) -> None:
        self._registry: dict[str, list[float]] = {}

    def register(self, text: str, vector: list[float]) -> None:
        """Register a specific (normalised) vector for *text*."""
        magnitude = math.sqrt(sum(x * x for x in vector))
        self._registry[text] = [x / magnitude for x in vector]

    def _hash_vector(self, text: str) -> list[float]:
        h = hash(text) & 0xFFFFFFFF
        parts = [(h >> (8 * i)) & 0xFF for i in range(self._DIMS)]
        floats = [float(p) + 1.0 for p in parts]
        magnitude = math.sqrt(sum(x * x for x in floats))
        return [x / magnitude for x in floats]

    def _vector_for(self, text: str) -> list[float]:
        return self._registry.get(text, self._hash_vector(text))

    def embed(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._DIMS

    @property
    def model_name(self) -> str:
        return "controlled-8d"


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_embedding_provider() -> MockEmbeddingProvider:
    """Hash-based 4D embedding provider. Different texts produce different vectors."""
    return MockEmbeddingProvider()


@pytest.fixture
def deterministic_embedding_provider() -> DeterministicEmbeddingProvider:
    """4D provider supporting register(text, vector) for precise similarity control."""
    return DeterministicEmbeddingProvider()


@pytest.fixture
def controlled_embedding_provider() -> ControlledEmbeddingProvider:
    """8D provider for precise cosine-similarity threshold testing."""
    return ControlledEmbeddingProvider()


@pytest.fixture
async def store(
    mock_embedding_provider: MockEmbeddingProvider,
) -> DuckDBStore:
    """Initialised in-memory DuckDBStore using the mock_embedding_provider.

    Yields the store for test use and closes it afterwards.
    """
    s = DuckDBStore(db_path=":memory:", embedding_provider=mock_embedding_provider)
    await s.initialize()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# Feed reachability probe: autouse stub so unit tests never hit the network.
# Individual tests that exercise the real probe can override with their own
# monkeypatch, but by default every test is insulated from outbound calls.
# ---------------------------------------------------------------------------

from collections.abc import Iterator  # noqa: E402


@pytest.fixture(autouse=True)
def _disable_watch_probe(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Stub ``distillery.mcp.tools.feeds._probe_url`` so it returns ``None``.

    Centralised here (per CodeRabbit #323 nitpick) instead of duplicated in
    ``test_watch.py`` / ``test_mcp_feeds.py`` / ``test_mcp_coverage_gaps.py``.

    Tests that exercise the real probe should mark themselves
    ``@pytest.mark.live_probe`` (or live in a module registered with that
    marker) to opt out — the autouse stub is skipped for those.
    """
    if request.node.get_closest_marker("live_probe") is not None:
        yield
        return

    async def _noop_probe(url: str) -> str | None:
        return None

    monkeypatch.setattr("distillery.mcp.tools.feeds._probe_url", _noop_probe)
    yield
