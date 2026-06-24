"""Observability is dark by default and degrades safely.

These tests must pass without the optional ``[otel]`` extra installed: every
assertion exercises the disabled path, which never imports logfire.
"""

import pytest

from distillery import observability


@pytest.fixture(autouse=True)
def _clear_otel_env(monkeypatch):
    """Ensure no telemetry env leaks in from the host, and reset module state."""
    for var in (
        "LOGFIRE_TOKEN",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(observability, "_configured", False)


def test_disabled_with_no_env():
    assert observability.observability_enabled() is False
    assert observability.configure_observability() is False
    assert observability._configured is False


@pytest.mark.parametrize("var", ["LOGFIRE_TOKEN", "OTEL_EXPORTER_OTLP_ENDPOINT"])
def test_enabled_flag_tracks_env(monkeypatch, var):
    monkeypatch.setenv(var, "x")
    assert observability.observability_enabled() is True


def test_traces_only_endpoint_does_not_enable(monkeypatch):
    """A traces-only OTLP endpoint is not a standalone trigger: logfire exports
    metrics only for the generic endpoint, so we require it (avoids collecting
    metrics that export nowhere)."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://x/v1/traces")
    assert observability.observability_enabled() is False


def test_resolve_version_returns_str():
    assert isinstance(observability._resolve_version(), str)


def test_configure_is_idempotent_when_already_configured(monkeypatch):
    monkeypatch.setattr(observability, "_configured", True)
    assert observability.configure_observability() is True


def test_span_is_noop_when_disabled():
    with observability.span("db.embed", embed_ms=1) as s:
        assert s is None  # nullcontext yields None


def test_instrument_asgi_app_passthrough_when_disabled():
    sentinel = object()
    assert observability.instrument_asgi_app(sentinel) is sentinel


def test_configure_without_extra_is_safe(monkeypatch):
    """With env set but the extra absent, configure must not raise and returns
    False. Simulate the missing extra by forcing the logfire import to fail."""
    monkeypatch.setenv("LOGFIRE_TOKEN", "x")
    import builtins

    real_import = builtins.__import__

    def _fail_logfire(name, *args, **kwargs):
        if name == "logfire" or name.startswith("logfire."):
            raise ImportError("no logfire")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_logfire)
    assert observability.configure_observability() is False
    assert observability._configured is False
