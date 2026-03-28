"""Data models for the Distillery skill evaluation framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SeedEntry:
    """An entry to pre-load into the test store before running a scenario.

    Attributes:
        content: Full text of the entry.
        entry_type: One of the EntryType string values (e.g. ``"session"``).
        author: Author identifier.
        tags: Optional list of tags.
        project: Optional project name.
        metadata: Optional type-specific metadata.
    """

    content: str
    entry_type: str
    author: str = "eval-seed"
    tags: list[str] = field(default_factory=list)
    project: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalScenario:
    """A single eval scenario: a prompt sent to Claude plus expected outcomes.

    Attributes:
        name: Unique scenario identifier (used in test output).
        skill: Which skill is being tested (e.g. ``"recall"``, ``"distill"``).
        prompt: The user message sent to Claude.
        description: Human-readable description of what is being tested.
        seed_entries: Entries to pre-load into the test store.
        expected_tools: Tool names that must be called (order-insensitive).
        expected_tools_in_order: Tool names in the order they must appear.
        response_must_contain: Substrings the final response must contain.
        response_must_not_contain: Substrings the final response must not contain.
        min_entries_stored: Minimum number of entries that must be stored.
        min_entries_retrieved: Minimum number of search results expected.
        max_latency_ms: Fail if total latency exceeds this threshold.
        max_total_tokens: Fail if total tokens exceed this threshold.
        model: Claude model to use (defaults to haiku for speed).
        max_tokens: Max tokens for Claude responses.
    """

    name: str
    skill: str
    prompt: str
    description: str = ""
    seed_entries: list[SeedEntry] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    expected_tools_in_order: list[str] = field(default_factory=list)
    response_must_contain: list[str] = field(default_factory=list)
    response_must_not_contain: list[str] = field(default_factory=list)
    min_entries_stored: int = 0
    min_entries_retrieved: int = 0
    max_latency_ms: float = 60_000.0
    max_total_tokens: int = 10_000
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 4096


@dataclass
class ToolCallRecord:
    """A record of a single MCP tool call made by Claude.

    Attributes:
        tool_name: Name of the MCP tool called (e.g. ``"distillery_search"``).
        arguments: Arguments Claude passed to the tool.
        response: Parsed JSON response from the tool handler.
        latency_ms: Wall-clock time for the handler to complete, in milliseconds.
        error: If the tool returned an error payload, the error message.
    """

    tool_name: str
    arguments: dict[str, Any]
    response: dict[str, Any]
    latency_ms: float
    error: str | None = None


@dataclass
class PerformanceMetrics:
    """Timing and token-usage metrics for a single scenario run.

    Attributes:
        total_latency_ms: Wall-clock time from first API call to final response.
        input_tokens: Total input tokens across all API calls.
        output_tokens: Total output tokens across all API calls.
        api_call_count: Number of Anthropic API calls made (one per turn).
        tool_call_count: Total MCP tool calls made by Claude.
        tool_latencies_ms: Per-call latency list (same order as tool_calls).
        avg_tool_latency_ms: Mean latency across all tool calls, or 0 if none.
        tokens_per_second: Approximate output throughput.
    """

    total_latency_ms: float
    input_tokens: int
    output_tokens: int
    api_call_count: int
    tool_call_count: int
    tool_latencies_ms: list[float] = field(default_factory=list)

    @property
    def avg_tool_latency_ms(self) -> float:
        if not self.tool_latencies_ms:
            return 0.0
        return sum(self.tool_latencies_ms) / len(self.tool_latencies_ms)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def tokens_per_second(self) -> float:
        if self.total_latency_ms <= 0:
            return 0.0
        return self.output_tokens / (self.total_latency_ms / 1000.0)


@dataclass
class EffectivenessScore:
    """Correctness checks for a single scenario run.

    Attributes:
        tools_called: Actual tool names called, in order.
        required_tools_present: True if all expected_tools were called.
        tool_order_correct: True if expected_tools_in_order matches the prefix
            of tools_called (or is empty).
        entries_stored: Number of entries written to the store during the run.
        entries_retrieved: Number of search results returned in the last search.
        response_contains_all: True if all response_must_contain strings appear.
        response_excludes_all: True if no response_must_not_contain strings appear.
        latency_within_budget: True if total_latency_ms <= max_latency_ms.
        tokens_within_budget: True if total_tokens <= max_total_tokens.
        passed: Aggregate pass/fail (all checks must pass).
        failure_reasons: Human-readable list of failing checks.
    """

    tools_called: list[str]
    required_tools_present: bool
    tool_order_correct: bool
    entries_stored: int
    entries_retrieved: int
    response_contains_all: bool
    response_excludes_all: bool
    latency_within_budget: bool
    tokens_within_budget: bool
    failure_reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failure_reasons


@dataclass
class ScenarioResult:
    """Full result for a single scenario run.

    Attributes:
        scenario_name: Name from the scenario definition.
        skill: Skill under test.
        passed: True if all effectiveness checks passed.
        performance: Timing and token metrics.
        effectiveness: Correctness checks.
        tool_calls: Ordered list of all MCP tool call records.
        final_response: The last text response from Claude.
        error: If the runner itself raised an exception, the message.
    """

    scenario_name: str
    skill: str
    passed: bool
    performance: PerformanceMetrics
    effectiveness: EffectivenessScore
    tool_calls: list[ToolCallRecord]
    final_response: str
    error: str | None = None

    def summary(self) -> str:
        """Return a compact human-readable summary line."""
        status = "PASS" if self.passed else "FAIL"
        perf = (
            f"{self.performance.total_latency_ms:.0f}ms "
            f"{self.performance.total_tokens}tok "
            f"{self.performance.tool_call_count}calls"
        )
        reasons = ""
        if self.effectiveness.failure_reasons:
            reasons = " — " + "; ".join(self.effectiveness.failure_reasons)
        return f"[{status}] {self.scenario_name} ({perf}){reasons}"
