"""Tests for POST /hooks/classify-batch webhook endpoint.

Covers:
- Bearer auth requirement (401 without token)
- Heuristic mode classification
- LLM mode classification (headless: entries queued as pending_review)
- Empty inbox (no entries to classify)
- Invalid mode parameter returns 400
- Error handling when classification raises
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from distillery.config import DistilleryConfig, ServerConfig, WebhookConfig
from distillery.mcp.webhooks import create_webhook_app
from distillery.models import Entry, EntrySource, EntryStatus, EntryType
from distillery.store.duckdb import DuckDBStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "test-webhook-secret-xyz"
_AUTH_HEADER = {"Authorization": f"Bearer {_SECRET}"}


def _make_config(
    *, enabled: bool = True, secret_env: str = "DISTILLERY_WEBHOOK_SECRET"
) -> DistilleryConfig:
    """Return a DistilleryConfig with WebhookConfig overrides."""
    return DistilleryConfig(
        server=ServerConfig(
            webhooks=WebhookConfig(enabled=enabled, secret_env=secret_env),
        )
    )


def _make_shared_state(store: DuckDBStore, embedding_provider: Any = None) -> dict[str, Any]:
    """Return a minimal shared-state dict using *store*."""
    return {
        "store": store,
        "config": _make_config(),
        "embedding_provider": embedding_provider,
    }


def _make_entry(
    content: str = "Some inbox entry content",
    entry_type: EntryType = EntryType.INBOX,
    status: EntryStatus = EntryStatus.PENDING_REVIEW,
) -> Entry:
    """Return a minimal valid Entry."""
    return Entry(
        content=content,
        entry_type=entry_type,
        source=EntrySource.MANUAL,
        author="tester",
        status=status,
    )


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_classify_batch_rejects_unauthenticated(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/classify-batch without a bearer token returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, _make_config())

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/classify-batch")

    assert resp.status_code == 401
    assert resp.json() == {"ok": False, "error": "unauthorized"}


@pytest.mark.unit
async def test_classify_batch_rejects_wrong_token(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/classify-batch with wrong bearer token returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, _make_config())

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/classify-batch", headers={"Authorization": "Bearer wrong-token"})

    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


# ---------------------------------------------------------------------------
# Empty inbox
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_classify_batch_empty_inbox(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/classify-batch with no pending entries returns zeros."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, _make_config())

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/classify-batch", headers=_AUTH_HEADER)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["classified"] == 0
    assert data["pending_review"] == 0
    assert data["errors"] == 0
    assert data["by_type"] == {}


# ---------------------------------------------------------------------------
# Invalid mode parameter
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_classify_batch_invalid_mode(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/classify-batch?mode=invalid returns 400 bad request."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, _make_config())

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/classify-batch?mode=invalid", headers=_AUTH_HEADER)

    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert "mode" in body["error"]


# ---------------------------------------------------------------------------
# Heuristic mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_classify_batch_heuristic_mode_classifies(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/classify-batch?mode=heuristic classifies pending entries
    using HeuristicClassifier and updates store."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)

    # Build a mock embedding provider.
    mock_embedding_provider = MagicMock()
    mock_embedding_provider.embed.return_value = [0.1, 0.2, 0.3, 0.4]
    mock_embedding_provider.embed_batch.return_value = [
        [0.1, 0.2, 0.3, 0.4],
        [0.1, 0.2, 0.3, 0.4],
    ]
    shared = _make_shared_state(store, embedding_provider=mock_embedding_provider)

    # Two pending entries.
    entry_a = _make_entry("Explored auth module, tried OAuth2 flow")
    entry_b = _make_entry("Bookmarked https://example.com/article")

    # Mock classifier: classify_batch is the single entry point called by the
    # webhook handler.  Return two ClassificationResult objects — the first an
    # active session match, the second a pending_review inbox fallback.
    from distillery.classification.models import ClassificationResult

    mock_classifier = MagicMock()
    mock_classifier.classify_batch = AsyncMock(
        return_value=[
            ClassificationResult(
                entry_type=EntryType.SESSION,
                confidence=0.82,
                status=EntryStatus.ACTIVE,
                reasoning="Heuristic: best centroid match is session.",
                suggested_tags=[],
                suggested_project=None,
            ),
            ClassificationResult(
                entry_type=EntryType.INBOX,
                confidence=0.3,
                status=EntryStatus.PENDING_REVIEW,
                reasoning="Heuristic: no centroid exceeded threshold.",
                suggested_tags=[],
                suggested_project=None,
            ),
        ]
    )

    # list_entries returns our two entries; update succeeds.
    mock_store = MagicMock()
    mock_store.list_entries = AsyncMock(return_value=[entry_a, entry_b])
    mock_store.update = AsyncMock(
        return_value=entry_a  # return value is ignored by the handler
    )
    mock_store.get_metadata = AsyncMock(return_value=None)
    mock_store.set_metadata = AsyncMock()
    shared["store"] = mock_store

    with patch("distillery.classification.HeuristicClassifier", return_value=mock_classifier):
        app = create_webhook_app(shared, _make_config())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/hooks/classify-batch?mode=heuristic", headers=_AUTH_HEADER)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["classified"] == 1
    assert data["pending_review"] == 1
    assert data["errors"] == 0
    assert data["by_type"] == {"session": 1}

    # classify_batch invoked exactly once for the entire batch of entries.
    assert mock_classifier.classify_batch.await_count == 1

    # Verify update was called for both entries (both get their store records updated).
    assert mock_store.update.await_count == 2
    # The first update (for the active/classified entry) sets entry_type=session, status=active.
    first_call_args = mock_store.update.call_args_list[0]
    assert first_call_args[0][1]["entry_type"] == "session"
    assert first_call_args[0][1]["status"] == "active"


@pytest.mark.unit
async def test_classify_batch_heuristic_requires_embedding_provider(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/classify-batch?mode=heuristic without embedding provider returns 500."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    # embedding_provider is None (default).
    shared = _make_shared_state(store, embedding_provider=None)

    entry = _make_entry("Some content")

    mock_store = MagicMock()
    mock_store.list_entries = AsyncMock(return_value=[entry])
    mock_store.get_metadata = AsyncMock(return_value=None)
    mock_store.set_metadata = AsyncMock()
    shared["store"] = mock_store

    app = create_webhook_app(shared, _make_config())
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/classify-batch?mode=heuristic", headers=_AUTH_HEADER)

    assert resp.status_code == 500
    body = resp.json()
    assert body["ok"] is False
    assert "embedding provider" in body["error"]


# ---------------------------------------------------------------------------
# LLM mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_classify_batch_llm_mode_queues_as_pending_review(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/classify-batch?mode=llm uses an LLM client if available,
    and classifies entries according to LLM-returned confidences."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)

    # Create real entries in the store
    entry_a = _make_entry("Session content A")
    entry_b = _make_entry("Meeting notes B")
    await store.store(entry_a)
    await store.store(entry_b)

    # Mock LLM client that returns classification results with different confidences
    mock_llm_client = MagicMock()
    # Entry A: high confidence -> should be classified as ACTIVE
    mock_llm_client.classify = AsyncMock(
        side_effect=[
            '{"entry_type": "session", "confidence": 0.85, "reasoning": "High confidence session", "suggested_tags": [], "suggested_project": null}',
            '{"entry_type": "minutes", "confidence": 0.55, "reasoning": "Low confidence meeting", "suggested_tags": [], "suggested_project": null}',
        ]
    )

    shared = _make_shared_state(store)
    shared["llm_client"] = mock_llm_client

    app = create_webhook_app(shared, _make_config())
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/classify-batch?mode=llm", headers=_AUTH_HEADER)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]

    # Entry A: confidence 0.85 >= threshold (0.6) -> classified
    # Entry B: confidence 0.55 < threshold (0.6) -> pending_review
    assert data["classified"] == 1
    assert data["pending_review"] == 1
    assert data["errors"] == 0
    assert data["by_type"]["session"] == 1

    # Verify LLM was called twice
    assert mock_llm_client.classify.call_count == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_classify_batch_heuristic_error_counting(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When per-entry store update raises, errors count increments and
    other entries are still processed."""
    from distillery.classification.models import ClassificationResult

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)

    mock_embedding_provider = MagicMock()
    shared = _make_shared_state(store, embedding_provider=mock_embedding_provider)

    entry_a = _make_entry("Content A")
    entry_b = _make_entry("Content B")

    # Both entries classify successfully as reference/active; the store.update
    # raises for the first entry, simulating a per-entry failure that should be
    # caught and counted as an error without aborting the batch.
    mock_classifier = MagicMock()
    mock_classifier.classify_batch = AsyncMock(
        return_value=[
            ClassificationResult(
                entry_type=EntryType.REFERENCE,
                confidence=0.75,
                status=EntryStatus.ACTIVE,
                reasoning="Heuristic: reference centroid match.",
                suggested_tags=[],
                suggested_project=None,
            ),
            ClassificationResult(
                entry_type=EntryType.REFERENCE,
                confidence=0.75,
                status=EntryStatus.ACTIVE,
                reasoning="Heuristic: reference centroid match.",
                suggested_tags=[],
                suggested_project=None,
            ),
        ]
    )

    mock_store = MagicMock()
    mock_store.list_entries = AsyncMock(return_value=[entry_a, entry_b])
    # First update raises; second succeeds.
    mock_store.update = AsyncMock(
        side_effect=[RuntimeError("update failure"), entry_b]
    )
    mock_store.get_metadata = AsyncMock(return_value=None)
    mock_store.set_metadata = AsyncMock()
    shared["store"] = mock_store

    with patch("distillery.classification.HeuristicClassifier", return_value=mock_classifier):
        app = create_webhook_app(shared, _make_config())
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/hooks/classify-batch?mode=heuristic", headers=_AUTH_HEADER)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["ok"] is True
    data = body["data"]
    assert data["classified"] == 1
    assert data["errors"] == 1
    assert data["by_type"] == {"reference": 1}


@pytest.mark.unit
async def test_classify_batch_store_error_returns_500(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the store raises during list_entries the endpoint returns 500."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_store = MagicMock()
    mock_store.list_entries = AsyncMock(side_effect=RuntimeError("db connection lost"))
    mock_store.get_metadata = AsyncMock(return_value=None)
    mock_store.set_metadata = AsyncMock()
    shared["store"] = mock_store

    app = create_webhook_app(shared, _make_config())
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/classify-batch", headers=_AUTH_HEADER)

    assert resp.status_code == 500
    body = resp.json()
    assert body["ok"] is False
    # The webhook returns a stable, generic error message to clients and keeps
    # the exception details (e.g. "db connection lost") in server logs.
    assert body["error"] == "classify-batch failed"


# ---------------------------------------------------------------------------
# entry_type query parameter
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_classify_batch_entry_type_param(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/classify-batch?entry_type=feed filters by the given entry type."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_store = MagicMock()
    mock_store.list_entries = AsyncMock(return_value=[])
    mock_store.get_metadata = AsyncMock(return_value=None)
    mock_store.set_metadata = AsyncMock()
    shared["store"] = mock_store

    app = create_webhook_app(shared, _make_config())
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/classify-batch?entry_type=feed&mode=llm", headers=_AUTH_HEADER)

    assert resp.status_code == 200
    # Verify list_entries was called with entry_type=feed.
    call_kwargs = mock_store.list_entries.call_args[1]
    assert call_kwargs["filters"]["entry_type"] == "feed"
