"""promptfoo Python provider — invokes Claude CLI with Distillery MCP.

Authenticates via CLAUDE_CODE_OAUTH_TOKEN (OAuth), not ANTHROPIC_API_KEY.
Called by promptfoo's ``python:`` provider for each test scenario.

Usage in promptfooconfig.yaml:
    providers:
      - id: "python:scripts/promptfoo_provider.py"

The ``call_api`` function receives the prompt, options, and context, and
returns a dict with ``output`` (structured, accessible in assertions).
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def call_api(
    prompt: str,
    options: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Invoke Claude CLI with Distillery MCP and return structured output.

    Returns a dict with:
        output: dict with ``text`` (response) and ``tool_calls`` list
        error: str | None
    """
    mcp_config = {
        "mcpServers": {
            "distillery": {
                "command": "distillery-mcp",
                "args": [],
                "env": {"DISTILLERY_CONFIG": "distillery-dev.yaml"},
            }
        }
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="promptfoo-mcp-", delete=False
    ) as f:
        json.dump(mcp_config, f)
        mcp_path = f.name

    try:
        result = subprocess.run(
            [
                "claude",
                "--output-format",
                "json",
                "--model",
                "claude-sonnet-4-5-latest",
                "--mcp-config",
                mcp_path,
                "--allowedTools",
                "mcp__distillery__*",
                "--max-turns",
                "5",
                "-p",
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"},
        )

        # Parse JSON output (single JSON object with result, tool calls, usage)
        response_text = ""
        tool_calls: list[dict[str, object]] = []
        input_tokens = 0
        output_tokens = 0

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            data = {}

        # --output-format json returns {result, messages, ...}
        if isinstance(data, dict):
            response_text = data.get("result", "")

            # Extract tool calls from the messages array
            for msg in data.get("messages", []):
                if msg.get("role") == "assistant":
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_use":
                            tool_calls.append(
                                {
                                    "name": block.get("name", ""),
                                    "input": block.get("input", {}),
                                }
                            )

            # Token usage from top-level or nested
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

        if result.returncode != 0 and not response_text:
            return {
                "error": f"Claude CLI exited with code {result.returncode}: "
                f"{result.stderr[:500]}",
            }

        return {
            "output": {
                "text": response_text,
                "tool_calls": tool_calls,
            },
            "tokenUsage": {
                "prompt": input_tokens,
                "completion": output_tokens,
                "total": input_tokens + output_tokens,
            },
        }

    except subprocess.TimeoutExpired:
        return {"error": "Claude CLI timed out after 120s"}
    finally:
        Path(mcp_path).unlink(missing_ok=True)
