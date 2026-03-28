"""Claude-powered eval runner.

Drives the actual Claude API against an in-process MCP bridge to execute skill
scenarios end-to-end.  Records performance (latency, token usage) and delegates
effectiveness scoring to :mod:`distillery.eval.scorer`.

Requires the ``anthropic`` package (``pip install distillery[eval]``).
Set ``ANTHROPIC_API_KEY`` in the environment (or pass ``api_key`` directly).
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from distillery.eval.mcp_bridge import MCPBridge
from distillery.eval.models import (
    EffectivenessScore,
    EvalScenario,
    PerformanceMetrics,
    ScenarioResult,
    ToolCallRecord,
)
from distillery.eval.scorer import score_effectiveness

logger = logging.getLogger(__name__)

# Path to the skills directory (relative to the repo root).
_SKILLS_DIR = Path(__file__).resolve().parents[3] / ".claude" / "skills"


def _load_skill_prompt(skill_name: str) -> str:
    """Return the SKILL.md content for *skill_name* as a system prompt.

    Falls back to a generic prompt if the file is not found so that tests
    still run in CI where the working directory may differ.

    Args:
        skill_name: Skill directory name (e.g. ``"recall"``).

    Returns:
        String content of the SKILL.md, or a minimal fallback prompt.
    """
    skill_path = _SKILLS_DIR / skill_name / "SKILL.md"
    if skill_path.exists():
        raw = skill_path.read_text(encoding="utf-8")
        # Strip YAML frontmatter (--- ... ---) if present.
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
        return raw.strip()

    logger.warning("SKILL.md not found at %s — using fallback prompt", skill_path)
    return (
        f"You are a helpful assistant with access to the Distillery knowledge base tools. "
        f"Execute the '{skill_name}' skill based on the user's request."
    )


class ClaudeEvalRunner:
    """Runs :class:`~distillery.eval.models.EvalScenario` instances against Claude.

    Each call to :meth:`run` creates a fresh in-memory store, seeds it,
    then drives a real Claude API conversation using the skill's SKILL.md
    as the system prompt.  All MCP tool calls are intercepted and routed
    to in-process handlers — no subprocess or stdio transport needed.

    Args:
        api_key: Anthropic API key.  Defaults to ``ANTHROPIC_API_KEY`` env var.
        skills_dir: Override the path to the ``.claude/skills/`` directory.
    """

    def __init__(
        self,
        api_key: str | None = None,
        skills_dir: Path | None = None,
    ) -> None:
        try:
            import anthropic  # noqa: F401  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for eval runs. "
                "Install it with: pip install 'distillery[eval]'"
            ) from exc

        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise ValueError(
                "Anthropic API key not found. "
                "Set ANTHROPIC_API_KEY or pass api_key= to ClaudeEvalRunner."
            )
        self._skills_dir = skills_dir

    def _get_client(self) -> Any:
        import anthropic  # type: ignore[import-not-found]

        return anthropic.AsyncAnthropic(api_key=self._api_key)

    def _get_skill_prompt(self, skill_name: str) -> str:
        if self._skills_dir is not None:
            skill_path = self._skills_dir / skill_name / "SKILL.md"
            if skill_path.exists():
                raw = skill_path.read_text(encoding="utf-8")
                if raw.startswith("---"):
                    parts = raw.split("---", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
                return raw.strip()
        return _load_skill_prompt(skill_name)

    async def run(self, scenario: EvalScenario) -> ScenarioResult:
        """Execute a scenario and return the full result with metrics.

        Args:
            scenario: The :class:`~distillery.eval.models.EvalScenario` to run.

        Returns:
            :class:`~distillery.eval.models.ScenarioResult` with performance
            and effectiveness data.
        """
        bridge: MCPBridge | None = None
        try:
            bridge = await MCPBridge.create(seed_entries=scenario.seed_entries)
            seed_count = await bridge.count_stored_entries()
            result = await self._execute(scenario, bridge, seed_count)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Eval runner error for scenario %r", scenario.name)
            perf = PerformanceMetrics(
                total_latency_ms=0.0,
                input_tokens=0,
                output_tokens=0,
                api_call_count=0,
                tool_call_count=0,
            )
            eff = EffectivenessScore(
                tools_called=[],
                required_tools_present=False,
                tool_order_correct=False,
                entries_stored=0,
                entries_retrieved=0,
                response_contains_all=False,
                response_excludes_all=True,
                latency_within_budget=False,
                tokens_within_budget=False,
                failure_reasons=[f"Runner error: {exc}"],
            )
            return ScenarioResult(
                scenario_name=scenario.name,
                skill=scenario.skill,
                passed=False,
                performance=perf,
                effectiveness=eff,
                tool_calls=[],
                final_response="",
                error=str(exc),
            )
        finally:
            if bridge is not None:
                await bridge.close()

        return result

    async def _execute(
        self,
        scenario: EvalScenario,
        bridge: MCPBridge,
        seed_count: int,
    ) -> ScenarioResult:
        """Inner execution loop."""
        client = self._get_client()
        system_prompt = self._get_skill_prompt(scenario.skill)
        tool_schemas = bridge.get_tool_schemas()

        messages: list[dict[str, Any]] = [{"role": "user", "content": scenario.prompt}]
        tool_calls: list[ToolCallRecord] = []
        total_input_tokens = 0
        total_output_tokens = 0
        api_call_count = 0
        tool_latencies: list[float] = []
        last_search_count = 0
        last_response_content: list[Any] = []

        run_start = time.perf_counter()
        max_iterations = 20  # Guard against infinite tool-use loops.

        while api_call_count < max_iterations:
            api_call_count += 1
            response = await client.messages.create(
                model=scenario.model,
                max_tokens=scenario.max_tokens,
                system=system_prompt,
                tools=tool_schemas,
                messages=messages,
            )

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            last_response_content = list(response.content)

            # Append the assistant turn (may include text + tool_use blocks).
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break

            # Process all tool_use blocks in this turn.
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                call_start = time.perf_counter()
                tool_resp = await bridge.call_tool(block.name, block.input)
                call_latency_ms = (time.perf_counter() - call_start) * 1000
                tool_latencies.append(call_latency_ms)

                error_val: str | None = None
                if isinstance(tool_resp, dict) and tool_resp.get("error"):
                    error_val = str(tool_resp.get("message", "unknown error"))

                # Track search results count for effectiveness scoring.
                if block.name == "distillery_search" and isinstance(tool_resp, dict):
                    last_search_count = tool_resp.get("count", 0)

                tool_calls.append(
                    ToolCallRecord(
                        tool_name=block.name,
                        arguments=dict(block.input),
                        response=tool_resp,
                        latency_ms=call_latency_ms,
                        error=error_val,
                    )
                )

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(tool_resp),
                    }
                )

            messages.append({"role": "user", "content": tool_results})

        # Check if we hit the iteration cap.
        hit_iteration_cap = api_call_count >= max_iterations

        total_latency_ms = (time.perf_counter() - run_start) * 1000

        # Extract final text response from the last assistant turn.
        final_response = ""
        for block in last_response_content:
            if hasattr(block, "text"):
                final_response += block.text

        performance = PerformanceMetrics(
            total_latency_ms=total_latency_ms,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            api_call_count=api_call_count,
            tool_call_count=len(tool_calls),
            tool_latencies_ms=tool_latencies,
        )

        entries_stored = await bridge.count_entries_since_seed(seed_count)
        effectiveness = score_effectiveness(
            scenario=scenario,
            tool_calls=tool_calls,
            final_response=final_response,
            entries_stored=entries_stored,
            entries_retrieved=last_search_count,
            performance=performance,
        )

        # If we hit the iteration cap, mark as failure.
        if hit_iteration_cap:
            effectiveness.failure_reasons.append(
                f"Reached maximum iterations ({max_iterations}) without completing"
            )
            # Override passed status to False when iteration cap is hit.
            passed = False
        else:
            passed = effectiveness.passed

        return ScenarioResult(
            scenario_name=scenario.name,
            skill=scenario.skill,
            passed=passed,
            performance=performance,
            effectiveness=effectiveness,
            tool_calls=tool_calls,
            final_response=final_response,
        )