"""OpenTelemetry / Pydantic Logfire instrumentation for the Distillery MCP server.

Config-gated and import-guarded: the server behaves identically when the
optional ``[otel]`` extra is absent or when no telemetry environment variables
are set. Activation is operational — set ``LOGFIRE_TOKEN`` (send to Logfire)
and/or ``OTEL_EXPORTER_OTLP_ENDPOINT`` (export to a self-hosted OTLP collector,
e.g. the GCP Cloud Run ``otel-collector``).

Dual-export is provided by Logfire itself: ``logfire.configure()`` honours the
standard ``OTEL_EXPORTER_OTLP_*`` env contract and exports **both traces and
metrics** to that collector, and additionally sends to Logfire when
``LOGFIRE_TOKEN`` is set. No manual span processor is added — logfire 4.x wires
the OTLP exporter from the env on its own (a manual one would double-export).
The generic ``OTEL_EXPORTER_OTLP_ENDPOINT`` is required for collector export
because logfire only attaches the OTLP *metric* reader for the generic/metrics
endpoint, not a traces-only one.

Auto-instrumentation captures the high-value signals with no hot-path changes:

* ``instrument_mcp`` — one span per MCP ``tools/call`` (per-skill round-trip
  count + per-call latency).
* ``instrument_httpx`` — every outbound HTTP call (the Jina embedding round-trips
  and the GitHub auth/sync calls), with duration. Credentials travel in headers,
  which are not captured.
* ``instrument_system_metrics`` — host/runtime CPU, memory and swap utilisation.
* ``instrument_asgi`` (via :func:`instrument_asgi_app`) — one span per HTTP
  request (method, route, status, duration). Headers are not captured.

DuckDB and NetworkX have no OTel instrumentor; :func:`span` is the seam for the
store/graph cost-centre spans (added separately).

Secret safety: Logfire's default scrubber redacts secret-shaped attributes
(authorization, api-key, token, cookie, ...) and runs upstream of the OTLP
fan-out, so secrets are redacted on both the Logfire and collector paths.
"""

from __future__ import annotations

import logging
import os
from contextlib import AbstractContextManager, nullcontext
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

_SERVICE_NAME = "distillery-mcp"
_configured = False


def observability_enabled() -> bool:
    """True when telemetry env is present: a Logfire token, or the generic OTLP
    endpoint (which enables both trace and metric export in logfire)."""
    return bool(os.environ.get("LOGFIRE_TOKEN") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _resolve_version() -> str:
    try:
        from importlib.metadata import version

        return version("distillery-mcp")
    except Exception:  # noqa: BLE001 — version is best-effort metadata only
        return "dev"


def configure_observability() -> bool:
    """Configure Logfire (with env-driven OTLP dual-export) when telemetry env
    is set. Returns ``True`` when activated, ``False`` otherwise (disabled, or
    the ``[otel]`` extra is absent). Idempotent and defensive — any failure is
    logged and swallowed so telemetry setup can never take down the server.
    """
    global _configured
    if _configured:
        return True
    if not observability_enabled():
        return False
    try:
        import logfire
    except ImportError:
        logger.warning(
            "Telemetry env is set but the [otel] extra is not installed; "
            "skipping instrumentation. Install distillery-mcp[otel] to enable."
        )
        return False

    logfire_token_present = bool(os.environ.get("LOGFIRE_TOKEN"))
    try:
        # logfire honours OTEL_EXPORTER_OTLP_ENDPOINT / OTEL_EXPORTER_OTLP_HEADERS
        # itself, so no additional_span_processors are needed (one would
        # double-export every span).
        logfire.configure(
            service_name=_SERVICE_NAME,
            service_version=_resolve_version(),
            environment=os.environ.get("DISTILLERY_ENV"),
            send_to_logfire="if-token-present",
            console=False,
            distributed_tracing=True,
        )
    except Exception:  # noqa: BLE001 — never let telemetry setup crash the server
        logger.exception("logfire.configure failed; continuing without telemetry")
        return False

    # The TracerProvider is live once configure() returns; mark active before
    # the instrumentors run so one instrumentor failing (e.g. a missing
    # sub-extra after a dependency bump) degrades only that signal instead of
    # leaving live exporter threads while the module reports telemetry "off".
    _configured = True
    for name, instrument in (
        ("mcp", logfire.instrument_mcp),
        ("httpx", logfire.instrument_httpx),
        ("system_metrics", logfire.instrument_system_metrics),
    ):
        try:
            instrument()
        except Exception:  # noqa: BLE001
            logger.warning(
                "logfire.instrument_%s failed; that signal is disabled", name, exc_info=True
            )

    logger.info(
        "Observability configured (logfire=%s, otlp_endpoint=%s)",
        logfire_token_present,
        bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")),
    )
    return True


def instrument_asgi_app(app: ASGIApp) -> ASGIApp:
    """Wrap an ASGI app with per-request spans (method, route, status, duration)
    when instrumentation is active. Headers are not captured, so neither the
    (scrubbed) Authorization token nor the client IP is exported to the trace
    backends. A no-op pass-through when observability is disabled.
    """
    if not _configured:
        return app
    try:
        import logfire

        # logfire/OTel type their ASGI alias differently from Starlette's; the
        # runtime shape is identical (ASGI3 callable), so bridge with a cast.
        return cast("ASGIApp", logfire.instrument_asgi(cast(Any, app)))
    except Exception:  # noqa: BLE001
        logger.warning("logfire.instrument_asgi failed; request spans disabled", exc_info=True)
        return app


def span(name: str, **attributes: Any) -> AbstractContextManager[Any]:
    """Cost-centre span seam for code with no OTel auto-instrumentor (DuckDB,
    NetworkX). Returns a Logfire span when active, else a cheap no-op context.
    """
    if not _configured:
        return nullcontext()
    import logfire

    return cast("AbstractContextManager[Any]", logfire.span(name, **attributes))
