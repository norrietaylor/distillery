"""Effectiveness scoring for eval scenario results.

Compares the tool calls made by Claude and the final response against the
scenario's expectations and returns an :class:`~distillery.eval.models.EffectivenessScore`.
"""

from __future__ import annotations

from distillery.eval.models import (
    EffectivenessScore,
    EvalScenario,
    PerformanceMetrics,
    ToolCallRecord,
)


def score_effectiveness(
    scenario: EvalScenario,
    tool_calls: list[ToolCallRecord],
    final_response: str,
    entries_stored: int,
    entries_retrieved: int,
    performance: PerformanceMetrics,
) -> EffectivenessScore:
    """Score a scenario run against the scenario's expectations.

    Args:
        scenario: The scenario definition with expected outcomes.
        tool_calls: Ordered list of tool call records from the run.
        final_response: The final text response from Claude.
        entries_stored: Entries added to the store during this run.
        entries_retrieved: Results returned by the last search call.
        performance: Timing and token metrics from the run.

    Returns:
        :class:`~distillery.eval.models.EffectivenessScore` with pass/fail detail.
    """

    # Normalize tool names: the CLI reports tools with an MCP transport prefix
    # (e.g. "mcp__distillery__distillery_status") but scenarios use the bare
    # tool name ("distillery_status").  Strip the prefix for matching.
    def _normalize_tool_name(name: str) -> str:
        prefix = "mcp__distillery__"
        return name[len(prefix) :] if name.startswith(prefix) else name

    tools_called = [
        _normalize_tool_name(tc.tool_name)
        for tc in tool_calls
        if tc.tool_name not in ("Skill", "Read", "Bash", "Edit", "Glob", "Grep")
    ]
    failure_reasons: list[str] = []

    # --- required tools present (order-insensitive) -------------------------
    required_tools_present = True
    if scenario.expected_tools:
        missing = [t for t in scenario.expected_tools if t not in tools_called]
        if missing:
            required_tools_present = False
            failure_reasons.append(f"Missing required tools: {missing}")

    # --- tools in order (prefix match) --------------------------------------
    tool_order_correct = True
    if scenario.expected_tools_in_order:
        for i, expected in enumerate(scenario.expected_tools_in_order):
            if i >= len(tools_called) or tools_called[i] != expected:
                tool_order_correct = False
                failure_reasons.append(
                    f"Tool order mismatch at position {i}: "
                    f"expected {expected!r}, got {tools_called[i] if i < len(tools_called) else 'nothing'!r}"
                )
                break

    # --- entries stored -----------------------------------------------------
    if entries_stored < scenario.min_entries_stored:
        failure_reasons.append(
            f"Entries stored: {entries_stored} < required {scenario.min_entries_stored}"
        )

    # --- entries retrieved --------------------------------------------------
    if entries_retrieved < scenario.min_entries_retrieved:
        failure_reasons.append(
            f"Entries retrieved: {entries_retrieved} < required {scenario.min_entries_retrieved}"
        )

    # --- response content checks --------------------------------------------
    response_lower = final_response.lower()
    response_contains_all = True
    for substring in scenario.response_must_contain:
        if substring.lower() not in response_lower:
            response_contains_all = False
            failure_reasons.append(f"Response missing expected content: {substring!r}")

    response_excludes_all = True
    for substring in scenario.response_must_not_contain:
        if substring.lower() in response_lower:
            response_excludes_all = False
            failure_reasons.append(f"Response contains forbidden content: {substring!r}")

    # --- performance budgets ------------------------------------------------
    latency_within_budget = performance.total_latency_ms <= scenario.max_latency_ms
    if not latency_within_budget:
        failure_reasons.append(
            f"Latency {performance.total_latency_ms:.0f}ms exceeds budget {scenario.max_latency_ms:.0f}ms"
        )

    tokens_within_budget = performance.total_tokens <= scenario.max_total_tokens
    if not tokens_within_budget:
        failure_reasons.append(
            f"Total tokens {performance.total_tokens} exceeds budget {scenario.max_total_tokens}"
        )

    return EffectivenessScore(
        tools_called=tools_called,
        required_tools_present=required_tools_present,
        tool_order_correct=tool_order_correct,
        entries_stored=entries_stored,
        entries_retrieved=entries_retrieved,
        response_contains_all=response_contains_all,
        response_excludes_all=response_excludes_all,
        latency_within_budget=latency_within_budget,
        tokens_within_budget=tokens_within_budget,
        failure_reasons=failure_reasons,
    )
