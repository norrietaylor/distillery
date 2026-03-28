"""Skill evaluation framework for Distillery.

Drives the Claude Code CLI against a temporary MCP server subprocess to
evaluate skill correctness, performance (latency, token usage, cost), and
effectiveness (did Claude do the right things?).

Usage::

    from distillery.eval import ClaudeEvalRunner, load_scenario

    scenario = load_scenario("tests/eval/scenarios/recall.yaml")
    runner = ClaudeEvalRunner()
    result = await runner.run(scenario)
    print(result.performance.total_latency_ms)
    print(result.effectiveness.passed)
"""

from distillery.eval.models import (
    EffectivenessScore,
    EvalScenario,
    PerformanceMetrics,
    ScenarioResult,
    SeedEntry,
    ToolCallRecord,
)
from distillery.eval.runner import ClaudeEvalRunner
from distillery.eval.scenarios import load_scenario, load_scenarios_from_dir

__all__ = [
    "ClaudeEvalRunner",
    "EffectivenessScore",
    "EvalScenario",
    "PerformanceMetrics",
    "ScenarioResult",
    "SeedEntry",
    "ToolCallRecord",
    "load_scenario",
    "load_scenarios_from_dir",
]
