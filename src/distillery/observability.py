"""OpenTelemetry / Pydantic Logfire instrumentation for the Distillery MCP server.

Config-gated and import-guarded: the server behaves identically when the
optional ``[otel]`` extra is absent or when no telemetry environment variables
are set. Activation is purely operational — set ``LOGFIRE_TOKEN`` and/or
``OTEL_EXPORTER_OTLP_ENDPOINT`` in the deployment environment.

When active, Logfire is configured as the OTLP SDK. If an OTLP endpoint is
given, the same spans are *dual-exported* to that collector (e.g. the GCP
Cloud Run ``otel-collector``) via an additional span processor, so traces land
in both Logfire and the collector's backend (Cloud Trace) without any further
application change.

Auto-instrumentation captures the high-value signals with no changes to the
hot paths:

* ``instrument_mcp`` — one span per MCP ``tools/call`` (per-skill round-trip
  count + per-call latency fall out of this).
* ``instrument_httpx`` — every outbound HTTP call, i.e. the Jina embedding
  round-trips and the GitHub auth/sync calls, with duration.
* ``instrument_system_metrics`` — host/runtime metrics including event-loop
  signals (the starvation signal during feed polls).
* ``instrument_asgi`` (via :func:`instrument_asgi_app`) — one span per HTTP
  request, capturing ``X-Request-ID`` for log<->trace correlation.

DuckDB and NetworkX have no OTel instrumentor; :func:`span` is the seam for the
store/graph cost-centre spans (added separately).
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
    """True when telemetry env is present (Logfire token or an OTLP endpoint)."""
    return bool(
        os.environ.get("LOGFIRE_TOKEN")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )


def _resolve_version() -> str:
    try:
        from importlib.metadata import version

        return version("distillery-mcp")
    except Exception:  # noqa: BLE001 — version is best-effort metadata only
        return "dev"


def _otlp_span_processor() -> Any | None:
    """Build a BatchSpanProcessor over an OTLP/HTTP exporter, or None.

    The exporter reads ``OTEL_EXPORTER_OTLP_ENDPOINT`` / ``_TRACES_ENDPOINT``
    and ``OTEL_EXPORTER_OTLP_HEADERS`` (e.g. ``Authorization=Bearer <secret>``)
    from the standard OTel env contract, so no credentials live in code.
    """
    if not (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    ):
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    return BatchSpanProcessor(OTLPSpanExporter())


def configure_observability() -> bool:
    """Configure Logfire + optional OTLP dual-export when telemetry env is set.

    Returns ``True`` when instrumentation was activated, ``False`` otherwise
    (disabled by env, or the ``[otel]`` extra is not installed). Idempotent and
    defensive — any failure is logged and swallowed so telemetry setup can
    never take down the server.
    """
    global _configured
    if _configured:
        return True
    if not observability_enabled():
        return False
    try:
        import logfire

        send_to_logfire = bool(os.environ.get("LOGFIRE_TOKEN"))
        processors = [p for p in (_otlp_span_processor(),) if p is not None]
        logfire.configure(
            service_name=_SERVICE_NAME,
            service_version=_resolve_version(),
            environment=os.environ.get("DISTILLERY_ENV"),
            send_to_logfire="if-token-present",
            console=False,
            distributed_tracing=True,
            additional_span_processors=processors or None,
        )
        logfire.instrument_mcp()
        logfire.instrument_httpx()
        logfire.instrument_system_metrics()
    except ImportError:
        logger.warning(
            "Telemetry env is set but the [otel] extra is not installed; "
            "skipping instrumentation. Install distillery-mcp[otel] to enable."
        )
        return False
    except Exception:  # noqa: BLE001 — never let telemetry setup crash the server
        logger.exception("Observability configuration failed; continuing without it")
        return False

    _configured = True
    logger.info(
        "Observability configured (logfire=%s, otlp_dual_export=%s)",
        send_to_logfire,
        bool(processors),
    )
    return True


def instrument_asgi_app(app: ASGIApp) -> ASGIApp:
    """Wrap an ASGI app with per-request spans when instrumentation is active.

    ``capture_headers=True`` records request/response headers, including
    ``X-Request-ID``, on the request span for log<->trace correlation. A no-op
    pass-through when observability is disabled.
    """
    if not _configured:
        return app
    import logfire

    # logfire/OTel type their ASGI alias differently from Starlette's; the
    # runtime shape is identical (ASGI3 callable), so bridge with a cast.
    wrapped = logfire.instrument_asgi(cast(Any, app), capture_headers=True)
    return cast("ASGIApp", wrapped)


def span(name: str, **attributes: Any) -> AbstractContextManager[Any]:
    """Cost-centre span seam for code with no OTel auto-instrumentor (DuckDB,
    NetworkX). Returns a Logfire span when active, else a cheap no-op context.
    """
    if not _configured:
        return nullcontext()
    import logfire

    return logfire.span(name, **attributes)
