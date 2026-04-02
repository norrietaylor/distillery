"""Unit tests for cost tracking in the distillery eval CLI.

Tests cover:
- Baseline save: JSON output contains cost_summary with correct structure
- Baseline save: per-scenario cost fields (input_tokens, output_tokens,
  total_tokens, total_cost_usd)
- Per-skill aggregation: cost_summary.per_skill sums correctly
- Cost comparison: delta computation from mock baseline and current data
- Cost warning: >20% increase detected and flagged
- Cost stable: <20% increase produces no warning
- Backward compatibility: old-format baseline (flat list) doesn't crash
  --compare-cost
- Edge case: baseline with no cost_summary → "no cost baseline available"

All tests use mock ScenarioResult data — no actual eval runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from distillery.eval.models import (
    EffectivenessScore,
    PerformanceMetrics,
    ScenarioResult,
)

# ---------------------------------------------------------------------------
# Helpers: factory functions for mock data
# ---------------------------------------------------------------------------


def _make_perf(
    *,
    total_latency_ms: float = 100.0,
    input_tokens: int = 50,
    output_tokens: int = 30,
    total_cost_usd: float = 0.001,
    api_call_count: int = 1,
    tool_call_count: int = 1,
) -> PerformanceMetrics:
    return PerformanceMetrics(
        total_latency_ms=total_latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        api_call_count=api_call_count,
        tool_call_count=tool_call_count,
        total_cost_usd=total_cost_usd,
    )


def _make_effectiveness(*, passed: bool = True) -> EffectivenessScore:
    return EffectivenessScore(
        tools_called=[],
        required_tools_present=passed,
        tool_order_correct=True,
        entries_stored=0,
        entries_retrieved=0,
        response_contains_all=passed,
        response_excludes_all=True,
        latency_within_budget=True,
        tokens_within_budget=True,
        failure_reasons=[] if passed else ["forced failure"],
    )


def _make_result(
    name: str,
    skill: str,
    *,
    passed: bool = True,
    input_tokens: int = 50,
    output_tokens: int = 30,
    total_cost_usd: float = 0.001,
) -> ScenarioResult:
    return ScenarioResult(
        scenario_name=name,
        skill=skill,
        passed=passed,
        performance=_make_perf(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_cost_usd=total_cost_usd,
        ),
        effectiveness=_make_effectiveness(passed=passed),
        tool_calls=[],
        final_response="ok",
    )


# ---------------------------------------------------------------------------
# Helpers: invoke _cmd_eval with mocked runner + scenarios
# ---------------------------------------------------------------------------


def _run_cmd_eval(
    tmp_path: Path,
    results: list[ScenarioResult],
    *,
    save_baseline: str | None = None,
    baseline: str | None = None,
    compare_cost: bool = False,
    fmt: str = "json",
) -> tuple[int, str]:
    """Run _cmd_eval with the given mock results.

    Returns (exit_code, stdout_text).
    """
    from distillery.cli import _cmd_eval

    scenarios_dir = tmp_path / "scenarios"
    scenarios_dir.mkdir(exist_ok=True)

    # Write a minimal scenario YAML so the directory is not empty.
    scenario_yaml = scenarios_dir / "mock.yaml"
    scenario_yaml.write_text(
        "scenarios:\n"
        "  - name: mock-scenario\n"
        "    skill: recall\n"
        "    prompt: 'test'\n",
        encoding="utf-8",
    )

    # Patch load_scenarios_from_dir and ClaudeEvalRunner.run so no real API
    # calls are made.
    from distillery.eval.models import EvalScenario

    mock_scenarios = [
        EvalScenario(name=r.scenario_name, skill=r.skill, prompt="test")
        for r in results
    ]

    import io

    captured = io.StringIO()

    with (
        patch(
            "distillery.eval.scenarios.load_scenarios_from_dir",
            return_value=mock_scenarios,
        ),
        patch(
            "distillery.eval.runner.ClaudeEvalRunner.__init__",
            return_value=None,
        ),
        patch(
            "distillery.eval.runner.ClaudeEvalRunner.run",
            side_effect=results,
        ),
        patch("sys.stdout", captured),
    ):
        exit_code = _cmd_eval(
            scenarios_dir=str(scenarios_dir),
            skill_filter=None,
            save_baseline=save_baseline,
            baseline=baseline,
            model="claude-haiku-4-5-20251001",
            fmt=fmt,
            compare_cost=compare_cost,
        )

    return exit_code, captured.getvalue()


# ---------------------------------------------------------------------------
# T04.3: Baseline save — JSON structure
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBaselineSaveFormat:
    """Verify that --save-baseline writes the correct JSON structure."""

    def test_baseline_has_scenarios_and_cost_summary_keys(
        self, tmp_path: Path
    ) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [
            _make_result("s1", "recall", total_cost_usd=0.001),
            _make_result("s2", "distill", total_cost_usd=0.002),
        ]

        _run_cmd_eval(
            tmp_path,
            results,
            save_baseline=str(baseline_path),
        )

        assert baseline_path.exists()
        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        assert "scenarios" in data
        assert "cost_summary" in data

    def test_cost_summary_has_required_keys(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [_make_result("s1", "recall", total_cost_usd=0.003)]

        _run_cmd_eval(tmp_path, results, save_baseline=str(baseline_path))

        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        cs = data["cost_summary"]
        assert "total_cost_usd" in cs
        assert "total_tokens" in cs
        assert "per_skill" in cs

    def test_per_scenario_cost_fields_present(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [
            _make_result(
                "s1",
                "recall",
                input_tokens=40,
                output_tokens=20,
                total_cost_usd=0.0015,
            )
        ]

        _run_cmd_eval(tmp_path, results, save_baseline=str(baseline_path))

        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        scenario = data["scenarios"][0]
        assert scenario["input_tokens"] == 40
        assert scenario["output_tokens"] == 20
        assert scenario["total_tokens"] == 60
        assert scenario["total_cost_usd"] == pytest.approx(0.0015)

    def test_per_scenario_name_and_skill(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [_make_result("my-scenario", "distill", total_cost_usd=0.001)]

        _run_cmd_eval(tmp_path, results, save_baseline=str(baseline_path))

        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        assert data["scenarios"][0]["name"] == "my-scenario"
        assert data["scenarios"][0]["skill"] == "distill"

    def test_cost_summary_total_cost_is_sum_of_scenarios(
        self, tmp_path: Path
    ) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [
            _make_result("s1", "recall", total_cost_usd=0.001),
            _make_result("s2", "recall", total_cost_usd=0.002),
            _make_result("s3", "distill", total_cost_usd=0.003),
        ]

        _run_cmd_eval(tmp_path, results, save_baseline=str(baseline_path))

        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        assert data["cost_summary"]["total_cost_usd"] == pytest.approx(0.006)


# ---------------------------------------------------------------------------
# T04.3: Per-skill aggregation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPerSkillAggregation:
    """Verify that cost_summary.per_skill groups and sums correctly."""

    def test_per_skill_keys_match_skills_in_results(
        self, tmp_path: Path
    ) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [
            _make_result("s1", "recall", total_cost_usd=0.001),
            _make_result("s2", "distill", total_cost_usd=0.002),
        ]

        _run_cmd_eval(tmp_path, results, save_baseline=str(baseline_path))

        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        per_skill = data["cost_summary"]["per_skill"]
        assert set(per_skill.keys()) == {"recall", "distill"}

    def test_per_skill_cost_is_summed_per_skill(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [
            _make_result("s1", "recall", total_cost_usd=0.001),
            _make_result("s2", "recall", total_cost_usd=0.003),
            _make_result("s3", "distill", total_cost_usd=0.002),
        ]

        _run_cmd_eval(tmp_path, results, save_baseline=str(baseline_path))

        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        per_skill = data["cost_summary"]["per_skill"]
        assert per_skill["recall"]["cost_usd"] == pytest.approx(0.004)
        assert per_skill["distill"]["cost_usd"] == pytest.approx(0.002)

    def test_per_skill_scenario_count(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [
            _make_result("s1", "recall", total_cost_usd=0.001),
            _make_result("s2", "recall", total_cost_usd=0.001),
            _make_result("s3", "recall", total_cost_usd=0.001),
        ]

        _run_cmd_eval(tmp_path, results, save_baseline=str(baseline_path))

        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        assert data["cost_summary"]["per_skill"]["recall"]["scenario_count"] == 3

    def test_per_skill_token_sum(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        results = [
            _make_result(
                "s1", "recall", input_tokens=10, output_tokens=5, total_cost_usd=0.001
            ),
            _make_result(
                "s2", "recall", input_tokens=20, output_tokens=10, total_cost_usd=0.001
            ),
        ]

        _run_cmd_eval(tmp_path, results, save_baseline=str(baseline_path))

        data = json.loads(baseline_path.read_text(encoding="utf-8"))
        # total_tokens for s1 = 15, s2 = 30, sum = 45
        assert data["cost_summary"]["per_skill"]["recall"]["tokens"] == 45


# ---------------------------------------------------------------------------
# T04.3: Cost comparison delta computation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCostComparison:
    """Verify delta computation when --compare-cost is used."""

    def _write_baseline(
        self,
        tmp_path: Path,
        scenarios: list[dict[str, Any]],
        cost_summary: dict[str, Any],
    ) -> Path:
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(
            json.dumps({"scenarios": scenarios, "cost_summary": cost_summary}),
            encoding="utf-8",
        )
        return baseline_path

    def test_compare_cost_delta_is_current_minus_baseline(
        self, tmp_path: Path
    ) -> None:
        baseline = self._write_baseline(
            tmp_path,
            scenarios=[
                {
                    "name": "s1",
                    "skill": "recall",
                    "passed": True,
                    "latency_ms": 100.0,
                    "total_tokens": 80,
                    "input_tokens": 50,
                    "output_tokens": 30,
                    "total_cost_usd": 0.010,
                    "tool_call_count": 1,
                }
            ],
            cost_summary={
                "total_cost_usd": 0.010,
                "total_tokens": 80,
                "per_skill": {"recall": {"cost_usd": 0.010, "tokens": 80, "scenario_count": 1}},
            },
        )
        results = [_make_result("s1", "recall", total_cost_usd=0.012)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        cc = data["cost_comparison"]
        assert cc["total_delta_usd"] == pytest.approx(0.002, abs=1e-7)
        assert cc["current_total_usd"] == pytest.approx(0.012, abs=1e-7)
        assert cc["baseline_total_usd"] == pytest.approx(0.010, abs=1e-7)

    def test_compare_cost_per_skill_delta(self, tmp_path: Path) -> None:
        baseline = self._write_baseline(
            tmp_path,
            scenarios=[
                {
                    "name": "s1",
                    "skill": "recall",
                    "passed": True,
                    "latency_ms": 100.0,
                    "total_tokens": 80,
                    "input_tokens": 50,
                    "output_tokens": 30,
                    "total_cost_usd": 0.010,
                    "tool_call_count": 1,
                }
            ],
            cost_summary={
                "total_cost_usd": 0.010,
                "total_tokens": 80,
                "per_skill": {"recall": {"cost_usd": 0.010, "tokens": 80, "scenario_count": 1}},
            },
        )
        results = [_make_result("s1", "recall", total_cost_usd=0.015)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        recall_delta = data["cost_comparison"]["per_skill"]["recall"]
        assert recall_delta["delta_usd"] == pytest.approx(0.005, abs=1e-7)
        assert recall_delta["baseline_usd"] == pytest.approx(0.010, abs=1e-7)
        assert recall_delta["current_usd"] == pytest.approx(0.015, abs=1e-7)

    def test_compare_cost_delta_pct_calculated(self, tmp_path: Path) -> None:
        baseline = self._write_baseline(
            tmp_path,
            scenarios=[
                {
                    "name": "s1",
                    "skill": "recall",
                    "passed": True,
                    "latency_ms": 100.0,
                    "total_tokens": 80,
                    "input_tokens": 50,
                    "output_tokens": 30,
                    "total_cost_usd": 0.010,
                    "tool_call_count": 1,
                }
            ],
            cost_summary={
                "total_cost_usd": 0.010,
                "total_tokens": 80,
                "per_skill": {"recall": {"cost_usd": 0.010, "tokens": 80, "scenario_count": 1}},
            },
        )
        results = [_make_result("s1", "recall", total_cost_usd=0.012)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        cc = data["cost_comparison"]
        # 0.012 / 0.010 = 1.2 → +20% but that is exactly 20.0, not > 20
        assert cc["total_delta_pct"] == pytest.approx(20.0, abs=0.1)


# ---------------------------------------------------------------------------
# T04.3: Cost warning (>20% increase)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCostWarning:
    """Verify that warnings are emitted when per-skill cost increases by >20%."""

    def _baseline_with_skill_cost(
        self, tmp_path: Path, skill: str, cost_usd: float
    ) -> Path:
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(
            json.dumps(
                {
                    "scenarios": [
                        {
                            "name": "s1",
                            "skill": skill,
                            "passed": True,
                            "latency_ms": 100.0,
                            "total_tokens": 80,
                            "input_tokens": 50,
                            "output_tokens": 30,
                            "total_cost_usd": cost_usd,
                            "tool_call_count": 1,
                        }
                    ],
                    "cost_summary": {
                        "total_cost_usd": cost_usd,
                        "total_tokens": 80,
                        "per_skill": {
                            skill: {
                                "cost_usd": cost_usd,
                                "tokens": 80,
                                "scenario_count": 1,
                            }
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return baseline_path

    def test_warning_emitted_when_cost_increases_more_than_20_pct(
        self, tmp_path: Path
    ) -> None:
        baseline = self._baseline_with_skill_cost(tmp_path, "recall", 0.010)
        # 0.013 / 0.010 = +30% → warning expected
        results = [_make_result("s1", "recall", total_cost_usd=0.013)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        warnings = data["cost_comparison"]["warnings"]
        assert len(warnings) == 1
        assert "recall" in warnings[0]
        assert "30.0%" in warnings[0]

    def test_no_warning_when_cost_increase_is_below_20_pct(
        self, tmp_path: Path
    ) -> None:
        baseline = self._baseline_with_skill_cost(tmp_path, "recall", 0.010)
        # 0.011 / 0.010 = +10% → no warning
        results = [_make_result("s1", "recall", total_cost_usd=0.011)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        warnings = data["cost_comparison"]["warnings"]
        assert warnings == []

    def test_no_warning_when_cost_decreases(self, tmp_path: Path) -> None:
        baseline = self._baseline_with_skill_cost(tmp_path, "recall", 0.010)
        # Current cost lower than baseline → no warning
        results = [_make_result("s1", "recall", total_cost_usd=0.005)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        warnings = data["cost_comparison"]["warnings"]
        assert warnings == []

    def test_warning_boundary_exactly_20_pct_no_warning(
        self, tmp_path: Path
    ) -> None:
        baseline = self._baseline_with_skill_cost(tmp_path, "recall", 0.010)
        # 0.012 / 0.010 = +20.0% (not > 20) → no warning
        results = [_make_result("s1", "recall", total_cost_usd=0.012)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        warnings = data["cost_comparison"]["warnings"]
        assert warnings == []


# ---------------------------------------------------------------------------
# T04.3: Backward compatibility — old-format baseline (flat list)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBackwardCompatibility:
    """Old-format baselines (flat list) must not crash --compare-cost."""

    def test_old_format_flat_list_does_not_crash(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(
            json.dumps(
                [
                    {
                        "name": "s1",
                        "skill": "recall",
                        "passed": True,
                        "latency_ms": 100.0,
                        "total_tokens": 80,
                    }
                ]
            ),
            encoding="utf-8",
        )

        results = [_make_result("s1", "recall", total_cost_usd=0.001)]

        exit_code, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline_path),
            compare_cost=True,
            fmt="json",
        )

        # Must not raise, exit code depends only on pass/fail
        assert exit_code == 0

    def test_old_format_reports_no_cost_baseline_available(
        self, tmp_path: Path
    ) -> None:
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(
            json.dumps(
                [
                    {
                        "name": "s1",
                        "skill": "recall",
                        "passed": True,
                        "latency_ms": 100.0,
                        "total_tokens": 80,
                    }
                ]
            ),
            encoding="utf-8",
        )

        results = [_make_result("s1", "recall", total_cost_usd=0.001)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline_path),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        assert "cost_comparison" in data
        assert data["cost_comparison"]["note"] == "no cost baseline available"


# ---------------------------------------------------------------------------
# T04.3: Edge case — new-format baseline with no cost_summary key
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMissingCostSummary:
    """New-format baseline dict that lacks cost_summary → graceful message."""

    def test_missing_cost_summary_reports_no_cost_baseline(
        self, tmp_path: Path
    ) -> None:
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(
            json.dumps(
                {
                    "scenarios": [
                        {
                            "name": "s1",
                            "skill": "recall",
                            "passed": True,
                            "latency_ms": 100.0,
                            "total_tokens": 80,
                        }
                    ]
                    # intentionally omitting "cost_summary"
                }
            ),
            encoding="utf-8",
        )

        results = [_make_result("s1", "recall", total_cost_usd=0.001)]

        _, output = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline_path),
            compare_cost=True,
            fmt="json",
        )

        data = json.loads(output)
        assert "cost_comparison" in data
        assert data["cost_comparison"]["note"] == "no cost baseline available"

    def test_missing_cost_summary_does_not_raise(self, tmp_path: Path) -> None:
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(
            json.dumps({"scenarios": []}),
            encoding="utf-8",
        )

        results = [_make_result("s1", "recall", total_cost_usd=0.001)]

        # Should not raise
        exit_code, _ = _run_cmd_eval(
            tmp_path,
            results,
            baseline=str(baseline_path),
            compare_cost=True,
            fmt="json",
        )
        assert exit_code == 0
