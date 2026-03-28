"""Claude-powered skill evaluation tests.

These tests drive real Claude API calls against an in-process Distillery MCP
server to evaluate skill correctness, performance, and effectiveness end-to-end.

Requirements:
  - ``ANTHROPIC_API_KEY`` env var must be set
  - ``pip install 'distillery[eval]'`` (adds the ``anthropic`` package)

Run selectively::

    pytest -m eval                          # all eval tests
    pytest -m eval -k recall               # only recall scenarios
    pytest tests/test_eval_claude.py -v    # with verbose output

All eval tests are skipped automatically if ANTHROPIC_API_KEY is not set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from distillery.eval.models import EvalScenario, ScenarioResult
from distillery.eval.scenarios import load_scenarios_from_dir

# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.eval

_HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))
_HAS_ANTHROPIC = False
try:
    import anthropic  # noqa: F401

    _HAS_ANTHROPIC = True
except ImportError:
    pass

_SKIP_REASON = (
    "ANTHROPIC_API_KEY not set or 'anthropic' package not installed — "
    "install with: pip install 'distillery[eval]'"
)
_SHOULD_SKIP = not (_HAS_API_KEY and _HAS_ANTHROPIC)

# ---------------------------------------------------------------------------
# Scenario discovery
# ---------------------------------------------------------------------------

_SCENARIOS_DIR = Path(__file__).parent / "eval" / "scenarios"


def _discover_scenarios() -> list[EvalScenario]:
    """Load all scenarios from the eval/scenarios directory."""
    if not _SCENARIOS_DIR.exists():
        return []
    return load_scenarios_from_dir(_SCENARIOS_DIR)


_ALL_SCENARIOS = _discover_scenarios()
_SCENARIO_IDS = [s.name for s in _ALL_SCENARIOS]

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def eval_runner():
    """Return a ClaudeEvalRunner (module-scoped to reuse the HTTP client)."""
    if _SHOULD_SKIP:
        pytest.skip(_SKIP_REASON)
    from distillery.eval.runner import ClaudeEvalRunner

    return ClaudeEvalRunner()


# ---------------------------------------------------------------------------
# Parametrised scenario tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SHOULD_SKIP, reason=_SKIP_REASON)
@pytest.mark.parametrize("scenario", _ALL_SCENARIOS, ids=_SCENARIO_IDS)
async def test_eval_scenario(scenario: EvalScenario, eval_runner) -> None:
    """Run a single eval scenario and assert it passes.

    Failure output includes the scenario summary with failure reasons so CI
    logs are actionable without reading the full test output.
    """
    result: ScenarioResult = await eval_runner.run(scenario)

    # Always print the summary for CI visibility.
    print(f"\n{result.summary()}")
    if result.tool_calls:
        print(f"  Tool calls: {[tc.tool_name for tc in result.tool_calls]}")
        print(f"  Performance: {result.performance.total_latency_ms:.0f}ms, "
              f"{result.performance.total_tokens} tokens")

    assert result.passed, (
        f"Scenario '{scenario.name}' failed:\n"
        + "\n".join(f"  - {r}" for r in result.effectiveness.failure_reasons)
        + f"\n\nFinal response:\n{result.final_response[:500]}"
    )


# ---------------------------------------------------------------------------
# Structural tests (no API key required)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_scenarios_discovered() -> None:
    """At least one scenario file must be loadable from the scenarios dir."""
    assert len(_ALL_SCENARIOS) > 0, (
        f"No scenarios found in {_SCENARIOS_DIR}. "
        "Add YAML files to tests/eval/scenarios/."
    )


@pytest.mark.unit
def test_scenario_names_unique() -> None:
    """All scenario names must be unique across all YAML files."""
    names = [s.name for s in _ALL_SCENARIOS]
    duplicates = [n for n in names if names.count(n) > 1]
    assert not duplicates, f"Duplicate scenario names found: {set(duplicates)}"


@pytest.mark.unit
def test_scenario_skills_valid() -> None:
    """Each scenario must reference a skill that has a SKILL.md file."""
    skills_dir = Path(__file__).parents[1] / ".claude" / "skills"
    valid_skills = {p.parent.name for p in skills_dir.glob("*/SKILL.md")} if skills_dir.exists() else set()
    for scenario in _ALL_SCENARIOS:
        assert scenario.skill in valid_skills or not valid_skills, (
            f"Scenario '{scenario.name}' references unknown skill '{scenario.skill}'. "
            f"Valid skills: {sorted(valid_skills)}"
        )


@pytest.mark.unit
def test_golden_dataset_loadable() -> None:
    """The golden dataset YAML must be parseable."""
    import yaml

    golden_path = Path(__file__).parent / "eval" / "golden_dataset.yaml"
    assert golden_path.exists(), f"Golden dataset not found at {golden_path}"
    data = yaml.safe_load(golden_path.read_text(encoding="utf-8"))
    assert "entries" in data
    assert len(data["entries"]) >= 20, (
        f"Golden dataset has only {len(data['entries'])} entries; need at least 20"
    )


@pytest.mark.unit
def test_skill_coverage() -> None:
    """Every discovered skill should have at least 3 eval scenarios."""
    from collections import Counter

    skill_counts = Counter(s.skill for s in _ALL_SCENARIOS)
    skills_dir = Path(__file__).parents[1] / ".claude" / "skills"
    if not skills_dir.exists():
        pytest.skip("Skills directory not found")

    known_skills = {p.parent.name for p in skills_dir.glob("*/SKILL.md")}
    for skill in known_skills:
        count = skill_counts.get(skill, 0)
        assert count >= 3, (
            f"Skill '{skill}' has only {count} eval scenarios; need at least 3. "
            f"Add scenarios to tests/eval/scenarios/{skill}.yaml"
        )


# ---------------------------------------------------------------------------
# Aggregate report (optional, runs if API key present)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SHOULD_SKIP, reason=_SKIP_REASON)
async def test_eval_aggregate_pass_rate(eval_runner) -> None:
    """At least 80% of scenarios must pass.

    This is a soft aggregate check — individual scenario tests catch
    regressions, but this ensures the suite doesn't silently degrade.
    """
    results = []
    for scenario in _ALL_SCENARIOS:
        result = await eval_runner.run(scenario)
        results.append(result)
        print(result.summary())

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    pass_rate = passed / total if total > 0 else 0.0

    print(f"\n=== Eval Suite: {passed}/{total} passed ({pass_rate:.0%}) ===")
    _print_performance_report(results)

    assert pass_rate >= 0.80, (
        f"Eval pass rate {pass_rate:.0%} is below the 80% threshold. "
        f"Failed scenarios:\n"
        + "\n".join(
            f"  - {r.scenario_name}: {'; '.join(r.effectiveness.failure_reasons)}"
            for r in results
            if not r.passed
        )
    )


def _print_performance_report(results: list[ScenarioResult]) -> None:
    """Print a performance summary table to stdout."""
    if not results:
        return
    print("\n--- Performance Report ---")
    print(f"{'Scenario':<45} {'Latency':>8} {'Tokens':>7} {'Calls':>6} {'Pass':>5}")
    print("-" * 75)
    for r in sorted(results, key=lambda x: x.performance.total_latency_ms, reverse=True):
        status = "PASS" if r.passed else "FAIL"
        print(
            f"{r.scenario_name[:44]:<45} "
            f"{r.performance.total_latency_ms:>7.0f}ms "
            f"{r.performance.total_tokens:>7} "
            f"{r.performance.tool_call_count:>6} "
            f"{status:>5}"
        )

    avg_latency = sum(r.performance.total_latency_ms for r in results) / len(results)
    avg_tokens = sum(r.performance.total_tokens for r in results) / len(results)
    print("-" * 75)
    print(f"{'AVERAGE':<45} {avg_latency:>7.0f}ms {avg_tokens:>7.0f}")


# ---------------------------------------------------------------------------
# Baseline regression detection
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_SHOULD_SKIP, reason=_SKIP_REASON)
async def test_eval_save_baseline(eval_runner, tmp_path) -> None:
    """Run all scenarios and save results to a JSON baseline file.

    Set EVAL_BASELINE_PATH to write a persistent baseline for regression
    detection. If the env var is not set this test writes to a temp file
    and is informational only.
    """
    baseline_path = os.environ.get("EVAL_BASELINE_PATH")
    if not baseline_path:
        pytest.skip("EVAL_BASELINE_PATH not set — skipping baseline save")

    results = []
    for scenario in _ALL_SCENARIOS:
        result = await eval_runner.run(scenario)
        results.append({
            "name": result.scenario_name,
            "skill": result.skill,
            "passed": result.passed,
            "latency_ms": result.performance.total_latency_ms,
            "total_tokens": result.performance.total_tokens,
            "tool_call_count": result.performance.tool_call_count,
        })

    Path(baseline_path).write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nBaseline saved to {baseline_path} ({len(results)} scenarios)")


@pytest.mark.skipif(_SHOULD_SKIP, reason=_SKIP_REASON)
async def test_eval_regression_check(eval_runner) -> None:
    """Compare current results against a saved baseline.

    Set EVAL_BASELINE_PATH to the path of a previously saved baseline JSON.
    Fails if any scenario that was passing has started failing, or if latency
    regressed by more than 50%.
    """
    baseline_path = os.environ.get("EVAL_BASELINE_PATH")
    if not baseline_path or not Path(baseline_path).exists():
        pytest.skip("EVAL_BASELINE_PATH not set or file not found — skipping regression check")

    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    baseline_by_name = {entry["name"]: entry for entry in baseline}

    regressions = []
    for scenario in _ALL_SCENARIOS:
        result = await eval_runner.run(scenario)
        baseline_entry = baseline_by_name.get(scenario.name)
        if baseline_entry is None:
            continue

        if baseline_entry["passed"] and not result.passed:
            regressions.append(
                f"{scenario.name}: was passing, now failing — "
                + "; ".join(result.effectiveness.failure_reasons)
            )

        if baseline_entry["latency_ms"] > 0:
            latency_ratio = result.performance.total_latency_ms / baseline_entry["latency_ms"]
            if latency_ratio > 1.5:
                regressions.append(
                    f"{scenario.name}: latency regressed "
                    f"{baseline_entry['latency_ms']:.0f}ms → "
                    f"{result.performance.total_latency_ms:.0f}ms "
                    f"({latency_ratio:.1f}x)"
                )

    assert not regressions, (
        f"Eval regressions detected ({len(regressions)}):\n"
        + "\n".join(f"  - {r}" for r in regressions)
    )
