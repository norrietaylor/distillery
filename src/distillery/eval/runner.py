"""Claude CLI-powered eval runner.

Drives the Claude Code CLI (``claude -p``) against a temporary MCP server
subprocess to execute skill scenarios end-to-end.  Records performance
(latency, token usage, cost) and delegates effectiveness scoring to
:mod:`distillery.eval.scorer`.

Requires the ``claude`` CLI binary on ``PATH`` (install with
``npm install -g @anthropic-ai/claude-code``).  Authenticates via
``CLAUDE_CODE_OAUTH_TOKEN`` (no Anthropic API key needed).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from distillery.eval.mcp_bridge import seed_file_store
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
_SKILLS_DIR = Path(__file__).parents[4] / ".claude" / "skills"


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

    logger.warning("SKILL.md not found at %s -- using fallback prompt", skill_path)
    return (
        f"You are a helpful assistant with access to the Distillery knowledge base tools. "
        f"Execute the '{skill_name}' skill based on the user's request."
    )


def _parse_stream_events(
    lines: list[str],
) -> tuple[list[ToolCallRecord], str, PerformanceMetrics]:
    """Parse ``--output-format stream-json`` lines from the Claude CLI.

    Each non-empty line is a JSON object. The function extracts:

    - ``ToolCallRecord`` instances from ``tool_use`` content blocks in assistant
      messages and their corresponding ``tool_result`` blocks.
    - Final text response from the last assistant message's text blocks.
    - Aggregate metrics from the ``result`` event.

    Args:
        lines: Raw stdout lines from the CLI subprocess.

    Returns:
        Tuple of (tool_calls, final_response, performance_metrics).
    """
    tool_calls: list[ToolCallRecord] = []
    final_text_parts: list[str] = []
    total_latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    api_call_count: int = 0
    total_cost_usd: float = 0.0

    # Collect pending tool_use blocks awaiting their results.
    pending_tool_uses: dict[str, dict[str, Any]] = {}
    # Track tool results by tool_use_id.
    tool_results: dict[str, Any] = {}

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")

        if event_type == "assistant":
            # Assistant message: extract text blocks and tool_use blocks.
            message = event.get("message", {})
            content_blocks: list[dict[str, Any]] = message.get("content", [])
            text_parts: list[str] = []
            for block in content_blocks:
                block_type = block.get("type", "")
                if block_type == "text":
                    text_parts.append(block.get("text", ""))
                elif block_type == "tool_use":
                    tool_id = block.get("id", "")
                    pending_tool_uses[tool_id] = {
                        "tool_name": block.get("name", ""),
                        "arguments": block.get("input", {}),
                    }
            # Always update final text from the latest assistant message.
            if text_parts:
                final_text_parts = text_parts

        elif event_type == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                tool_id = block.get("id", "")
                pending_tool_uses[tool_id] = {
                    "tool_name": block.get("name", ""),
                    "arguments": block.get("input", {}),
                }
            elif block.get("type") == "text":
                pass  # Text accumulated via content_block_delta or assistant event

        elif event_type == "content_block_delta":
            # Accumulate tool input JSON deltas if needed.
            pass

        elif event_type == "content_block_stop":
            pass

        elif event_type == "tool_result":
            # Tool result: pair with the pending tool_use.
            tool_use_id = event.get("tool_use_id", "")
            content = event.get("content", "")
            if isinstance(content, str):
                try:
                    parsed: Any = json.loads(content)
                except json.JSONDecodeError:
                    parsed = {"text": content}
            elif isinstance(content, list) and content:
                # Content blocks array -- extract text.
                text_parts_result = []
                for cb in content:
                    if isinstance(cb, dict) and cb.get("type") == "text":
                        text_parts_result.append(cb.get("text", ""))
                raw_text = "".join(text_parts_result)
                try:
                    parsed = json.loads(raw_text)
                except json.JSONDecodeError:
                    parsed = {"text": raw_text}
            else:
                parsed = {"text": str(content)}
            tool_results[tool_use_id] = parsed

        elif event_type == "result":
            # Aggregate metrics from the result event.
            total_latency_ms = float(event.get("duration_ms", 0))
            usage = event.get("usage", {})
            input_tokens = int(usage.get("input_tokens", 0))
            output_tokens = int(usage.get("output_tokens", 0))
            api_call_count = int(event.get("num_turns", 0))
            total_cost_usd = float(event.get("total_cost_usd", 0.0))

    # Build ToolCallRecords by matching pending tool_uses with their results.
    for tool_id, tool_info in pending_tool_uses.items():
        response = tool_results.get(tool_id, {})
        error_val: str | None = None
        if isinstance(response, dict) and response.get("error"):
            error_val = str(response.get("message", "unknown error"))

        tool_calls.append(
            ToolCallRecord(
                tool_name=tool_info["tool_name"],
                arguments=tool_info["arguments"],
                response=response if isinstance(response, dict) else {"text": str(response)},
                latency_ms=0.0,  # CLI does not expose per-tool timing.
                error=error_val,
            )
        )

    tool_call_count = len(tool_calls)
    final_response = "".join(final_text_parts)

    performance = PerformanceMetrics(
        total_latency_ms=total_latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        api_call_count=api_call_count,
        tool_call_count=tool_call_count,
        tool_latencies_ms=[0.0] * tool_call_count,
        total_cost_usd=total_cost_usd,
    )

    return tool_calls, final_response, performance


class ClaudeEvalRunner:
    """Runs :class:`~distillery.eval.models.EvalScenario` instances via the Claude CLI.

    Each call to :meth:`run` creates a temporary directory with a DuckDB file,
    a ``distillery.yaml`` config, and an MCP config JSON file, then invokes the
    ``claude`` CLI subprocess.  The CLI spawns its own MCP server subprocess via
    the ``--mcp-config`` file.

    Args:
        claude_cli: Path or name of the Claude CLI binary (default ``"claude"``).
        skills_dir: Override the path to the ``.claude/skills/`` directory.
    """

    def __init__(
        self,
        claude_cli: str = "claude",
        skills_dir: Path | None = None,
    ) -> None:
        resolved = shutil.which(claude_cli)
        if resolved is None:
            raise FileNotFoundError(
                f"Claude CLI binary not found: {claude_cli!r}. "
                "Install with: npm install -g @anthropic-ai/claude-code"
            )
        self._claude_cli = resolved
        self._skills_dir = skills_dir

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
        try:
            result = await self._execute(scenario)
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

        return result

    async def _execute(self, scenario: EvalScenario) -> ScenarioResult:
        """Inner execution: create temp env, run CLI, parse results."""
        with tempfile.TemporaryDirectory(prefix="distillery-eval-") as tmpdir:
            tmp_path = Path(tmpdir)

            # 1. Create DuckDB file and seed it.
            db_path = str(tmp_path / "eval.db")
            seed_count = await seed_file_store(
                db_path=db_path,
                seed_entries=scenario.seed_entries,
                dimensions=4,
            )

            # 2. Write distillery.yaml config pointing at the temp DB.
            config_path = tmp_path / "distillery.yaml"
            config_path.write_text(
                "storage:\n"
                f"  backend: duckdb\n"
                f"  database_path: {db_path}\n"
                "embedding:\n"
                "  provider: mock\n"
                "  model: mock-hash\n"
                "  dimensions: 4\n",
                encoding="utf-8",
            )

            # 3. Write MCP config JSON.
            mcp_config_path = tmp_path / "mcp-config.json"
            mcp_config: dict[str, Any] = {
                "mcpServers": {
                    "distillery": {
                        "command": sys.executable,
                        "args": ["-m", "distillery.mcp"],
                        "env": {"DISTILLERY_CONFIG": str(config_path)},
                    }
                }
            }
            mcp_config_path.write_text(
                json.dumps(mcp_config, indent=2), encoding="utf-8"
            )

            # 4. Build CLI command.
            system_prompt = self._get_skill_prompt(scenario.skill)
            cmd = [
                self._claude_cli,
                "-p",
                scenario.prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--model",
                scenario.model,
                "--mcp-config",
                str(mcp_config_path),
                "--dangerously-skip-permissions",
                "--system-prompt",
                system_prompt,
                "--allowedTools",
                "mcp__distillery__*",
            ]
            # Note: --bare is intentionally omitted. In bare mode the CLI
            # only accepts ANTHROPIC_API_KEY and ignores OAuth tokens.
            # Without --bare, CLAUDE_CODE_OAUTH_TOKEN is read from env.

            # 5. Run the CLI subprocess.
            env = os.environ.copy()
            env["DISTILLERY_CONFIG"] = str(config_path)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")

            if proc.returncode != 0:
                logger.warning(
                    "Claude CLI exited with code %d for scenario %r: %s",
                    proc.returncode,
                    scenario.name,
                    stderr_text[:500],
                )

            # 6. Parse stream-json output.
            lines = stdout_text.splitlines()
            tool_calls, final_response, performance = _parse_stream_events(lines)

            # 7. Reopen DuckDB to count entries stored since seeding.
            from distillery.mcp._stub_embedding import HashEmbeddingProvider
            from distillery.store.duckdb import DuckDBStore

            provider = HashEmbeddingProvider(dimensions=4)
            store = DuckDBStore(db_path=db_path, embedding_provider=provider)
            await store.initialize()
            results = await store.list_entries(filters=None, limit=2147483647, offset=0)
            entries_stored = max(0, len(results) - seed_count)

            # Count search results from tool calls.
            last_search_count = 0
            for tc in tool_calls:
                if tc.tool_name == "distillery_search" and isinstance(tc.response, dict):
                    last_search_count = tc.response.get("count", 0)

            await store.close()

            # 8. Score effectiveness.
            effectiveness = score_effectiveness(
                scenario=scenario,
                tool_calls=tool_calls,
                final_response=final_response,
                entries_stored=entries_stored,
                entries_retrieved=last_search_count,
                performance=performance,
            )

            return ScenarioResult(
                scenario_name=scenario.name,
                skill=scenario.skill,
                passed=effectiveness.passed,
                performance=performance,
                effectiveness=effectiveness,
                tool_calls=tool_calls,
                final_response=final_response,
            )
