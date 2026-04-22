"""Unit and integration tests for webhook authentication, cooldowns, and async jobs.

Covers:
- Bearer token authentication (missing, wrong, valid)
- Per-endpoint cooldown enforcement (429 with Retry-After)
- Cooldown persistence via DuckDB get_metadata / set_metadata
- App composition: parent Starlette app mounts both /api/* and /mcp paths
- Webhooks-disabled state: no /api routes when disabled or no secret env var
- Async job contract: POST /poll|/rescore|/maintenance returns 202 + job_id,
  background task runs the real work, GET /jobs/{id} surfaces the result
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from distillery.config import DistilleryConfig, ServerConfig, WebhookConfig
from distillery.mcp import webhooks as webhooks_module
from distillery.mcp.webhooks import create_webhook_app
from distillery.store.duckdb import DuckDBStore

# The autouse fixture that clears ``_jobs``, ``_active_job_by_endpoint``,
# ``_endpoint_locks``, and ``_cooldown_ts`` between tests lives in the root
# ``tests/conftest.py`` so all webhook test files share it.

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


def _make_shared_state(store: DuckDBStore) -> dict[str, Any]:
    """Return a minimal shared-state dict using *store*."""
    return {"store": store, "config": _make_config(), "embedding_provider": None}


def _wait_for_job(
    client: TestClient,
    job_id: str,
    *,
    timeout_s: float = 5.0,
    poll_interval_s: float = 0.01,
) -> dict[str, Any]:
    """Poll ``GET /jobs/{job_id}`` until the job reaches a terminal state.

    Raises :class:`AssertionError` on timeout so tests fail with a readable
    message rather than flaking.  Returns the serialised job dict.
    """
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


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_auth_missing_token(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST to /poll without Authorization header returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/poll")

    assert resp.status_code == 401
    assert resp.json() == {"ok": False, "error": "unauthorized"}


@pytest.mark.unit
async def test_auth_wrong_token(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST with wrong bearer token returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/poll", headers={"Authorization": "Bearer wrong-secret-value"})

    assert resp.status_code == 401
    assert resp.json() == {"ok": False, "error": "unauthorized"}


@pytest.mark.unit
async def test_auth_valid_token_returns_202(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST with correct bearer token returns 202 and a job id."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/poll", headers=_AUTH_HEADER)

        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["ok"] is True
        assert isinstance(body["job_id"], str) and body["job_id"]
        assert body["state"] == "queued"
        assert body["status_url"] == f"/jobs/{body['job_id']}"

        # The background task must complete; the real FeedPoller runs against
        # the empty fixture store and returns an all-zeros poll summary.
        final = _wait_for_job(client, body["job_id"])
        assert final["state"] == "succeeded"


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_cooldown_enforced(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """First authenticated request returns 202; immediate second returns 429 with Retry-After."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    with TestClient(app, raise_server_exceptions=False) as client:
        # First request: enqueues job, returns 202.  Cooldown is reserved
        # synchronously before 202 returns, so the second call sees it.
        first = client.post("/poll", headers=_AUTH_HEADER)
        assert first.status_code == 202, f"Expected 202 on first request, got {first.status_code}"

        # Immediate second request: must be rejected with 429.
        second = client.post("/poll", headers=_AUTH_HEADER)
        assert second.status_code == 429, (
            f"Expected 429 on second request, got {second.status_code}"
        )

        body = second.json()
        assert body["ok"] is False
        assert body["error"] == "too_early"
        assert "retry_after" in body
        assert isinstance(body["retry_after"], int)
        assert body["retry_after"] > 0

        # Retry-After header must also be present.
        assert "retry-after" in second.headers
        assert int(second.headers["retry-after"]) > 0

        # Let the first job finish so the test exits cleanly.
        _wait_for_job(client, first.json()["job_id"])


@pytest.mark.integration
async def test_cooldown_persisted(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cooldown set by one app instance is visible to a new app using the same store.

    This tests DuckDB persistence: the cooldown timestamp written by
    create_webhook_app#1 via store.set_metadata is still present when a second
    create_webhook_app#2 instance is created pointing at the same store.
    """
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared1 = _make_shared_state(store)
    app1 = create_webhook_app(shared1, config)

    with TestClient(app1, raise_server_exceptions=False) as client1:
        # First request triggers cooldown recording in DuckDB.
        resp = client1.post("/poll", headers=_AUTH_HEADER)
        assert resp.status_code == 202
        _wait_for_job(client1, resp.json()["job_id"])

    # Verify the cooldown was actually written to DuckDB.
    cooldown_val = await store.get_metadata("webhook_cooldown:poll")
    assert cooldown_val is not None, "Cooldown timestamp was not persisted to DuckDB"

    # Create a brand-new app instance with a fresh shared_state dict,
    # but pointing at the same underlying store.
    shared2 = _make_shared_state(store)
    app2 = create_webhook_app(shared2, config)
    with TestClient(app2, raise_server_exceptions=False) as client2:
        # The new app should see the cooldown from DuckDB.
        resp2 = client2.post("/poll", headers=_AUTH_HEADER)
        assert resp2.status_code == 429, (
            "New webhook app instance did not see DuckDB-persisted cooldown"
        )
        assert resp2.json()["error"] == "too_early"


# ---------------------------------------------------------------------------
# App composition tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_app_composition(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """When webhooks are enabled and secret is set, parent Starlette app serves both
    /api/* and /mcp paths.
    """
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    webhook_app = create_webhook_app(shared, config)

    # Build a minimal stub for the MCP app.
    async def _mcp_handler(request: Request) -> JSONResponse:
        return JSONResponse({"mcp": True})

    mcp_stub = Starlette(routes=[Route("/mcp", _mcp_handler)])

    # Compose parent app exactly as __main__.py does.
    parent = Starlette(
        routes=[
            Mount("/api", app=webhook_app),
            Mount("/", app=mcp_stub),
        ]
    )

    with TestClient(parent, raise_server_exceptions=False) as client:
        # /mcp path should be accessible.
        mcp_resp = client.get("/mcp")
        assert mcp_resp.status_code == 200
        assert mcp_resp.json() == {"mcp": True}

        # /api/poll without auth should return 401.
        api_resp = client.post("/api/poll")
        assert api_resp.status_code == 401
        assert api_resp.json()["error"] == "unauthorized"

        # /api/poll with correct auth should return 202 + job id.
        api_auth_resp = client.post("/api/poll", headers=_AUTH_HEADER)
        assert api_auth_resp.status_code == 202
        job_id = api_auth_resp.json()["job_id"]

        # Let the bg task complete to avoid a pending task at teardown.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            resp = client.get(f"/api/jobs/{job_id}", headers=_AUTH_HEADER)
            assert resp.status_code == 200
            if resp.json()["data"]["state"] in ("succeeded", "failed"):
                break
            time.sleep(0.01)


# ---------------------------------------------------------------------------
# Disabled-state tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_webhooks_disabled(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """When webhooks are disabled OR the secret env var is unset, /api routes should
    not be mounted in the parent app.

    This test mirrors the guard in __main__.py:
        if config.server.webhooks.enabled and os.environ.get(config.server.webhooks.secret_env)
    """
    # Scenario 1: webhooks disabled via config flag (secret is still set).
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config_disabled = _make_config(enabled=False)
    shared = _make_shared_state(store)

    async def _mcp_handler(request: Request) -> JSONResponse:
        return JSONResponse({"mcp": True})

    mcp_stub = Starlette(routes=[Route("/mcp", _mcp_handler)])

    # Replicate __main__.py logic: only compose if enabled AND secret set.
    if config_disabled.server.webhooks.enabled and os.environ.get(
        config_disabled.server.webhooks.secret_env
    ):
        webhook_app = create_webhook_app(shared, config_disabled)
        final_app: Starlette = Starlette(
            routes=[
                Mount("/api", app=webhook_app),
                Mount("/", app=mcp_stub),
            ]
        )
    else:
        # Pass through as-is — no /api routes.
        final_app = mcp_stub

    client = TestClient(final_app, raise_server_exceptions=False)

    # /api/poll must not exist when disabled — expect 404.
    resp = client.post("/api/poll", headers=_AUTH_HEADER)
    assert resp.status_code == 404, (
        f"Expected 404 (no /api routes when disabled), got {resp.status_code}"
    )

    # /mcp is still accessible.
    mcp_resp = client.get("/mcp")
    assert mcp_resp.status_code == 200

    # Scenario 2: webhooks enabled via config but no secret env var set.
    monkeypatch.delenv("DISTILLERY_WEBHOOK_SECRET", raising=False)
    config_no_secret = _make_config(enabled=True)

    if config_no_secret.server.webhooks.enabled and os.environ.get(
        config_no_secret.server.webhooks.secret_env
    ):
        webhook_app2 = create_webhook_app(shared, config_no_secret)
        final_app2: Starlette = Starlette(
            routes=[
                Mount("/api", app=webhook_app2),
                Mount("/", app=mcp_stub),
            ]
        )
    else:
        final_app2 = mcp_stub

    client2 = TestClient(final_app2, raise_server_exceptions=False)

    resp2 = client2.post("/api/poll", headers=_AUTH_HEADER)
    assert resp2.status_code == 404, (
        f"Expected 404 (no /api routes when no secret), got {resp2.status_code}"
    )


# ---------------------------------------------------------------------------
# Handler tests — poll, rescore, maintenance (async contract)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_poll_handler(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /poll returns 202 immediately; the background job runs FeedPoller.poll()
    and the GET /jobs/{id} result reflects the summary."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from distillery.feeds.poller import PollerSummary, PollResult

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    result = PollResult(
        source_url="https://example.com/feed", source_type="rss", items_fetched=10, items_stored=7
    )
    summary = PollerSummary(results=[result], total_fetched=10, total_stored=7, sources_polled=1)

    mock_poller = MagicMock()
    mock_poller.poll = AsyncMock(return_value=summary)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller) as mock_cls:
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/poll", headers=_AUTH_HEADER)
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
            final = _wait_for_job(client, resp.json()["job_id"])

    assert final["state"] == "succeeded", final
    data = final["result"]
    assert data["sources_polled"] == 1
    assert data["items_fetched"] == 10
    assert data["items_stored"] == 7
    assert data["errors"] == []
    mock_cls.assert_called_once()
    mock_poller.poll.assert_awaited_once()


@pytest.mark.unit
async def test_rescore_handler(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /rescore with body {limit: 50} returns 202; the background job
    forwards limit=50 to FeedPoller.rescore() and the job result carries the stats."""
    from unittest.mock import AsyncMock, MagicMock, patch

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    rescore_stats = {"rescored": 50, "upgraded": 12, "downgraded": 5, "errors": 0}

    mock_poller = MagicMock()
    mock_poller.rescore = AsyncMock(return_value=rescore_stats)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/rescore", headers=_AUTH_HEADER, json={"limit": 50})
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
            final = _wait_for_job(client, resp.json()["job_id"])

    assert final["state"] == "succeeded", final
    data = final["result"]
    assert data["rescored"] == 50
    assert data["upgraded"] == 12
    assert data["downgraded"] == 5
    # Verify the custom limit was forwarded to the poller.
    mock_poller.rescore.assert_awaited_once_with(limit=50)


@pytest.mark.unit
async def test_maintenance_handler(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /maintenance returns 202; the background job orchestrates
    poll → rescore → classify-batch and the GET /jobs/{id} result contains
    combined poll, rescore, and classify_batch keys."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from distillery.feeds.poller import PollerSummary, PollResult

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    # Mock FeedPoller for both poll and rescore sub-operations.
    poll_result = PollResult(
        source_url="https://example.com/feed",
        source_type="rss",
        items_fetched=5,
        items_stored=3,
    )
    poll_summary = PollerSummary(
        results=[poll_result], total_fetched=5, total_stored=3, sources_polled=1
    )
    rescore_stats = {"rescored": 20, "upgraded": 4, "downgraded": 1}

    mock_poller = MagicMock()
    mock_poller.poll = AsyncMock(return_value=poll_summary)
    mock_poller.rescore = AsyncMock(return_value=rescore_stats)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/maintenance", headers=_AUTH_HEADER)
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
            final = _wait_for_job(client, resp.json()["job_id"])

    assert final["state"] == "succeeded", final
    data = final["result"]

    # Response must contain all three sub-operation keys.
    assert "poll" in data
    assert "rescore" in data
    assert "classify_batch" in data

    # poll sub-result contains expected fields.
    assert data["poll"]["sources_polled"] == 1
    assert data["poll"]["items_fetched"] == 5
    assert data["poll"]["items_stored"] == 3

    # rescore sub-result contains expected fields.
    assert data["rescore"]["rescored"] == 20
    assert data["rescore"]["upgraded"] == 4
    assert data["rescore"]["downgraded"] == 1

    # classify_batch sub-result is present (no pending entries → zeros).
    assert "classified" in data["classify_batch"]


@pytest.mark.unit
async def test_handler_error_surfaces_in_job(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When FeedPoller.poll() raises an exception the endpoint still returns 202,
    but the background job terminates in the 'failed' state with a descriptive
    error payload."""
    from unittest.mock import AsyncMock, MagicMock, patch

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    mock_poller = MagicMock()
    mock_poller.poll = AsyncMock(side_effect=RuntimeError("feed source unavailable"))

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/poll", headers=_AUTH_HEADER)
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
            final = _wait_for_job(client, resp.json()["job_id"])

    assert final["state"] == "failed", final
    # The webhook returns a stable, generic error message to clients and keeps
    # the exception details (e.g. "feed source unavailable") in server logs.
    assert final["error"] == "poll cycle failed"


@pytest.mark.unit
async def test_failed_job_triggers_store_rollback(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the bg runner fails, _execute_job calls store.rollback() so any
    aborted DuckDB transaction state cannot leak into the next webhook job.

    This is the defensive safety-net described in issue #396: a prior
    rollback regression let a poisoned connection cascade every subsequent
    find_similar/store call in the same poll run.  Rollback at the webhook
    boundary is redundant with ``DuckDBStore._run_sync`` on the happy path
    but catches regressions in paths that bypass it.
    """
    from unittest.mock import AsyncMock, MagicMock, patch

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()

    # Wrap the real store with a spy on rollback() to observe calls without
    # disturbing the rest of the interface.
    rollback_spy = AsyncMock(wraps=store.rollback)
    spy_store = MagicMock(wraps=store)
    spy_store.rollback = rollback_spy
    shared: dict[str, Any] = {
        "store": spy_store,
        "config": _make_config(),
        "embedding_provider": None,
    }

    mock_poller = MagicMock()
    mock_poller.poll = AsyncMock(side_effect=RuntimeError("feed source unavailable"))

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/poll", headers=_AUTH_HEADER)
            assert resp.status_code == 202
            final = _wait_for_job(client, resp.json()["job_id"])

    assert final["state"] == "failed", final
    assert rollback_spy.await_count >= 1, (
        "store.rollback() must be called when the bg runner fails "
        "(defensive guard against issue #396 cascade)"
    )


# ---------------------------------------------------------------------------
# /hooks/poll and /hooks/rescore endpoint tests (deprecated async aliases)
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_hooks_poll_route_exists(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /hooks/poll is a valid route that returns 202 + job id with a valid
    bearer token, and the background job succeeds."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from distillery.feeds.poller import PollerSummary, PollResult

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    result = PollResult(
        source_url="https://example.com/feed", source_type="rss", items_fetched=5, items_stored=3
    )
    summary = PollerSummary(results=[result], total_fetched=5, total_stored=3, sources_polled=1)

    mock_poller = MagicMock()
    mock_poller.poll = AsyncMock(return_value=summary)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/hooks/poll", headers=_AUTH_HEADER)
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert body["ok"] is True
            assert "job_id" in body
            final = _wait_for_job(client, body["job_id"])

    assert final["state"] == "succeeded"


@pytest.mark.unit
async def test_hooks_poll_rejects_unauthenticated(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/poll without a bearer token returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/poll")

    assert resp.status_code == 401
    assert resp.json() == {"ok": False, "error": "unauthorized"}


@pytest.mark.unit
async def test_hooks_poll_source_url_query_param(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/poll?source_url=<url> forwards source_url to FeedPoller.poll()
    on the background task."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from distillery.feeds.poller import PollerSummary, PollResult

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    target_url = "https://example.com/feed"
    result = PollResult(source_url=target_url, source_type="rss", items_fetched=3, items_stored=2)
    summary = PollerSummary(results=[result], total_fetched=3, total_stored=2, sources_polled=1)

    mock_poller = MagicMock()
    mock_poller.poll = AsyncMock(return_value=summary)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                f"/hooks/poll?source_url={target_url}",
                headers=_AUTH_HEADER,
            )
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
            _wait_for_job(client, resp.json()["job_id"])

    # Verify poll was called with the specific source_url.
    mock_poller.poll.assert_awaited_once_with(source_url=target_url)


@pytest.mark.unit
async def test_hooks_rescore_route_exists(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/rescore is a valid route that returns 202 + job id with a valid
    bearer token, and the background job succeeds."""
    from unittest.mock import AsyncMock, MagicMock, patch

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    rescore_stats = {"rescored": 20, "upgraded": 5, "downgraded": 2, "errors": 0}
    mock_poller = MagicMock()
    mock_poller.rescore = AsyncMock(return_value=rescore_stats)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/hooks/rescore", headers=_AUTH_HEADER)
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert body["ok"] is True
            assert "job_id" in body
            final = _wait_for_job(client, body["job_id"])

    assert final["state"] == "succeeded"


@pytest.mark.unit
async def test_hooks_rescore_rejects_unauthenticated(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/rescore without a bearer token returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/rescore")

    assert resp.status_code == 401
    assert resp.json() == {"ok": False, "error": "unauthorized"}


@pytest.mark.unit
async def test_hooks_rescore_limit_query_param(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/rescore?limit=50 forwards limit=50 to FeedPoller.rescore()."""
    from unittest.mock import AsyncMock, MagicMock, patch

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    rescore_stats = {"rescored": 50, "upgraded": 10, "downgraded": 3, "errors": 0}
    mock_poller = MagicMock()
    mock_poller.rescore = AsyncMock(return_value=rescore_stats)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/hooks/rescore?limit=50", headers=_AUTH_HEADER)
            assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
            _wait_for_job(client, resp.json()["job_id"])

    mock_poller.rescore.assert_awaited_once_with(limit=50)


@pytest.mark.unit
async def test_hooks_rescore_invalid_limit_query_param(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /hooks/rescore?limit=abc returns 400 bad request (parsed before 202)."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/hooks/rescore?limit=abc", headers=_AUTH_HEADER)

    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert "integer" in body["error"]


@pytest.mark.unit
@pytest.mark.parametrize("bad_limit", ["0", "-1"])
async def test_hooks_rescore_non_positive_limit_query_param(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch, bad_limit: str
) -> None:
    """POST /hooks/rescore?limit=0 and ?limit=-1 return 400 bad request.

    Guards the ``limit <= 0`` branch in the rescore parser against regression
    — a purely typed check would let zero/negative values slip through.
    Each bad limit runs in its own parametrised invocation so the
    fresh in-memory ``store`` fixture provides a clean cooldown slate.
    """
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(f"/hooks/rescore?limit={bad_limit}", headers=_AUTH_HEADER)

    assert resp.status_code == 400, (
        f"limit={bad_limit!r} should be rejected; got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["ok"] is False
    assert "positive" in body["error"], (
        f"error should mention 'positive' for limit={bad_limit!r}; got {body['error']!r}"
    )


# ---------------------------------------------------------------------------
# Async job semantics — idempotency, status endpoint, unknown job id
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_jobs_endpoint_requires_auth(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /jobs/{id} without a bearer token returns 401 unauthorized."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/jobs/does-not-matter")
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


@pytest.mark.unit
async def test_jobs_endpoint_unknown_id_returns_404(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /jobs/<unknown> returns 404 with a descriptive error."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/jobs/no-such-id", headers=_AUTH_HEADER)
    assert resp.status_code == 404
    assert resp.json() == {"ok": False, "error": "job not found"}


@pytest.mark.unit
async def test_second_poll_while_in_flight_returns_409(
    store: DuckDBStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While a poll job is running, a second POST /poll returns 409 with the
    existing job_id so the caller re-attaches rather than racing.

    This guards the idempotency contract independently of the cooldown —
    we overwrite the cooldown key with a far-past timestamp between the
    two requests so the only reason the second call can fail is the
    in-flight lock.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    from distillery.feeds.poller import PollerSummary, PollResult

    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)

    # Slow poll: keep the bg task alive long enough that the second request
    # sees the job mid-flight.  We use asyncio.sleep (not a cross-loop Event)
    # because the bg task and the second dispatch run in the TestClient's
    # portal loop — but the test function itself runs in pytest-asyncio's
    # loop, and asyncio.Event is loop-bound.
    result = PollResult(source_url="https://x/feed", source_type="rss")
    summary = PollerSummary(results=[result])

    async def _slow_poll(*args: Any, **kwargs: Any) -> PollerSummary:
        await asyncio.sleep(0.5)
        return summary

    mock_poller = MagicMock()
    mock_poller.poll = AsyncMock(side_effect=_slow_poll)

    with patch("distillery.mcp.webhooks.FeedPoller", return_value=mock_poller):
        app = create_webhook_app(shared, config)
        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.post("/poll", headers=_AUTH_HEADER)
            assert first.status_code == 202
            first_job_id = first.json()["job_id"]

            # Pin the cooldown to a far-past time so the 429 path does not
            # mask the 409 path.  Any parseable ISO timestamp older than the
            # cooldown window works.  Must clear the in-memory cache too —
            # _check_cooldown prefers it over the DuckDB row.
            webhooks_module._cooldown_ts.pop("poll", None)
            await store.set_metadata(
                "webhook_cooldown:poll", "1970-01-01T00:00:00+00:00"
            )

            second = client.post("/poll", headers=_AUTH_HEADER)
            assert second.status_code == 409, (
                f"Expected 409 while first job in-flight, got {second.status_code}: {second.text}"
            )
            body = second.json()
            assert body["ok"] is False
            assert body["error"] == "job_in_progress"
            assert body["job_id"] == first_job_id

            # Wait for the first job to finish cleanly.
            _wait_for_job(client, first_job_id, timeout_s=3.0)
