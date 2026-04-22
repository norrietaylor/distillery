"""Tests for POST /maintenance webhook endpoint (rewired as async orchestrator).

Covers:
- Auth requirement (401 without bearer token)
- POST returns 202 + job_id; orchestrator runs poll → rescore → classify-batch
  on a background task and reports completion via GET /jobs/{id}
- Combined result format: {poll: {...}, rescore: {...}, classify_batch: {...}}
- Error in one sub-operation is reported in the job result but does not
  block the other sub-operations
- Cooldown enforcement (429 on second immediate request)
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from distillery.config import DistilleryConfig, ServerConfig, WebhookConfig
from distillery.feeds.poller import PollerSummary, PollResult
from distillery.mcp import webhooks as webhooks_module
from distillery.mcp.webhooks import create_webhook_app
from distillery.store.duckdb import DuckDBStore


@pytest.fixture(autouse=True)
def _reset_webhook_module_state() -> Any:
    """Clear module-level async-job registries between tests.

    See the matching fixture in ``tests/test_webhooks.py`` for rationale:
    the ``_jobs`` + ``_active_job_by_endpoint`` dicts leak across tests and
    cause a fresh POST to return 409 (stale active pointer) instead of 202.
    """
    webhooks_module._jobs.clear()
    webhooks_module._active_job_by_endpoint.clear()
    webhooks_module._endpoint_locks.clear()
    webhooks_module._cooldown_ts.clear()
    yield
    webhooks_module._jobs.clear()
    webhooks_module._active_job_by_endpoint.clear()
    webhooks_module._endpoint_locks.clear()
    webhooks_module._cooldown_ts.clear()

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


def _make_poller_mock(
    *,
    sources_polled: int = 1,
    total_fetched: int = 5,
    total_stored: int = 3,
    poll_errors: list[str] | None = None,
    rescored: int = 10,
    upgraded: int = 2,
    downgraded: int = 1,
    poll_raises: Exception | None = None,
    rescore_raises: Exception | None = None,
) -> MagicMock:
    """Build a FeedPoller mock with configurable poll/rescore behaviour."""
    result = PollResult(
        source_url="https://example.com/feed",
        source_type="rss",
        items_fetched=total_fetched,
        items_stored=total_stored,
        errors=poll_errors or [],
    )
    summary = PollerSummary(
        results=[result],
        total_fetched=total_fetched,
        total_stored=total_stored,
        sources_polled=sources_polled,
    )
    rescore_stats = {"rescored": rescored, "upgraded": upgraded, "downgraded": downgraded}

    mock = MagicMock()
    if poll_raises:
        mock.poll = AsyncMock(side_effect=poll_raises)
    else:
        mock.poll = AsyncMock(return_value=summary)

    if rescore_raises:
        mock.rescore = AsyncMock(side_effect=rescore_raises)
    else:
        mock.rescore = AsyncMock(return_value=rescore_stats)

    return mock


def _wait_for_job(
    client: TestClient,
    job_id: str,
    *,
    timeout_s: float = 5.0,
    poll_interval_s: float = 0.01,
) -> dict[str, Any]:
    """Poll ``GET /jobs/{job_id}`` until the job is terminal; return the dict."""
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        resp = client.get(f"/jobs/{job_id}", headers=_AUTH_HEADER)
        assert resp.status_code == 200, f"GET /jobs/{job_id} → {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["ok"] is True, body
        last = body["data"]
        if last["state"] in ("succeeded", "failed"):
            return last
        time.sleep(poll_interval_s)
    raise AssertionError(f"job {job_id} did not terminate within {timeout_s}s; last={last!r}")


def _submit_and_await(
    client: TestClient,
) -> dict[str, Any]:
    """POST /maintenance, assert 202, wait for completion, return job snapshot."""
    resp = client.post("/maintenance", headers=_AUTH_HEADER)
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    return _wait_for_job(client, resp.json()["job_id"])


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_maintenance_rejects_unauthenticated(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /maintenance without a bearer token returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, _make_config())

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/maintenance")

    assert resp.status_code == 401
    assert resp.json() == {"ok": False, "error": "unauthorized"}


@pytest.mark.unit
async def test_maintenance_rejects_wrong_token(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /maintenance with wrong bearer token returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, _make_config())

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/maintenance", headers={"Authorization": "Bearer wrong-token"})

    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


# ---------------------------------------------------------------------------
# Combined result format
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_maintenance_combined_result_format(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /maintenance returns 202 + job id; the job result contains
    {poll: {...}, rescore: {...}, classify_batch: {...}} — all three
    sub-operation keys are present."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_poller = _make_poller_mock(
        sources_polled=2, total_fetched=10, total_stored=7, rescored=15, upgraded=3, downgraded=2
    )

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, _make_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            final = _submit_and_await(client)

    assert final["state"] == "succeeded", final
    data = final["result"]
    assert "poll" in data, "Missing 'poll' key in maintenance result"
    assert "rescore" in data, "Missing 'rescore' key in maintenance result"
    assert "classify_batch" in data, "Missing 'classify_batch' key in maintenance result"


@pytest.mark.unit
async def test_maintenance_poll_sub_operation_values(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The poll sub-result contains sources_polled, items_fetched, items_stored, errors."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_poller = _make_poller_mock(sources_polled=3, total_fetched=12, total_stored=9)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, _make_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            final = _submit_and_await(client)

    data = final["result"]
    poll = data["poll"]
    assert poll["sources_polled"] == 3
    assert poll["items_fetched"] == 12
    assert poll["items_stored"] == 9
    assert poll["errors"] == []


@pytest.mark.unit
async def test_maintenance_rescore_sub_operation_values(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rescore sub-result contains rescored, upgraded, downgraded counts."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_poller = _make_poller_mock(rescored=25, upgraded=7, downgraded=3)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, _make_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            final = _submit_and_await(client)

    data = final["result"]
    rescore = data["rescore"]
    assert rescore["rescored"] == 25
    assert rescore["upgraded"] == 7
    assert rescore["downgraded"] == 3


@pytest.mark.unit
async def test_maintenance_classify_batch_sub_operation_present(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The classify_batch sub-result is present with classified, pending_review,
    errors, and by_type keys (no entries in fresh store → all zeros)."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_poller = _make_poller_mock()

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, _make_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            final = _submit_and_await(client)

    data = final["result"]
    classify = data["classify_batch"]
    assert "classified" in classify
    assert "pending_review" in classify
    assert "errors" in classify
    assert "by_type" in classify
    assert classify["classified"] == 0
    assert classify["pending_review"] == 0
    assert classify["errors"] == 0


# ---------------------------------------------------------------------------
# Sequential execution order
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_maintenance_calls_poll_then_rescore(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both FeedPoller.poll() and FeedPoller.rescore() are called during maintenance,
    and poll is invoked before rescore."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_poller = _make_poller_mock()

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, _make_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            final = _submit_and_await(client)

    assert final["state"] == "succeeded"
    mock_poller.poll.assert_awaited()
    mock_poller.rescore.assert_awaited()
    call_names = [c[0] for c in mock_poller.mock_calls]
    assert call_names.index("poll") < call_names.index("rescore"), (
        "poll() must be called before rescore() in the maintenance pipeline"
    )


# ---------------------------------------------------------------------------
# Error isolation — one sub-operation failure does not block others
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_maintenance_poll_failure_does_not_block_rescore_or_classify(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When poll sub-operation fails, rescore and classify-batch still run.

    The overall job still terminates as ``succeeded`` because maintenance is
    best-effort; the poll error is captured in the poll sub-result."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_poller = _make_poller_mock(poll_raises=RuntimeError("feed timeout"))

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, _make_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            final = _submit_and_await(client)

    assert final["state"] == "succeeded", (
        f"Maintenance should still succeed as a whole when poll fails; got {final!r}"
    )
    data = final["result"]

    # poll sub-result reports failure.
    assert data["poll"].get("ok") is False or "error" in data["poll"], (
        "poll failure should be reflected in the poll sub-result"
    )

    # rescore and classify_batch keys are still present.
    assert "rescore" in data
    assert "classify_batch" in data


@pytest.mark.unit
async def test_maintenance_rescore_failure_does_not_block_classify(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When rescore sub-operation fails, classify-batch still runs.

    The overall job still terminates as ``succeeded``; rescore reports its
    error inline."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_poller = _make_poller_mock(rescore_raises=RuntimeError("rescore db error"))

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, _make_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            final = _submit_and_await(client)

    assert final["state"] == "succeeded", (
        f"Maintenance should still succeed as a whole when rescore fails; got {final!r}"
    )
    data = final["result"]

    assert data["rescore"].get("ok") is False or "error" in data["rescore"], (
        "rescore failure should be reflected in the rescore sub-result"
    )
    assert "classify_batch" in data


# ---------------------------------------------------------------------------
# Cooldown enforcement
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_maintenance_cooldown_enforced(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First POST /maintenance returns 202; immediate second returns 429 with Retry-After.

    Cooldown is reserved synchronously inside the dispatcher before the 202
    is returned, so the second POST sees the cooldown regardless of whether
    the first job has completed."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    shared = _make_shared_state(store)

    mock_poller = _make_poller_mock()

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, _make_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.post("/maintenance", headers=_AUTH_HEADER)
            assert first.status_code == 202, (
                f"First request should be accepted, got {first.status_code}"
            )

            second = client.post("/maintenance", headers=_AUTH_HEADER)
            assert second.status_code == 429, (
                f"Second immediate request should be rate-limited, got {second.status_code}"
            )
            body = second.json()
            assert body["ok"] is False
            assert body["error"] == "too_early"
            assert isinstance(body.get("retry_after"), int)
            assert body["retry_after"] > 0
            assert "retry-after" in second.headers

            # Let the first job finish cleanly.
            _wait_for_job(client, first.json()["job_id"])
