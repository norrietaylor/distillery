"""Configuration tool handler for the Distillery MCP server.

Implements the ``distillery_configure`` tool that allows runtime
configuration changes via MCP, writing updates atomically to the
YAML config file on disk while also patching the in-memory config.

When ``value`` is omitted (None), the tool operates in read-only mode
and returns the current value for the given section+key.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from mcp import types

from distillery.config import (
    DistilleryConfig,
    _find_config_path,
)
from distillery.mcp.tools._common import error_response, success_response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlist of configurable keys
# ---------------------------------------------------------------------------

# Maps (section, key) to a spec dict with keys:
#   "type" -- expected Python type (float or int)
#   "range" -- optional (min, max) for numeric values
#   "constraint" -- optional callable(config, new_value) -> error_msg | None
_ALLOWED_KEYS: dict[tuple[str, str], dict[str, Any]] = {
    ("feeds.thresholds", "alert"): {
        "type": float,
        "range": (0.0, 1.0),
        "constraint": lambda cfg, val: (
            f"alert ({val}) must be >= digest ({cfg.feeds.thresholds.digest})"
            if val < cfg.feeds.thresholds.digest
            else None
        ),
    },
    ("feeds.thresholds", "digest"): {
        "type": float,
        "range": (0.0, 1.0),
        "constraint": lambda cfg, val: (
            f"digest ({val}) must be <= alert ({cfg.feeds.thresholds.alert})"
            if val > cfg.feeds.thresholds.alert
            else None
        ),
    },
    ("defaults", "dedup_threshold"): {
        "type": float,
        "range": (0.0, 1.0),
    },
    ("defaults", "dedup_limit"): {
        "type": int,
        "range": (1, 100),
    },
    ("defaults", "stale_days"): {
        "type": int,
        "range": (1, 3650),
    },
    ("classification", "confidence_threshold"): {
        "type": float,
        "range": (0.0, 1.0),
    },
    ("classification", "mode"): {
        "type": str,
        "constraint": lambda _cfg, val: (
            f"classification.mode must be 'llm' or 'heuristic', got {val!r}"
            if val not in ("llm", "heuristic")
            else None
        ),
    },
}


def _coerce_value(raw_value: str | int | float, target_type: type) -> Any:
    """Coerce *raw_value* to *target_type*, raising ValueError on failure."""
    if target_type is float:
        return float(raw_value)
    if target_type is int:
        int_val = int(raw_value)
        if isinstance(raw_value, float) and raw_value != int_val:
            raise ValueError(f"Cannot losslessly convert {raw_value} to int")
        return int_val
    return raw_value  # pragma: no cover


def _get_nested(obj: Any, dotted_section: str, key: str) -> Any:
    """Read a value from a dataclass hierarchy using dotted path + key."""
    current = obj
    for part in dotted_section.split("."):
        current = getattr(current, part)
    return getattr(current, key)


def _set_nested(obj: Any, dotted_section: str, key: str, value: Any) -> None:
    """Set a value on a dataclass hierarchy using dotted path + key."""
    current = obj
    for part in dotted_section.split("."):
        current = getattr(current, part)
    setattr(current, key, value)


def _set_nested_dict(d: dict[str, Any], dotted_section: str, key: str, value: Any) -> None:
    """Set a value in a nested dict using dotted path + key, creating intermediates."""
    current = d
    for part in dotted_section.split("."):
        if part not in current:
            current[part] = {}
        current = current[part]
    current[key] = value


def _resolve_config_path() -> Path | None:
    """Resolve the config file path using the same logic as load_config."""
    return _find_config_path()


def _write_config_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write YAML config to *path* atomically via temp-file + rename."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, sort_keys=False)
        os.replace(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on any error.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


async def _handle_configure(
    config: DistilleryConfig,
    arguments: dict[str, Any],
) -> list[types.TextContent]:
    """Handle the ``distillery_configure`` tool.

    Validates the requested configuration change, applies it to the in-memory
    config, and writes the update atomically to the YAML config file on disk.

    Args:
        config: The live in-memory :class:`DistilleryConfig` instance.
        arguments: Parsed tool arguments with ``section``, ``key``, ``value``.

    Returns:
        A structured MCP success or error response.
    """
    section = arguments.get("section")
    key = arguments.get("key")
    value = arguments.get("value")

    # --- Validate required params ---
    if not section or not isinstance(section, str):
        return error_response(
            "INVALID_PARAMS",
            "Parameter 'section' is required and must be a non-empty string.",
        )
    if not key or not isinstance(key, str):
        return error_response(
            "INVALID_PARAMS",
            "Parameter 'key' is required and must be a non-empty string.",
        )

    # --- Read-only mode: value omitted ---
    if value is None:
        spec = _ALLOWED_KEYS.get((section, key))
        if spec is None:
            return error_response(
                "INVALID_PARAMS",
                f"Configuration key '{section}.{key}' is not a recognised configurable key. "
                f"Allowed keys: "
                f"{', '.join(f'{s}.{k}' for s, k in sorted(_ALLOWED_KEYS))}.",
            )
        try:
            current = _get_nested(config, section, key)
        except AttributeError:
            return error_response(
                "INTERNAL",
                f"Unable to read current value for '{section}.{key}'.",
            )
        return success_response(
            {
                "section": section,
                "key": key,
                "value": current,
                "message": f"Current value of {section}.{key} is {current}",
            }
        )

    # --- Check allowlist ---
    spec = _ALLOWED_KEYS.get((section, key))
    if spec is None:
        return error_response(
            "INVALID_PARAMS",
            f"Configuration key '{section}.{key}' is not a recognised configurable key. "
            f"Allowed keys: {', '.join(f'{s}.{k}' for s, k in sorted(_ALLOWED_KEYS))}.",
        )

    # --- Coerce value ---
    target_type = spec["type"]
    try:
        coerced = _coerce_value(value, target_type)
    except (TypeError, ValueError):
        return error_response(
            "INVALID_PARAMS",
            f"Value {value!r} cannot be converted to {target_type.__name__}.",
        )

    # --- Range validation ---
    val_range = spec.get("range")
    if val_range is not None:
        lo, hi = val_range
        if not (lo <= coerced <= hi):
            return error_response(
                "INVALID_PARAMS",
                f"Value {coerced} for '{section}.{key}' must be between {lo} and {hi}.",
            )

    # --- Cross-field constraint ---
    constraint = spec.get("constraint")
    if constraint is not None:
        err_msg = constraint(config, coerced)
        if err_msg is not None:
            return error_response("INVALID_PARAMS", err_msg)

    # --- Read previous value ---
    try:
        previous = _get_nested(config, section, key)
    except AttributeError:
        return error_response(
            "INTERNAL",
            f"Unable to read current value for '{section}.{key}'.",
        )

    if coerced == previous:
        return success_response(
            {
                "changed": False,
                "section": section,
                "key": key,
                "previous_value": previous,
                "new_value": coerced,
                "message": "Value unchanged.",
            }
        )

    # --- Apply to in-memory config ---
    try:
        _set_nested(config, section, key, coerced)
    except AttributeError:
        return error_response(
            "INTERNAL",
            f"Unable to set value for '{section}.{key}'.",
        )

    # --- Persist to disk ---
    config_path = _resolve_config_path()
    disk_written = False
    if config_path is not None:
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw_yaml: dict[str, Any] = yaml.safe_load(fh) or {}
            _set_nested_dict(raw_yaml, section, key, coerced)
            _write_config_atomic(config_path, raw_yaml)
            disk_written = True
            logger.info(
                "Configuration updated: %s.%s = %r (was %r), written to %s",
                section,
                key,
                coerced,
                previous,
                config_path,
            )
        except Exception:
            # Revert in-memory change on disk-write failure.
            _set_nested(config, section, key, previous)
            logger.exception(
                "Failed to write config to %s — in-memory change reverted",
                config_path,
            )
            return error_response(
                "INTERNAL",
                f"Failed to write configuration to {config_path}. "
                "In-memory change has been reverted.",
            )
    else:
        logger.info(
            "Configuration updated in-memory: %s.%s = %r (was %r). "
            "No config file found on disk to persist.",
            section,
            key,
            coerced,
            previous,
        )

    return success_response(
        {
            "changed": True,
            "section": section,
            "key": key,
            "previous_value": previous,
            "new_value": coerced,
            "disk_written": disk_written,
            "message": (
                f"Updated {section}.{key}: {previous} -> {coerced}"
                + (f" (written to {config_path})" if disk_written else " (in-memory only)")
            ),
        }
    )
