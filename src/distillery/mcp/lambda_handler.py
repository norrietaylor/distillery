"""AWS Lambda handler for the Distillery MCP server.

Wraps the FastMCP ASGI application with Mangum so that API Gateway HTTP API
events (payload format v2) are translated into ASGI lifecycle calls and back.

Environment variables used at startup:
    DISTILLERY_HOST          -- ignored in Lambda (Lambda does not bind a port)
    DISTILLERY_PORT          -- ignored in Lambda
    GITHUB_CLIENT_ID         -- GitHub OAuth client ID (when auth.provider=github)
    GITHUB_CLIENT_SECRET     -- GitHub OAuth client secret (when auth.provider=github)
    DISTILLERY_BASE_URL      -- publicly accessible URL of the Lambda / API GW endpoint
    JINA_API_KEY             -- Jina embedding API key
    MOTHERDUCK_TOKEN         -- MotherDuck connection token (if using motherduck backend)
    AWS_ACCESS_KEY_ID        -- AWS credentials forwarded to S3 storage backend
    AWS_SECRET_ACCESS_KEY    -- AWS credentials forwarded to S3 storage backend
    AWS_DEFAULT_REGION       -- AWS region for S3 storage backend

The Lambda function entrypoint is ``distillery.mcp.lambda_handler.handler``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Module-level lazy singletons — populated on first invocation so that the
# module can be imported without any real DB / OAuth credentials available.
_mangum_handler: Any = None


def _build_mangum_handler() -> Any:
    """Build the Mangum-wrapped FastMCP ASGI handler (called once per cold start).

    Reads distillery config, resolves auth, creates the MCP server, wraps the
    resulting Starlette ASGI app with Mangum, and returns the callable handler.

    Returns:
        A Mangum handler callable suitable for use as an AWS Lambda entrypoint.
    """
    from mangum import Mangum

    from distillery.config import load_config
    from distillery.mcp.server import create_server

    config = load_config()

    auth = None
    provider_name = config.server.auth.provider
    if provider_name == "github":
        from distillery.mcp.auth import build_github_auth

        auth = build_github_auth(config)
    elif provider_name == "none":
        logger.warning(
            "Lambda handler starting without authentication "
            "(server.auth.provider is 'none')",
        )
    else:
        raise ValueError(
            f"Unknown auth provider {provider_name!r} for Lambda handler. "
            f"Supported values: 'github', 'none'."
        )

    server = create_server(config=config, auth=auth)
    # FastMCP exposes the underlying Starlette ASGI app via .http_app().
    asgi_app = server.http_app(path="/mcp", stateless_http=True)

    logger.info("Lambda handler initialised — wrapping ASGI app with Mangum")
    return Mangum(asgi_app, lifespan="off")


def handler(event: dict[Any, Any], context: Any) -> dict[Any, Any]:
    """AWS Lambda entrypoint.

    Initialises the Mangum handler on first call (cold start) and delegates
    all subsequent calls to the cached instance.

    Args:
        event:   The raw Lambda event dict from API Gateway HTTP API (v2) or
                 ALB.  Mangum handles both payload format v1 and v2.
        context: The Lambda context object (passed through to Mangum).

    Returns:
        An API Gateway / ALB compatible HTTP response dict with at minimum
        ``statusCode``, ``headers``, and ``body`` keys.
    """
    global _mangum_handler
    if _mangum_handler is None:
        _mangum_handler = _build_mangum_handler()

    logger.debug("Lambda invocation: requestId=%s", getattr(context, "aws_request_id", "n/a"))
    return _mangum_handler(event, context)  # type: ignore[no-any-return]
