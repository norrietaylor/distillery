"""Entry point for the Distillery MCP server.

Run with:
    python -m distillery.mcp

Or via the CLI entry point:
    distillery-mcp

The server communicates over stdio (default) or streamable-HTTP using the MCP
protocol and exposes Distillery storage operations as tools to any connected
MCP client (e.g. Claude Code).

Usage:
    distillery-mcp                          # stdio mode (default)
    distillery-mcp --transport stdio        # explicit stdio mode
    distillery-mcp --transport http         # HTTP mode, default host/port
    distillery-mcp --transport http --host 127.0.0.1 --port 9000

Exit codes:
    0   -- server exited cleanly
    1   -- startup or runtime error
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys


def _configure_logging() -> None:
    """Configure logging to stderr so it does not interfere with stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        stream=sys.stderr,
    )
    # Attach secret redaction filter to prevent API keys leaking into logs.
    from distillery.security import SecretRedactFilter

    logging.getLogger("distillery").addFilter(SecretRedactFilter())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:] when ``None``).

    Returns:
        Parsed :class:`argparse.Namespace`.
    """
    parser = argparse.ArgumentParser(
        prog="distillery-mcp",
        description="Start the Distillery MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help=(
            "Transport protocol to use. 'stdio' (default) for local use; "
            "'http' for persistent streamable-HTTP endpoint."
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help=(
            "Bind address for HTTP transport (default: %(default)s). "
            "Falls back to DISTILLERY_HOST env var, then '0.0.0.0'."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Bind port for HTTP transport (default: %(default)s). "
            "Falls back to DISTILLERY_PORT env var, then 8000."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Start the Distillery MCP server and run it until completion or interruption.

    When ``--transport http`` is supplied the server binds as a persistent
    streamable-HTTP endpoint.  The default (or ``--transport stdio``) keeps
    the original stdio behaviour unchanged.

    Args:
        argv: Argument list forwarded to :func:`_parse_args`.  Defaults to
            ``sys.argv[1:]`` when ``None``.

    Returns:
        Exit code: ``0`` on successful exit or interruption, ``1`` on error.
    """

    # Convert SIGTERM into KeyboardInterrupt so the FastMCP lifespan
    # finally-block runs and DuckDBStore.close() can CHECKPOINT the WAL.
    # Fly.io sends SIGTERM on scale-to-zero; without this conversion the
    # process exits immediately and the WAL may be left dirty on disk.
    def _sigterm_handler(signum: int, frame: object) -> None:  # pragma: no cover
        raise KeyboardInterrupt

    _configure_logging()
    logger = logging.getLogger(__name__)

    signal.signal(signal.SIGTERM, _sigterm_handler)

    args = _parse_args(argv)

    try:
        from distillery.config import load_config
        from distillery.mcp.server import create_server

        config = load_config()

        if args.transport == "http":
            host = (
                args.host if args.host is not None else os.environ.get("DISTILLERY_HOST", "0.0.0.0")
            )
            port_env = os.environ.get("DISTILLERY_PORT")
            port = args.port if args.port is not None else (int(port_env) if port_env else 8000)

            auth = None
            org_checker = None
            provider_name = config.server.auth.provider
            if provider_name == "github":
                from distillery.mcp.auth import (
                    _patch_cimd_localhost_redirect,
                    build_github_auth,
                    build_org_checker,
                )

                _patch_cimd_localhost_redirect()
                org_checker = build_org_checker(config)
                auth = build_github_auth(config, org_checker=org_checker)

                # Pre-register Claude Code so the server never needs to
                # fetch the CIMD document from claude.ai at runtime (the
                # fetch fails on Fly machines whose egress IP is
                # Cloudflare-challenged).
                from distillery.mcp.auth import pre_register_claude_code_client

                asyncio.run(pre_register_claude_code_client(auth))
            elif provider_name == "none":
                logger.warning(
                    "HTTP server running without authentication (server.auth.provider is 'none')",
                )
            else:
                raise ValueError(
                    f"Unknown auth provider {provider_name!r} for HTTP transport. "
                    f"Supported values: 'github', 'none'."
                )

            server = create_server(config=config, auth=auth)

            # Wire up audit logging for auth events.  The callback lazily
            # reads the store from the server's shared state so it works
            # even though the store is only initialised at first request.
            _shared_ref = server._distillery_shared  # type: ignore[attr-defined]
            _shared_ref["transport"] = "http"

            async def _auth_audit_cb(
                user_id: str,
                operation: str,
                entry_id: str,
                action: str,
                outcome: str,
            ) -> None:
                store = _shared_ref.get("store")
                if store is None:
                    return
                await store.write_audit_log(user_id, operation, entry_id, action, outcome)

            # Attach callback to auth provider (if org-restricted).
            from distillery.mcp.auth import OrgRestrictedGitHubProvider

            if isinstance(auth, OrgRestrictedGitHubProvider):
                auth._audit_callback = _auth_audit_cb
            http_app = server.http_app(
                path="/mcp",
                transport="streamable-http",
                stateless_http=True,
            )

            # Wrap ASGI app with rate limiting and body size middleware.
            rl = config.server.http_rate_limit
            from distillery.mcp.middleware import apply_http_middleware

            wrapped_app = apply_http_middleware(
                http_app,
                requests_per_minute=rl.requests_per_minute,
                requests_per_hour=rl.requests_per_hour,
                max_body_bytes=rl.max_body_bytes,
                trust_proxy=rl.trust_proxy,
                org_checker=org_checker,
                audit_callback=_auth_audit_cb,
            )

            from starlette.types import ASGIApp, Receive, Scope, Send

            final_app: ASGIApp = wrapped_app
            if config.server.webhooks.enabled and os.environ.get(config.server.webhooks.secret_env):
                from distillery.mcp.middleware import BodySizeLimitMiddleware
                from distillery.mcp.webhooks import create_webhook_app

                webhook_app: ASGIApp = create_webhook_app(
                    server._distillery_shared,  # type: ignore[attr-defined]
                    config,
                )
                # Apply the same body-size guard as the MCP endpoint.
                webhook_app = BodySizeLimitMiddleware(webhook_app, max_bytes=rl.max_body_bytes)

                # Route /api/* to webhooks, everything else to MCP.
                # Uses a thin ASGI dispatcher instead of Starlette Mount so
                # that lifespan events propagate naturally to wrapped_app
                # (which contains the FastMCP lifespan via middleware chain).
                _mcp_app = wrapped_app

                async def _combined_app(scope: Scope, receive: Receive, send: Send) -> None:
                    if scope["type"] == "http" and scope.get("path", "").startswith("/api/"):
                        # Strip /api prefix for the webhook app's routes.
                        scope = dict(scope)
                        scope["path"] = scope["path"][4:]  # /api/poll -> /poll
                        raw = scope.get("root_path", "")
                        scope["root_path"] = raw + "/api"
                        await webhook_app(scope, receive, send)
                    else:
                        await _mcp_app(scope, receive, send)

                final_app = _combined_app

            import uvicorn as _uvicorn

            uv_config = _uvicorn.Config(
                app=final_app,
                host=host,
                port=port,
                log_level="info",
            )
            uv_server = _uvicorn.Server(uv_config)
            uv_server.run()
        else:
            server = create_server(config=config)
            server._distillery_shared["transport"] = "stdio"  # type: ignore[attr-defined]
            asyncio.run(server.run_stdio_async(show_banner=False))

        return 0
    except KeyboardInterrupt:
        logger.info("Distillery MCP server interrupted")
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("Distillery MCP server failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
