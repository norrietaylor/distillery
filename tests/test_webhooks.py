"""Unit and integration tests for webhook authentication, cooldowns, and app composition.

Covers:
- Bearer token authentication (missing, wrong, valid)
- Per-endpoint cooldown enforcement (429 with Retry-After)
- Cooldown persistence via DuckDB get_metadata / set_metadata
- App composition: parent Starlette app mounts both /api/* and /mcp paths
- Webhooks-disabled state: no /api routes when disabled or no secret env var
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from distillery.config import DistilleryConfig, ServerConfig, WebhookConfig
from distillery.mcp.webhooks import create_webhook_app
from distillery.store.duckdb import DuckDBStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "test-webhook-secret-xyz"
_AUTH_HEADER = {"Authorization": f"Bearer {_SECRET}"}


def _make_config(*, enabled: bool = True, secret_env: str = "DISTILLERY_WEBHOOK_SECRET") -> DistilleryConfig:
    """Return a DistilleryConfig with WebhookConfig overrides."""
    return DistilleryConfig(
        server=ServerConfig(
            webhooks=WebhookConfig(enabled=enabled, secret_env=secret_env),
        )
    )


def _make_shared_state(store: DuckDBStore) -> dict[str, Any]:
    """Return a minimal shared-state dict using *store*."""
    return {"store": store, "config": _make_config(), "embedding_provider": None}


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
async def test_auth_valid_token(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST with correct bearer token returns 200 accepted."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/poll", headers=_AUTH_HEADER)

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_cooldown_enforced(store: DuckDBStore, monkeypatch: pytest.MonkeyPatch) -> None:
    """First authenticated request succeeds; immediate second returns 429 with Retry-After."""
    monkeypatch.setenv("DISTILLERY_WEBHOOK_SECRET", _SECRET)
    config = _make_config()
    shared = _make_shared_state(store)
    app = create_webhook_app(shared, config)

    client = TestClient(app, raise_server_exceptions=False)

    # First request: should succeed
    first = client.post("/poll", headers=_AUTH_HEADER)
    assert first.status_code == 200, f"Expected 200 on first request, got {first.status_code}"

    # Immediate second request: must be rejected with 429
    second = client.post("/poll", headers=_AUTH_HEADER)
    assert second.status_code == 429, f"Expected 429 on second request, got {second.status_code}"

    body = second.json()
    assert body["ok"] is False
    assert body["error"] == "too_early"
    assert "retry_after" in body
    assert isinstance(body["retry_after"], int)
    assert body["retry_after"] > 0

    # Retry-After header must also be present
    assert "retry-after" in second.headers
    assert int(second.headers["retry-after"]) > 0


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

    client1 = TestClient(app1, raise_server_exceptions=False)

    # First request triggers cooldown recording in DuckDB.
    resp = client1.post("/poll", headers=_AUTH_HEADER)
    assert resp.status_code == 200

    # Verify the cooldown was actually written to DuckDB.
    cooldown_val = await store.get_metadata("webhook_cooldown:poll")
    assert cooldown_val is not None, "Cooldown timestamp was not persisted to DuckDB"

    # Create a brand-new app instance with a fresh shared_state dict,
    # but pointing at the same underlying store.
    shared2 = _make_shared_state(store)
    app2 = create_webhook_app(shared2, config)
    client2 = TestClient(app2, raise_server_exceptions=False)

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

    client = TestClient(parent, raise_server_exceptions=False)

    # /mcp path should be accessible.
    mcp_resp = client.get("/mcp")
    assert mcp_resp.status_code == 200
    assert mcp_resp.json() == {"mcp": True}

    # /api/poll without auth should return 401 (i.e. the route exists and
    # the webhook app is handling it).
    api_resp = client.post("/api/poll")
    assert api_resp.status_code == 401
    assert api_resp.json()["error"] == "unauthorized"

    # /api/poll with correct auth should return 200.
    api_auth_resp = client.post("/api/poll", headers=_AUTH_HEADER)
    assert api_auth_resp.status_code == 200


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
