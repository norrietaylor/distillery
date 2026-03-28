"""Unit tests for distillery.mcp.lambda_handler.

Tests verify:
- The ``handler`` function is importable and callable.
- Invoked with a mock API Gateway HTTP event, it returns a dict with a
  ``statusCode`` key.
- The lazy initialisation path is exercised via patching so no real DB or
  embedding connection is required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import distillery.mcp.lambda_handler as lambda_handler_mod

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_apigw_event(
    method: str = "GET",
    path: str = "/health",
    body: str = "",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a minimal API Gateway HTTP API (v2) event dict.

    See: https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html
    """
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "rawQueryString": "",
        "headers": headers or {"accept": "application/json"},
        "requestContext": {
            "http": {
                "method": method,
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "requestId": "test-request-id",
            "routeKey": f"{method} {path}",
            "stage": "$default",
        },
        "body": body,
        "isBase64Encoded": False,
    }


class _FakeLambdaContext:
    """Minimal Lambda context stand-in."""

    aws_request_id = "test-context-id"
    function_name = "distillery-mcp"
    memory_limit_in_mb = 512


# Canonical fake response returned by our mock Mangum handler.
FAKE_RESPONSE: dict[str, Any] = {
    "statusCode": 200,
    "headers": {"content-type": "application/json"},
    "body": '{"status": "ok"}',
    "isBase64Encoded": False,
}


@pytest.fixture(autouse=True)
def reset_mangum_handler() -> Any:
    """Reset the module-level cached handler before and after each test."""
    original = lambda_handler_mod._mangum_handler
    lambda_handler_mod._mangum_handler = None
    yield
    lambda_handler_mod._mangum_handler = original


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLambdaHandlerModule:
    """Tests that exercise the lambda_handler module with mocked internals."""

    def _make_mock_mangum_handler(self) -> MagicMock:
        """Return a mock callable that returns FAKE_RESPONSE."""
        return MagicMock(return_value=FAKE_RESPONSE)

    def test_handler_is_callable(self) -> None:
        """handler() exists and is callable."""
        assert callable(lambda_handler_mod.handler)

    def test_handler_returns_response(self) -> None:
        """handler() returns a dict with a statusCode key."""
        mock_mgm = self._make_mock_mangum_handler()
        with patch.object(lambda_handler_mod, "_build_mangum_handler", return_value=mock_mgm):
            event = _make_apigw_event("GET", "/health")
            ctx = _FakeLambdaContext()
            response = lambda_handler_mod.handler(event, ctx)

        assert isinstance(response, dict), "handler must return a dict"
        assert "statusCode" in response, "response must contain 'statusCode'"

    def test_handler_delegates_to_mangum(self) -> None:
        """handler() delegates to the Mangum-wrapped ASGI app."""
        mock_mgm = self._make_mock_mangum_handler()
        with patch.object(lambda_handler_mod, "_build_mangum_handler", return_value=mock_mgm):
            event = _make_apigw_event("GET", "/mcp")
            ctx = _FakeLambdaContext()
            response = lambda_handler_mod.handler(event, ctx)

        mock_mgm.assert_called_once_with(event, ctx)
        assert response == FAKE_RESPONSE

    def test_handler_returns_200_for_health(self) -> None:
        """handler() returns status 200 for a GET /health event."""
        mock_mgm = self._make_mock_mangum_handler()
        with patch.object(lambda_handler_mod, "_build_mangum_handler", return_value=mock_mgm):
            event = _make_apigw_event("GET", "/health")
            ctx = _FakeLambdaContext()
            response = lambda_handler_mod.handler(event, ctx)

        assert response["statusCode"] == 200

    def test_handler_response_body_is_valid_json_with_status(self) -> None:
        """handler() response body is valid JSON containing a 'status' field."""
        import json

        mock_mgm = self._make_mock_mangum_handler()
        with patch.object(lambda_handler_mod, "_build_mangum_handler", return_value=mock_mgm):
            event = _make_apigw_event("GET", "/health")
            ctx = _FakeLambdaContext()
            response = lambda_handler_mod.handler(event, ctx)

        body = response.get("body", "")
        parsed = json.loads(body)
        assert "status" in parsed

    def test_handler_caches_mangum_instance(self) -> None:
        """_build_mangum_handler() is called once even with multiple invocations."""
        mock_mgm = self._make_mock_mangum_handler()
        with patch.object(
            lambda_handler_mod, "_build_mangum_handler", return_value=mock_mgm
        ) as mock_build:
            event = _make_apigw_event("GET", "/health")
            ctx = _FakeLambdaContext()
            lambda_handler_mod.handler(event, ctx)
            lambda_handler_mod.handler(event, ctx)

        mock_build.assert_called_once()
        assert mock_mgm.call_count == 2
