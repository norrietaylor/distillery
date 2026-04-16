"""Tests for the distillery_configure MCP tool handler.

Covers validation, range checking, cross-field constraints, in-memory
application, atomic disk persistence, and error paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from distillery.config import (
    ClassificationConfig,
    DefaultsConfig,
    DistilleryConfig,
    EmbeddingConfig,
    FeedsConfig,
    FeedsThresholdsConfig,
    StorageConfig,
)
from distillery.mcp.tools.configure import _handle_configure

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse(result: list[Any]) -> dict[str, Any]:
    """Parse MCP TextContent list into a plain dict."""
    assert len(result) == 1
    return json.loads(result[0].text)  # type: ignore[no-any-return]


def make_config(
    alert: float = 0.85,
    digest: float = 0.60,
    dedup_threshold: float = 0.92,
    confidence_threshold: float = 0.6,
) -> DistilleryConfig:
    return DistilleryConfig(
        storage=StorageConfig(database_path=":memory:"),
        embedding=EmbeddingConfig(provider="", model="stub", dimensions=4),
        defaults=DefaultsConfig(dedup_threshold=dedup_threshold),
        classification=ClassificationConfig(confidence_threshold=confidence_threshold),
        feeds=FeedsConfig(thresholds=FeedsThresholdsConfig(alert=alert, digest=digest)),
    )


# ---------------------------------------------------------------------------
# Validation: required params
# ---------------------------------------------------------------------------


class TestRequiredParams:
    """Missing or invalid required parameters produce INVALID_PARAMS errors."""

    @pytest.mark.asyncio
    async def test_missing_section(self) -> None:
        cfg = make_config()
        result = await _handle_configure(cfg, {"key": "alert", "value": 0.7})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "section" in data["message"]

    @pytest.mark.asyncio
    async def test_missing_key(self) -> None:
        cfg = make_config()
        result = await _handle_configure(cfg, {"section": "feeds.thresholds", "value": 0.7})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "key" in data["message"]

    @pytest.mark.asyncio
    async def test_missing_section_for_read(self) -> None:
        cfg = make_config()
        result = await _handle_configure(cfg, {"key": "alert"})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "section" in data["message"]

    @pytest.mark.asyncio
    async def test_missing_key_for_read(self) -> None:
        cfg = make_config()
        result = await _handle_configure(cfg, {"section": "feeds.thresholds"})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "key" in data["message"]


# ---------------------------------------------------------------------------
# Validation: unknown keys rejected
# ---------------------------------------------------------------------------


class TestUnknownKeys:
    """Unknown (section, key) pairs are rejected by the allowlist."""

    @pytest.mark.asyncio
    async def test_unknown_section(self) -> None:
        cfg = make_config()
        result = await _handle_configure(
            cfg, {"section": "unknown_section", "key": "arbitrary_key", "value": "anything"}
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "not a recognised" in data["message"]

    @pytest.mark.asyncio
    async def test_unknown_key_in_known_section(self) -> None:
        cfg = make_config()
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "nonexistent", "value": 0.5}
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# Validation: range checking
# ---------------------------------------------------------------------------


class TestRangeValidation:
    """Numeric values outside allowed ranges are rejected."""

    @pytest.mark.asyncio
    async def test_alert_above_1(self) -> None:
        cfg = make_config()
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": 1.5}
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "between 0.0 and 1.0" in data["message"]

    @pytest.mark.asyncio
    async def test_alert_below_0(self) -> None:
        cfg = make_config()
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": -0.1}
        )
        data = parse(result)
        assert data["error"] is True

    @pytest.mark.asyncio
    async def test_dedup_limit_below_min(self) -> None:
        cfg = make_config()
        result = await _handle_configure(
            cfg, {"section": "defaults", "key": "dedup_limit", "value": 0}
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_type_coercion_failure(self) -> None:
        cfg = make_config()
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": "not-a-number"}
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "cannot be converted" in data["message"]


# ---------------------------------------------------------------------------
# Validation: cross-field constraints
# ---------------------------------------------------------------------------


class TestCrossFieldConstraints:
    """Cross-field constraints prevent invalid threshold relationships."""

    @pytest.mark.asyncio
    async def test_alert_below_digest_rejected(self) -> None:
        cfg = make_config(alert=0.8, digest=0.5)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": 0.3}
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "alert" in data["message"] and "digest" in data["message"]

    @pytest.mark.asyncio
    async def test_digest_above_alert_rejected(self) -> None:
        cfg = make_config(alert=0.7, digest=0.5)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "digest", "value": 0.9}
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "digest" in data["message"] and "alert" in data["message"]


# ---------------------------------------------------------------------------
# Successful in-memory updates
# ---------------------------------------------------------------------------


class TestInMemoryUpdate:
    """Successful configuration changes update the in-memory config object."""

    @pytest.mark.asyncio
    async def test_update_alert_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ensure no config file is found so we only test in-memory.
        monkeypatch.setattr("distillery.mcp.tools.configure._resolve_config_path", lambda: None)
        cfg = make_config(alert=0.8, digest=0.5)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": 0.7}
        )
        data = parse(result)
        assert data.get("error") is None or data.get("error") is False
        assert data["changed"] is True
        assert data["previous_value"] == 0.8
        assert data["new_value"] == 0.7
        assert cfg.feeds.thresholds.alert == 0.7

    @pytest.mark.asyncio
    async def test_update_digest_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("distillery.mcp.tools.configure._resolve_config_path", lambda: None)
        cfg = make_config(alert=0.8, digest=0.5)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "digest", "value": 0.6}
        )
        data = parse(result)
        assert data["changed"] is True
        assert data["previous_value"] == 0.5
        assert data["new_value"] == 0.6
        assert cfg.feeds.thresholds.digest == 0.6

    @pytest.mark.asyncio
    async def test_update_dedup_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("distillery.mcp.tools.configure._resolve_config_path", lambda: None)
        cfg = make_config(dedup_threshold=0.92)
        result = await _handle_configure(
            cfg, {"section": "defaults", "key": "dedup_threshold", "value": 0.85}
        )
        data = parse(result)
        assert data["changed"] is True
        assert data["previous_value"] == 0.92
        assert data["new_value"] == 0.85
        assert cfg.defaults.dedup_threshold == 0.85

    @pytest.mark.asyncio
    async def test_update_confidence_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("distillery.mcp.tools.configure._resolve_config_path", lambda: None)
        cfg = make_config(confidence_threshold=0.6)
        result = await _handle_configure(
            cfg, {"section": "classification", "key": "confidence_threshold", "value": 0.8}
        )
        data = parse(result)
        assert data["changed"] is True
        assert cfg.classification.confidence_threshold == 0.8

    @pytest.mark.asyncio
    async def test_noop_when_value_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("distillery.mcp.tools.configure._resolve_config_path", lambda: None)
        cfg = make_config(alert=0.85)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": 0.85}
        )
        data = parse(result)
        assert data["changed"] is False
        assert data["previous_value"] == 0.85
        assert data["new_value"] == 0.85


# ---------------------------------------------------------------------------
# Disk persistence
# ---------------------------------------------------------------------------


class TestDiskPersistence:
    """Configuration changes are written atomically to the YAML file."""

    @pytest.mark.asyncio
    async def test_writes_to_yaml_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "feeds": {
                        "thresholds": {"alert": 0.85, "digest": 0.60},
                    },
                }
            )
        )
        monkeypatch.setattr(
            "distillery.mcp.tools.configure._resolve_config_path",
            lambda: config_file,
        )

        cfg = make_config(alert=0.85, digest=0.60)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": 0.7}
        )
        data = parse(result)
        assert data["changed"] is True
        assert data["disk_written"] is True

        # Verify the file on disk was updated.
        reloaded = yaml.safe_load(config_file.read_text())
        assert reloaded["feeds"]["thresholds"]["alert"] == 0.7
        # Digest should be preserved.
        assert reloaded["feeds"]["thresholds"]["digest"] == 0.60

    @pytest.mark.asyncio
    async def test_creates_nested_keys_if_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(yaml.dump({"storage": {"backend": "duckdb"}}))
        monkeypatch.setattr(
            "distillery.mcp.tools.configure._resolve_config_path",
            lambda: config_file,
        )

        cfg = make_config()
        result = await _handle_configure(
            cfg, {"section": "defaults", "key": "stale_days", "value": 60}
        )
        data = parse(result)
        assert data["changed"] is True

        reloaded = yaml.safe_load(config_file.read_text())
        assert reloaded["defaults"]["stale_days"] == 60
        # Original content preserved.
        assert reloaded["storage"]["backend"] == "duckdb"

    @pytest.mark.asyncio
    async def test_reverts_in_memory_on_write_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        config_file = tmp_path / "distillery.yaml"
        config_file.write_text(yaml.dump({"feeds": {"thresholds": {"alert": 0.85}}}))

        monkeypatch.setattr(
            "distillery.mcp.tools.configure._resolve_config_path",
            lambda: config_file,
        )

        # Make the write fail by making _write_config_atomic raise.
        def _boom(path: Path, data: dict[str, Any]) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("distillery.mcp.tools.configure._write_config_atomic", _boom)

        cfg = make_config(alert=0.85)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": 0.7}
        )
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INTERNAL"
        # In-memory should be reverted.
        assert cfg.feeds.thresholds.alert == 0.85

    @pytest.mark.asyncio
    async def test_no_config_file_returns_in_memory_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("distillery.mcp.tools.configure._resolve_config_path", lambda: None)
        cfg = make_config(alert=0.85)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": 0.7}
        )
        data = parse(result)
        assert data["changed"] is True
        assert data["disk_written"] is False
        assert "in-memory only" in data["message"]


# ---------------------------------------------------------------------------
# String value coercion
# ---------------------------------------------------------------------------


class TestValueCoercion:
    """String values from MCP are coerced to the correct type."""

    @pytest.mark.asyncio
    async def test_string_to_float(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("distillery.mcp.tools.configure._resolve_config_path", lambda: None)
        cfg = make_config(alert=0.85)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": "0.7"}
        )
        data = parse(result)
        assert data["changed"] is True
        assert data["new_value"] == 0.7
        assert cfg.feeds.thresholds.alert == 0.7

    @pytest.mark.asyncio
    async def test_string_to_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("distillery.mcp.tools.configure._resolve_config_path", lambda: None)
        cfg = make_config()
        result = await _handle_configure(
            cfg, {"section": "defaults", "key": "dedup_limit", "value": "5"}
        )
        data = parse(result)
        assert data["changed"] is True
        assert data["new_value"] == 5
        assert cfg.defaults.dedup_limit == 5


# ---------------------------------------------------------------------------
# Read-only mode (value omitted)
# ---------------------------------------------------------------------------


class TestReadOnlyMode:
    """When value is omitted (None), return the current config value."""

    @pytest.mark.asyncio
    async def test_read_alert_threshold(self) -> None:
        cfg = make_config(alert=0.9, digest=0.5)
        result = await _handle_configure(cfg, {"section": "feeds.thresholds", "key": "alert"})
        data = parse(result)
        assert data.get("error") is None or data.get("error") is False
        assert data["section"] == "feeds.thresholds"
        assert data["key"] == "alert"
        assert data["value"] == 0.9
        assert "0.9" in data["message"]

    @pytest.mark.asyncio
    async def test_read_digest_threshold(self) -> None:
        cfg = make_config(alert=0.85, digest=0.65)
        result = await _handle_configure(cfg, {"section": "feeds.thresholds", "key": "digest"})
        data = parse(result)
        assert data["value"] == 0.65

    @pytest.mark.asyncio
    async def test_read_dedup_threshold(self) -> None:
        cfg = make_config(dedup_threshold=0.88)
        result = await _handle_configure(cfg, {"section": "defaults", "key": "dedup_threshold"})
        data = parse(result)
        assert data["value"] == 0.88

    @pytest.mark.asyncio
    async def test_read_confidence_threshold(self) -> None:
        cfg = make_config(confidence_threshold=0.7)
        result = await _handle_configure(
            cfg, {"section": "classification", "key": "confidence_threshold"}
        )
        data = parse(result)
        assert data["value"] == 0.7

    @pytest.mark.asyncio
    async def test_read_unknown_key_rejected(self) -> None:
        cfg = make_config()
        result = await _handle_configure(cfg, {"section": "feeds.thresholds", "key": "nonexistent"})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"
        assert "not a recognised" in data["message"]

    @pytest.mark.asyncio
    async def test_read_unknown_section_rejected(self) -> None:
        cfg = make_config()
        result = await _handle_configure(cfg, {"section": "bogus", "key": "whatever"})
        data = parse(result)
        assert data["error"] is True
        assert data["code"] == "INVALID_PARAMS"

    @pytest.mark.asyncio
    async def test_read_does_not_mutate_config(self) -> None:
        cfg = make_config(alert=0.85)
        await _handle_configure(cfg, {"section": "feeds.thresholds", "key": "alert"})
        assert cfg.feeds.thresholds.alert == 0.85

    @pytest.mark.asyncio
    async def test_read_with_explicit_none_value(self) -> None:
        cfg = make_config(alert=0.85)
        result = await _handle_configure(
            cfg, {"section": "feeds.thresholds", "key": "alert", "value": None}
        )
        data = parse(result)
        assert data.get("error") is None or data.get("error") is False
        assert data["value"] == 0.85
