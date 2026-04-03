"""Unit tests for the distillery.eval package.

Covers models, scorer, scenarios, mcp_bridge, and the runner's skill-prompt
loader — all without requiring an Anthropic API key.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from distillery.eval.models import (
    EffectivenessScore,
    EvalScenario,
    PerformanceMetrics,
    ScenarioResult,
    SeedEntry,
    ToolCallRecord,
)
from distillery.eval.scenarios import (
    load_scenario,
    load_scenarios,
    load_scenarios_from_dir,
)
from distillery.eval.scorer import score_effectiveness

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scenario(**kwargs: Any) -> EvalScenario:
    """Return an EvalScenario with sensible defaults, overridden by kwargs."""
    defaults: dict[str, Any] = {
        "name": "test-scenario",
        "skill": "distill",
        "prompt": "/distill something",
        "max_latency_ms": 60_000.0,
        "max_total_tokens": 10_000,
    }
    defaults.update(kwargs)
    return EvalScenario(**defaults)


def _make_perf(
    total_latency_ms: float = 1_000.0,
    input_tokens: int = 100,
    output_tokens: int = 200,
    api_call_count: int = 1,
    tool_call_count: int = 1,
    tool_latencies_ms: list[float] | None = None,
) -> PerformanceMetrics:
    return PerformanceMetrics(
        total_latency_ms=total_latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        api_call_count=api_call_count,
        tool_call_count=tool_call_count,
        tool_latencies_ms=tool_latencies_ms or [],
    )


def _make_tool_call(name: str = "distillery_store", latency_ms: float = 50.0) -> ToolCallRecord:
    return ToolCallRecord(
        tool_name=name,
        arguments={"content": "test"},
        response={"id": "abc"},
        latency_ms=latency_ms,
    )


# ===========================================================================
# models.py
# ===========================================================================


@pytest.mark.unit
class TestSeedEntry:
    def test_defaults(self) -> None:
        e = SeedEntry(content="hello", entry_type="session")
        assert e.author == "eval-seed"
        assert e.tags == []
        assert e.project is None
        assert e.metadata == {}

    def test_explicit_fields(self) -> None:
        e = SeedEntry(
            content="text",
            entry_type="bookmark",
            author="alice",
            tags=["a", "b"],
            project="proj",
            metadata={"url": "https://example.com"},
        )
        assert e.author == "alice"
        assert e.tags == ["a", "b"]
        assert e.project == "proj"
        assert e.metadata["url"] == "https://example.com"


@pytest.mark.unit
class TestEvalScenario:
    def test_defaults(self) -> None:
        s = EvalScenario(name="x", skill="recall", prompt="/recall foo")
        assert s.description == ""
        assert s.seed_entries == []
        assert s.expected_tools == []
        assert s.expected_tools_in_order == []
        assert s.response_must_contain == []
        assert s.response_must_not_contain == []
        assert s.min_entries_stored == 0
        assert s.min_entries_retrieved == 0
        assert s.max_latency_ms == 60_000.0
        assert s.max_total_tokens == 10_000
        assert s.model == "claude-haiku-4-5-20251001"
        assert s.max_tokens == 4096


@pytest.mark.unit
class TestToolCallRecord:
    def test_no_error_by_default(self) -> None:
        tc = _make_tool_call()
        assert tc.error is None

    def test_with_error(self) -> None:
        tc = ToolCallRecord(
            tool_name="distillery_get",
            arguments={"id": "bad"},
            response={"error": True},
            latency_ms=10.0,
            error="entry not found",
        )
        assert tc.error == "entry not found"


@pytest.mark.unit
class TestPerformanceMetrics:
    def test_total_tokens(self) -> None:
        p = _make_perf(input_tokens=300, output_tokens=150)
        assert p.total_tokens == 450

    def test_avg_tool_latency_no_calls(self) -> None:
        p = _make_perf(tool_latencies_ms=[])
        assert p.avg_tool_latency_ms == 0.0

    def test_avg_tool_latency_single(self) -> None:
        p = _make_perf(tool_latencies_ms=[100.0])
        assert p.avg_tool_latency_ms == 100.0

    def test_avg_tool_latency_multiple(self) -> None:
        p = _make_perf(tool_latencies_ms=[100.0, 200.0, 300.0])
        assert p.avg_tool_latency_ms == 200.0

    def test_tokens_per_second(self) -> None:
        # 200 output tokens in 2000 ms → 100 tok/sec
        p = _make_perf(total_latency_ms=2000.0, output_tokens=200)
        assert p.tokens_per_second == pytest.approx(100.0)

    def test_tokens_per_second_zero_latency(self) -> None:
        p = _make_perf(total_latency_ms=0.0, output_tokens=100)
        assert p.tokens_per_second == 0.0

    def test_tokens_per_second_negative_latency(self) -> None:
        p = _make_perf(total_latency_ms=-1.0, output_tokens=100)
        assert p.tokens_per_second == 0.0

    def test_total_cost_usd_default_zero(self) -> None:
        p = _make_perf()
        assert p.total_cost_usd == 0.0

    def test_total_cost_usd_explicit(self) -> None:
        p = PerformanceMetrics(
            total_latency_ms=1000.0,
            input_tokens=100,
            output_tokens=200,
            api_call_count=1,
            tool_call_count=0,
            total_cost_usd=0.0042,
        )
        assert p.total_cost_usd == pytest.approx(0.0042)


@pytest.mark.unit
class TestEffectivenessScore:
    def test_passed_when_no_failures(self) -> None:
        score = EffectivenessScore(
            tools_called=["distillery_store"],
            required_tools_present=True,
            tool_order_correct=True,
            entries_stored=1,
            entries_retrieved=0,
            response_contains_all=True,
            response_excludes_all=True,
            latency_within_budget=True,
            tokens_within_budget=True,
            failure_reasons=[],
        )
        assert score.passed is True

    def test_failed_when_failure_reasons(self) -> None:
        score = EffectivenessScore(
            tools_called=[],
            required_tools_present=False,
            tool_order_correct=True,
            entries_stored=0,
            entries_retrieved=0,
            response_contains_all=True,
            response_excludes_all=True,
            latency_within_budget=True,
            tokens_within_budget=True,
            failure_reasons=["Missing required tools: ['distillery_store']"],
        )
        assert score.passed is False


@pytest.mark.unit
class TestScenarioResult:
    def _make_result(self, passed: bool = True, reasons: list[str] | None = None) -> ScenarioResult:
        score = EffectivenessScore(
            tools_called=["distillery_store"],
            required_tools_present=True,
            tool_order_correct=True,
            entries_stored=1,
            entries_retrieved=0,
            response_contains_all=True,
            response_excludes_all=True,
            latency_within_budget=True,
            tokens_within_budget=True,
            failure_reasons=reasons or [],
        )
        return ScenarioResult(
            scenario_name="my-test",
            skill="distill",
            passed=passed,
            performance=_make_perf(),
            effectiveness=score,
            tool_calls=[_make_tool_call()],
            final_response="All done.",
        )

    def test_summary_pass(self) -> None:
        result = self._make_result(passed=True)
        s = result.summary()
        assert s.startswith("[PASS]")
        assert "my-test" in s

    def test_summary_fail_includes_reasons(self) -> None:
        result = self._make_result(
            passed=False,
            reasons=["Missing required tools: ['x']"],
        )
        s = result.summary()
        assert s.startswith("[FAIL]")
        assert "Missing required tools" in s

    def test_summary_contains_perf_info(self) -> None:
        result = self._make_result()
        s = result.summary()
        # latency (1000ms), total tokens (300), tool_call_count (1)
        assert "1000ms" in s
        assert "300tok" in s
        assert "1calls" in s

    def test_error_field_default_none(self) -> None:
        result = self._make_result()
        assert result.error is None


# ===========================================================================
# scorer.py
# ===========================================================================


@pytest.mark.unit
class TestScoreEffectiveness:
    """Tests for the core score_effectiveness pure function."""

    def _score(self, **kwargs: Any) -> EffectivenessScore:
        """Run scorer with sensible defaults, overridden by kwargs."""
        scenario = _make_scenario(
            expected_tools=kwargs.pop("expected_tools", []),
            expected_tools_in_order=kwargs.pop("expected_tools_in_order", []),
            response_must_contain=kwargs.pop("response_must_contain", []),
            response_must_not_contain=kwargs.pop("response_must_not_contain", []),
            min_entries_stored=kwargs.pop("min_entries_stored", 0),
            min_entries_retrieved=kwargs.pop("min_entries_retrieved", 0),
            max_latency_ms=kwargs.pop("max_latency_ms", 60_000.0),
            max_total_tokens=kwargs.pop("max_total_tokens", 10_000),
        )
        tool_calls = kwargs.pop("tool_calls", [])
        final_response = kwargs.pop("final_response", "great response")
        entries_stored = kwargs.pop("entries_stored", 0)
        entries_retrieved = kwargs.pop("entries_retrieved", 0)
        performance = kwargs.pop("performance", _make_perf())
        return score_effectiveness(
            scenario=scenario,
            tool_calls=tool_calls,
            final_response=final_response,
            entries_stored=entries_stored,
            entries_retrieved=entries_retrieved,
            performance=performance,
        )

    def test_all_pass_empty_expectations(self) -> None:
        score = self._score()
        assert score.passed

    # --- required tools ---

    def test_required_tool_present(self) -> None:
        tc = _make_tool_call("distillery_store")
        score = self._score(expected_tools=["distillery_store"], tool_calls=[tc])
        assert score.required_tools_present
        assert score.passed

    def test_required_tool_missing(self) -> None:
        score = self._score(expected_tools=["distillery_store"], tool_calls=[])
        assert not score.required_tools_present
        assert not score.passed
        assert any("Missing required tools" in r for r in score.failure_reasons)

    def test_multiple_required_tools_all_present(self) -> None:
        tools = [_make_tool_call("distillery_status"), _make_tool_call("distillery_store")]
        score = self._score(
            expected_tools=["distillery_status", "distillery_store"],
            tool_calls=tools,
        )
        assert score.required_tools_present

    def test_multiple_required_tools_partial_missing(self) -> None:
        score = self._score(
            expected_tools=["distillery_status", "distillery_store"],
            tool_calls=[_make_tool_call("distillery_status")],
        )
        assert not score.required_tools_present
        assert any("distillery_store" in r for r in score.failure_reasons)

    # --- tool order ---

    def test_tool_order_correct(self) -> None:
        tools = [_make_tool_call("distillery_status"), _make_tool_call("distillery_store")]
        score = self._score(
            expected_tools_in_order=["distillery_status", "distillery_store"],
            tool_calls=tools,
        )
        assert score.tool_order_correct

    def test_tool_order_wrong(self) -> None:
        tools = [_make_tool_call("distillery_store"), _make_tool_call("distillery_status")]
        score = self._score(
            expected_tools_in_order=["distillery_status", "distillery_store"],
            tool_calls=tools,
        )
        assert not score.tool_order_correct
        assert any("Tool order mismatch" in r for r in score.failure_reasons)

    def test_tool_order_prefix_only(self) -> None:
        """If in-order list is a prefix of actual calls, that's fine."""
        tools = [
            _make_tool_call("distillery_status"),
            _make_tool_call("distillery_store"),
            _make_tool_call("distillery_search"),
        ]
        score = self._score(
            expected_tools_in_order=["distillery_status"],
            tool_calls=tools,
        )
        assert score.tool_order_correct

    def test_tool_order_too_few_actual_calls(self) -> None:
        """If in-order list is longer than actual calls, should fail."""
        score = self._score(
            expected_tools_in_order=["distillery_status", "distillery_store"],
            tool_calls=[_make_tool_call("distillery_status")],
        )
        assert not score.tool_order_correct

    def test_tool_order_empty_expectation_always_passes(self) -> None:
        score = self._score(expected_tools_in_order=[], tool_calls=[])
        assert score.tool_order_correct

    # --- entries stored ---

    def test_entries_stored_sufficient(self) -> None:
        score = self._score(min_entries_stored=2, entries_stored=3)
        assert not any("Entries stored" in r for r in score.failure_reasons)

    def test_entries_stored_exact_threshold(self) -> None:
        score = self._score(min_entries_stored=2, entries_stored=2)
        assert not any("Entries stored" in r for r in score.failure_reasons)

    def test_entries_stored_insufficient(self) -> None:
        score = self._score(min_entries_stored=3, entries_stored=1)
        assert any("Entries stored" in r for r in score.failure_reasons)
        assert not score.passed

    # --- entries retrieved ---

    def test_entries_retrieved_sufficient(self) -> None:
        score = self._score(min_entries_retrieved=1, entries_retrieved=5)
        assert not any("Entries retrieved" in r for r in score.failure_reasons)

    def test_entries_retrieved_insufficient(self) -> None:
        score = self._score(min_entries_retrieved=2, entries_retrieved=0)
        assert any("Entries retrieved" in r for r in score.failure_reasons)

    # --- response content ---

    def test_response_must_contain_present(self) -> None:
        score = self._score(
            response_must_contain=["hello"],
            final_response="Hello World",
        )
        assert score.response_contains_all
        assert score.passed

    def test_response_must_contain_case_insensitive(self) -> None:
        score = self._score(
            response_must_contain=["WORLD"],
            final_response="hello world",
        )
        assert score.response_contains_all

    def test_response_must_contain_missing(self) -> None:
        score = self._score(
            response_must_contain=["goodbye"],
            final_response="hello world",
        )
        assert not score.response_contains_all
        assert any("missing expected content" in r.lower() for r in score.failure_reasons)

    def test_response_must_not_contain_absent(self) -> None:
        score = self._score(
            response_must_not_contain=["error"],
            final_response="everything is fine",
        )
        assert score.response_excludes_all

    def test_response_must_not_contain_present(self) -> None:
        score = self._score(
            response_must_not_contain=["error"],
            final_response="An error occurred",
        )
        assert not score.response_excludes_all
        assert any("forbidden content" in r.lower() for r in score.failure_reasons)

    def test_response_must_not_contain_case_insensitive(self) -> None:
        score = self._score(
            response_must_not_contain=["ERROR"],
            final_response="an error occurred",
        )
        assert not score.response_excludes_all

    # --- performance budgets ---

    def test_latency_within_budget(self) -> None:
        perf = _make_perf(total_latency_ms=5_000)
        score = self._score(max_latency_ms=10_000.0, performance=perf)
        assert score.latency_within_budget

    def test_latency_exact_budget(self) -> None:
        perf = _make_perf(total_latency_ms=10_000)
        score = self._score(max_latency_ms=10_000.0, performance=perf)
        assert score.latency_within_budget

    def test_latency_exceeds_budget(self) -> None:
        perf = _make_perf(total_latency_ms=15_000)
        score = self._score(max_latency_ms=10_000.0, performance=perf)
        assert not score.latency_within_budget
        assert any("Latency" in r and "exceeds budget" in r for r in score.failure_reasons)

    def test_tokens_within_budget(self) -> None:
        perf = _make_perf(input_tokens=100, output_tokens=200)
        score = self._score(max_total_tokens=1_000, performance=perf)
        assert score.tokens_within_budget

    def test_tokens_exceed_budget(self) -> None:
        perf = _make_perf(input_tokens=5_000, output_tokens=6_000)
        score = self._score(max_total_tokens=1_000, performance=perf)
        assert not score.tokens_within_budget
        assert any("tokens" in r.lower() and "exceeds budget" in r for r in score.failure_reasons)

    # --- tools_called extraction ---

    def test_tools_called_list_populated(self) -> None:
        tools = [_make_tool_call("distillery_status"), _make_tool_call("distillery_search")]
        score = self._score(tool_calls=tools)
        assert score.tools_called == ["distillery_status", "distillery_search"]

    def test_tools_called_empty(self) -> None:
        score = self._score(tool_calls=[])
        assert score.tools_called == []

    # --- multiple failures accumulated ---

    def test_multiple_failures_all_recorded(self) -> None:
        perf = _make_perf(total_latency_ms=999_999, input_tokens=50_000, output_tokens=50_000)
        score = self._score(
            expected_tools=["distillery_store"],
            tool_calls=[],
            response_must_contain=["hello"],
            final_response="goodbye",
            min_entries_stored=5,
            entries_stored=0,
            max_latency_ms=1_000.0,
            max_total_tokens=100,
            performance=perf,
        )
        assert not score.passed
        assert len(score.failure_reasons) >= 4


# ===========================================================================
# scenarios.py
# ===========================================================================


@pytest.mark.unit
class TestScenarioLoading:
    """Tests for the YAML scenario loader."""

    def _write_yaml(self, tmp_path: Path, name: str, content: str) -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        return p

    def test_load_scenario_single_dict(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "s.yaml",
            """\
            name: my-scenario
            skill: recall
            prompt: "/recall foo"
            """,
        )
        scenario = load_scenario(path)
        assert scenario.name == "my-scenario"
        assert scenario.skill == "recall"
        assert scenario.prompt == "/recall foo"

    def test_load_scenario_from_list_returns_first(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "multi.yaml",
            """\
            - name: first
              skill: distill
              prompt: "/distill a"
            - name: second
              skill: distill
              prompt: "/distill b"
            """,
        )
        scenario = load_scenario(path)
        assert scenario.name == "first"

    def test_load_scenarios_returns_all(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "multi.yaml",
            """\
            - name: first
              skill: distill
              prompt: "/distill a"
            - name: second
              skill: recall
              prompt: "/recall b"
            """,
        )
        scenarios = load_scenarios(path)
        assert len(scenarios) == 2
        assert scenarios[0].name == "first"
        assert scenarios[1].name == "second"

    def test_load_scenarios_single_dict_wraps_in_list(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "s.yaml",
            """\
            name: only
            skill: pour
            prompt: "/pour topic"
            """,
        )
        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        assert scenarios[0].name == "only"

    def test_load_scenarios_from_dir(self, tmp_path: Path) -> None:
        self._write_yaml(
            tmp_path,
            "a.yaml",
            """\
            name: a-scenario
            skill: distill
            prompt: "/distill a"
            """,
        )
        self._write_yaml(
            tmp_path,
            "b.yaml",
            """\
            name: b-scenario
            skill: recall
            prompt: "/recall b"
            """,
        )
        scenarios = load_scenarios_from_dir(tmp_path)
        names = {s.name for s in scenarios}
        assert "a-scenario" in names
        assert "b-scenario" in names

    def test_load_scenarios_from_dir_empty(self, tmp_path: Path) -> None:
        scenarios = load_scenarios_from_dir(tmp_path)
        assert scenarios == []

    def test_defaults_applied(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "minimal.yaml",
            """\
            name: minimal
            skill: distill
            prompt: "/distill x"
            """,
        )
        s = load_scenario(path)
        assert s.description == ""
        assert s.seed_entries == []
        assert s.expected_tools == []
        assert s.response_must_contain == []
        assert s.min_entries_stored == 0
        assert s.max_latency_ms == 60_000.0
        assert s.max_total_tokens == 10_000
        assert s.model == "claude-haiku-4-5-20251001"
        assert s.max_tokens == 4096

    def test_seed_entry_defaults(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "seeded.yaml",
            """\
            name: seeded
            skill: recall
            prompt: "/recall x"
            seed_entries:
              - content: "hello world"
                entry_type: session
            """,
        )
        s = load_scenario(path)
        assert len(s.seed_entries) == 1
        se = s.seed_entries[0]
        assert se.content == "hello world"
        assert se.entry_type == "session"
        assert se.author == "eval-seed"
        assert se.tags == []
        assert se.project is None
        assert se.metadata == {}

    def test_seed_entry_explicit_fields(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "seeded.yaml",
            """\
            name: seeded
            skill: recall
            prompt: "/recall x"
            seed_entries:
              - content: "note"
                entry_type: bookmark
                author: alice
                tags: [web, ai]
                project: myproject
                metadata:
                  url: https://example.com
            """,
        )
        s = load_scenario(path)
        se = s.seed_entries[0]
        assert se.author == "alice"
        assert se.tags == ["web", "ai"]
        assert se.project == "myproject"
        assert se.metadata["url"] == "https://example.com"

    def test_numeric_budget_overrides(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "budget.yaml",
            """\
            name: budget-test
            skill: distill
            prompt: "/distill x"
            max_latency_ms: 5000
            max_total_tokens: 2000
            max_tokens: 1024
            """,
        )
        s = load_scenario(path)
        assert s.max_latency_ms == 5000.0
        assert s.max_total_tokens == 2000
        assert s.max_tokens == 1024

    def test_response_constraints_loaded(self, tmp_path: Path) -> None:
        path = self._write_yaml(
            tmp_path,
            "content.yaml",
            """\
            name: content-test
            skill: recall
            prompt: "/recall q"
            response_must_contain: ["hello", "world"]
            response_must_not_contain: ["error"]
            """,
        )
        s = load_scenario(path)
        assert s.response_must_contain == ["hello", "world"]
        assert s.response_must_not_contain == ["error"]


# ===========================================================================
# mcp_bridge.py — _MockEmbeddingProvider and MCPBridge
# ===========================================================================


@pytest.mark.unit
class TestMockEmbeddingProvider:
    """Unit tests for the hash-based embedding provider used by the eval bridge."""

    def setup_method(self) -> None:
        from distillery.mcp._stub_embedding import HashEmbeddingProvider

        self.provider = HashEmbeddingProvider(dimensions=4)

    def test_dimensions_property(self) -> None:
        assert self.provider.dimensions == 4

    def test_model_name_property(self) -> None:
        assert self.provider.model_name == "mock-hash"

    def test_embed_returns_correct_dims(self) -> None:
        vec = self.provider.embed("hello")
        assert len(vec) == 4

    def test_embed_normalized(self) -> None:
        import math

        vec = self.provider.embed("hello world")
        magnitude = math.sqrt(sum(x * x for x in vec))
        assert magnitude == pytest.approx(1.0, abs=1e-6)

    def test_embed_batch_consistency(self) -> None:
        texts = ["alpha", "beta", "gamma"]
        batch = self.provider.embed_batch(texts)
        assert len(batch) == 3
        for i, text in enumerate(texts):
            assert batch[i] == self.provider.embed(text)

    def test_same_text_same_vector(self) -> None:
        v1 = self.provider.embed("deterministic input")
        v2 = self.provider.embed("deterministic input")
        assert v1 == v2

    def test_different_text_different_vector(self) -> None:
        v1 = self.provider.embed("apple")
        v2 = self.provider.embed("orange")
        # With overwhelming probability the hashes differ.
        assert v1 != v2

    def test_embed_batch_empty(self) -> None:
        result = self.provider.embed_batch([])
        assert result == []


@pytest.mark.unit
class TestMCPBridgeAsync:
    """Async unit tests for MCPBridge (no Anthropic API key required)."""

    @pytest.mark.asyncio
    async def test_create_empty(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        bridge = await MCPBridge.create()
        count = await bridge.count_stored_entries()
        assert count == 0
        await bridge.close()

    @pytest.mark.asyncio
    async def test_create_with_seed_entries(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        seeds = [
            SeedEntry(content="first entry", entry_type="session"),
            SeedEntry(content="second entry", entry_type="bookmark"),
        ]
        bridge = await MCPBridge.create(seed_entries=seeds)
        count = await bridge.count_stored_entries()
        assert count == 2
        await bridge.close()

    @pytest.mark.asyncio
    async def test_count_entries_since_seed(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        seeds = [SeedEntry(content="seed content", entry_type="session")]
        bridge = await MCPBridge.create(seed_entries=seeds)
        seed_count = await bridge.count_stored_entries()

        # Store one more via tool call.
        await bridge.call_tool(
            "distillery_store",
            {"content": "new entry", "entry_type": "session", "author": "test"},
        )
        new_entries = await bridge.count_entries_since_seed(seed_count)
        assert new_entries == 1
        await bridge.close()

    @pytest.mark.asyncio
    async def test_count_entries_since_seed_zero_new(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        bridge = await MCPBridge.create()
        seed_count = await bridge.count_stored_entries()
        new_entries = await bridge.count_entries_since_seed(seed_count)
        assert new_entries == 0
        await bridge.close()

    @pytest.mark.asyncio
    async def test_get_tool_schemas_count(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        bridge = await MCPBridge.create()
        schemas = bridge.get_tool_schemas()
        # All 17 distillery tools must be present.
        assert len(schemas) == 17
        names = {s["name"] for s in schemas}
        assert "distillery_store" in names
        assert "distillery_search" in names
        assert "distillery_metrics" in names
        await bridge.close()

    @pytest.mark.asyncio
    async def test_call_tool_status(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        bridge = await MCPBridge.create()
        result = await bridge.call_tool("distillery_metrics", {"scope": "summary"})
        assert isinstance(result, dict)
        assert "error" not in result or not result.get("error")
        await bridge.close()

    @pytest.mark.asyncio
    async def test_call_tool_store_and_retrieve(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        bridge = await MCPBridge.create()
        store_result = await bridge.call_tool(
            "distillery_store",
            {"content": "test knowledge entry", "entry_type": "session", "author": "unit-test"},
        )
        assert isinstance(store_result, dict)
        count = await bridge.count_stored_entries()
        assert count == 1
        await bridge.close()

    @pytest.mark.asyncio
    async def test_call_tool_unknown_returns_error(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        bridge = await MCPBridge.create()
        result = await bridge.call_tool("distillery_nonexistent_tool", {})
        assert result.get("error") is True
        await bridge.close()

    @pytest.mark.asyncio
    async def test_call_tool_type_schemas(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        bridge = await MCPBridge.create()
        result = await bridge.call_tool("distillery_type_schemas", {})
        assert isinstance(result, dict)
        await bridge.close()

    @pytest.mark.asyncio
    async def test_call_tool_list(self) -> None:
        from distillery.eval.mcp_bridge import MCPBridge

        seeds = [SeedEntry(content="hello", entry_type="session")]
        bridge = await MCPBridge.create(seed_entries=seeds)
        result = await bridge.call_tool("distillery_list", {})
        assert isinstance(result, dict)
        await bridge.close()


# ===========================================================================
# runner.py — _load_skill_prompt
# ===========================================================================


@pytest.mark.unit
class TestLoadSkillPrompt:
    """Unit tests for the _load_skill_prompt helper."""

    def test_fallback_when_file_missing(self) -> None:
        from distillery.eval.runner import _load_skill_prompt

        prompt = _load_skill_prompt("nonexistent-skill-xyz")
        assert len(prompt) > 0
        assert "distillery" in prompt.lower() or "skill" in prompt.lower()

    def test_loads_plain_content(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from distillery.eval import runner

        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("This is the skill description.", encoding="utf-8")

        monkeypatch.setattr(runner, "_SKILLS_DIR", tmp_path)
        prompt = runner._load_skill_prompt("myskill")
        assert prompt == "This is the skill description."

    def test_strips_yaml_frontmatter(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from distillery.eval import runner

        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\ntitle: My Skill\nversion: 1\n---\nActual skill content here.",
            encoding="utf-8",
        )

        monkeypatch.setattr(runner, "_SKILLS_DIR", tmp_path)
        prompt = runner._load_skill_prompt("myskill")
        assert prompt == "Actual skill content here."
        assert "---" not in prompt
        assert "title:" not in prompt

    def test_content_without_frontmatter_returned_as_is(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from distillery.eval import runner

        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("No frontmatter here.\nJust content.", encoding="utf-8")

        monkeypatch.setattr(runner, "_SKILLS_DIR", tmp_path)
        prompt = runner._load_skill_prompt("myskill")
        assert "No frontmatter here." in prompt

    def test_incomplete_frontmatter_not_stripped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file that starts with --- but has no closing --- keeps all content."""
        from distillery.eval import runner

        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\ntitle: Missing close\nContent here.", encoding="utf-8"
        )

        monkeypatch.setattr(runner, "_SKILLS_DIR", tmp_path)
        prompt = runner._load_skill_prompt("myskill")
        # Only 2 parts after split on ---, so fallback to full content
        assert "---" in prompt or "Missing close" in prompt


# ===========================================================================
# runner.py -- ClaudeEvalRunner.__init__
# ===========================================================================


@pytest.mark.unit
class TestClaudeEvalRunnerInit:
    """Tests for ClaudeEvalRunner constructor validation."""

    def test_raises_file_not_found_when_cli_missing(self) -> None:
        from distillery.eval.runner import ClaudeEvalRunner

        with pytest.raises(FileNotFoundError, match="not found"):
            ClaudeEvalRunner(claude_cli="nonexistent-claude-binary-xyz-99")

    def test_no_anthropic_api_key_required(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ClaudeEvalRunner no longer requires ANTHROPIC_API_KEY."""
        from distillery.eval.runner import ClaudeEvalRunner

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Should NOT raise -- just needs `claude` CLI on PATH.
        # We use a real binary that exists (`python3`) to satisfy shutil.which.
        runner = ClaudeEvalRunner(claude_cli="python3")
        assert runner._claude_cli is not None


# ===========================================================================
# runner.py -- _parse_stream_events
# ===========================================================================


@pytest.mark.unit
class TestParseStreamEvents:
    """Tests for the stream-json parser used by the CLI-based eval runner."""

    def test_empty_input(self) -> None:
        from distillery.eval.runner import _parse_stream_events

        tool_calls, final_response, perf = _parse_stream_events([])
        assert tool_calls == []
        assert final_response == ""
        assert perf.total_latency_ms == 0.0
        assert perf.input_tokens == 0
        assert perf.output_tokens == 0

    def test_text_only_response(self) -> None:
        import json

        from distillery.eval.runner import _parse_stream_events

        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Hello, world!"}],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "duration_ms": 1500,
                    "usage": {"input_tokens": 50, "output_tokens": 25},
                    "num_turns": 1,
                    "total_cost_usd": 0.001,
                }
            ),
        ]
        tool_calls, final_response, perf = _parse_stream_events(lines)
        assert tool_calls == []
        assert final_response == "Hello, world!"
        assert perf.total_latency_ms == 1500.0
        assert perf.input_tokens == 50
        assert perf.output_tokens == 25
        assert perf.api_call_count == 1
        assert perf.total_cost_usd == pytest.approx(0.001)

    def test_tool_use_and_result(self) -> None:
        import json

        from distillery.eval.runner import _parse_stream_events

        lines = [
            # Assistant message with tool_use block
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_001",
                                "name": "distillery_store",
                                "input": {
                                    "content": "test entry",
                                    "entry_type": "session",
                                    "author": "eval",
                                },
                            }
                        ],
                    },
                }
            ),
            # Tool result
            json.dumps(
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_001",
                    "content": json.dumps({"id": "abc-123", "status": "created"}),
                }
            ),
            # Final assistant text
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Entry stored successfully."}],
                    },
                }
            ),
            # Result event
            json.dumps(
                {
                    "type": "result",
                    "duration_ms": 3200,
                    "usage": {"input_tokens": 200, "output_tokens": 80},
                    "num_turns": 2,
                    "total_cost_usd": 0.005,
                }
            ),
        ]
        tool_calls, final_response, perf = _parse_stream_events(lines)
        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "distillery_store"
        assert tool_calls[0].arguments["content"] == "test entry"
        assert tool_calls[0].response["id"] == "abc-123"
        assert tool_calls[0].latency_ms == 0.0  # CLI doesn't expose per-tool timing
        assert tool_calls[0].error is None
        assert final_response == "Entry stored successfully."
        assert perf.tool_call_count == 1
        assert perf.api_call_count == 2
        assert perf.total_latency_ms == 3200.0
        assert perf.total_cost_usd == pytest.approx(0.005)

    def test_multiple_tool_calls(self) -> None:
        import json

        from distillery.eval.runner import _parse_stream_events

        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_001",
                                "name": "distillery_status",
                                "input": {},
                            },
                            {
                                "type": "tool_use",
                                "id": "tu_002",
                                "name": "distillery_search",
                                "input": {"query": "python testing"},
                            },
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_001",
                    "content": json.dumps({"status": "ok", "entries": 42}),
                }
            ),
            json.dumps(
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_002",
                    "content": json.dumps({"count": 3, "entries": []}),
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Found 3 results."}],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "duration_ms": 5000,
                    "usage": {"input_tokens": 500, "output_tokens": 150},
                    "num_turns": 2,
                }
            ),
        ]
        tool_calls, final_response, perf = _parse_stream_events(lines)
        assert len(tool_calls) == 2
        assert tool_calls[0].tool_name == "distillery_status"
        assert tool_calls[1].tool_name == "distillery_search"
        assert perf.tool_call_count == 2
        assert perf.tool_latencies_ms == [0.0, 0.0]
        assert final_response == "Found 3 results."

    def test_tool_error_response(self) -> None:
        import json

        from distillery.eval.runner import _parse_stream_events

        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "tu_err",
                                "name": "distillery_get",
                                "input": {"entry_id": "bad-id"},
                            }
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_err",
                    "content": json.dumps({"error": True, "message": "Entry not found"}),
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "duration_ms": 800,
                    "usage": {"input_tokens": 100, "output_tokens": 30},
                    "num_turns": 1,
                }
            ),
        ]
        tool_calls, final_response, perf = _parse_stream_events(lines)
        assert len(tool_calls) == 1
        assert tool_calls[0].error == "Entry not found"

    def test_ignores_invalid_json_lines(self) -> None:
        import json

        from distillery.eval.runner import _parse_stream_events

        lines = [
            "not valid json",
            "",
            json.dumps(
                {
                    "type": "result",
                    "duration_ms": 100,
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                    "num_turns": 1,
                }
            ),
        ]
        tool_calls, final_response, perf = _parse_stream_events(lines)
        assert tool_calls == []
        assert perf.total_latency_ms == 100.0

    def test_missing_result_event_defaults(self) -> None:
        """If no result event is present, metrics default to zero."""
        import json

        from distillery.eval.runner import _parse_stream_events

        lines = [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "text", "text": "Partial output"}],
                    },
                }
            ),
        ]
        tool_calls, final_response, perf = _parse_stream_events(lines)
        assert final_response == "Partial output"
        assert perf.total_latency_ms == 0.0
        assert perf.input_tokens == 0
        assert perf.api_call_count == 0

    def test_total_cost_usd_absent_defaults_to_zero(self) -> None:
        import json

        from distillery.eval.runner import _parse_stream_events

        lines = [
            json.dumps(
                {
                    "type": "result",
                    "duration_ms": 500,
                    "usage": {"input_tokens": 20, "output_tokens": 10},
                    "num_turns": 1,
                }
            ),
        ]
        _, _, perf = _parse_stream_events(lines)
        assert perf.total_cost_usd == 0.0


# ===========================================================================
# mcp_bridge.py -- seed_file_store
# ===========================================================================


@pytest.mark.unit
class TestSeedFileStore:
    """Tests for the seed_file_store async function."""

    @pytest.mark.asyncio
    async def test_seeds_entries_and_returns_count(self, tmp_path: Path) -> None:
        from distillery.eval.mcp_bridge import seed_file_store

        db_path = str(tmp_path / "test.db")
        seeds = [
            SeedEntry(content="first entry", entry_type="session"),
            SeedEntry(content="second entry", entry_type="bookmark", author="alice"),
            SeedEntry(content="third entry", entry_type="session"),
        ]
        count = await seed_file_store(db_path=db_path, seed_entries=seeds)
        assert count == 3

    @pytest.mark.asyncio
    async def test_seeds_zero_entries(self, tmp_path: Path) -> None:
        from distillery.eval.mcp_bridge import seed_file_store

        db_path = str(tmp_path / "empty.db")
        count = await seed_file_store(db_path=db_path, seed_entries=[])
        assert count == 0

    @pytest.mark.asyncio
    async def test_creates_readable_db_file(self, tmp_path: Path) -> None:
        """The seeded DB should be openable and contain the expected entries."""
        from distillery.eval.mcp_bridge import seed_file_store
        from distillery.mcp._stub_embedding import HashEmbeddingProvider
        from distillery.store.duckdb import DuckDBStore

        db_path = str(tmp_path / "readable.db")
        seeds = [
            SeedEntry(content="knowledge entry alpha", entry_type="session"),
            SeedEntry(content="knowledge entry beta", entry_type="reference"),
        ]
        count = await seed_file_store(db_path=db_path, seed_entries=seeds)
        assert count == 2

        # Reopen and verify using the same provider type as seed_file_store.
        provider = HashEmbeddingProvider(dimensions=4)
        store = DuckDBStore(db_path=db_path, embedding_provider=provider)
        await store.initialize()
        results = await store.list_entries(filters=None, limit=100, offset=0)
        assert len(results) == 2
        await store.close()
