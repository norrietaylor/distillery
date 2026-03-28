"""YAML scenario loader for the Distillery eval framework."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from distillery.eval.models import EvalScenario, SeedEntry


def _parse_seed_entry(data: dict[str, Any]) -> SeedEntry:
    return SeedEntry(
        content=data["content"],
        entry_type=data.get("entry_type", "session"),
        author=data.get("author", "eval-seed"),
        tags=data.get("tags", []),
        project=data.get("project"),
        metadata=data.get("metadata", {}),
    )


def _parse_scenario(data: dict[str, Any]) -> EvalScenario:
    seed_entries = [_parse_seed_entry(s) for s in data.get("seed_entries", [])]
    return EvalScenario(
        name=data["name"],
        skill=data["skill"],
        prompt=data["prompt"],
        description=data.get("description", ""),
        seed_entries=seed_entries,
        expected_tools=data.get("expected_tools", []),
        expected_tools_in_order=data.get("expected_tools_in_order", []),
        response_must_contain=data.get("response_must_contain", []),
        response_must_not_contain=data.get("response_must_not_contain", []),
        min_entries_stored=data.get("min_entries_stored", 0),
        min_entries_retrieved=data.get("min_entries_retrieved", 0),
        max_latency_ms=float(data.get("max_latency_ms", 60_000)),
        max_total_tokens=int(data.get("max_total_tokens", 10_000)),
        model=data.get("model", "claude-haiku-4-5-20251001"),
        max_tokens=int(data.get("max_tokens", 4096)),
    )


def load_scenario(path: str | Path) -> EvalScenario:
    """Load a single scenario from a YAML file.

    The file may contain either a single scenario dict or a list of scenarios
    (in which case the first is returned).

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed :class:`~distillery.eval.models.EvalScenario`.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return _parse_scenario(data[0])
    return _parse_scenario(data)


def load_scenarios(path: str | Path) -> list[EvalScenario]:
    """Load all scenarios from a YAML file.

    Supports both a single scenario dict and a list of scenario dicts.

    Args:
        path: Path to the YAML file.

    Returns:
        List of :class:`~distillery.eval.models.EvalScenario` objects.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [_parse_scenario(item) for item in data]
    return [_parse_scenario(data)]


def load_scenarios_from_dir(directory: str | Path) -> list[EvalScenario]:
    """Load all scenarios from all YAML files in *directory*.

    Args:
        directory: Directory containing ``*.yaml`` scenario files.

    Returns:
        Combined list of all scenarios found.
    """
    scenarios: list[EvalScenario] = []
    for yaml_file in sorted(Path(directory).glob("*.yaml")):
        scenarios.extend(load_scenarios(yaml_file))
    return scenarios
