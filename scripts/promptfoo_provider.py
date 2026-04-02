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
                "env": {
                    "DISTILLERY_CONFIG": "distillery-dev.yaml",
                    "JINA_API_KEY": os.environ.get("JINA_API_KEY", ""),
                },
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
                "stream-json",
                "--verbose",
                "--model",
                "claude-haiku-4-5-20251001",
                "--mcp-config",
                mcp_path,
                "--allowedTools",
                "mcp__distillery__*",
                "--dangerously-skip-permissions",
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

        # Parse stream-json output (one JSON object per line).
        # Event types: "assistant" (text/tool_use blocks), "tool_result", "result".
        response_text = ""
        tool_calls: list[dict[str, object]] = []
        input_tokens = 0
        output_tokens = 0

        for line in result.stdout.strip().splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            # Assistant messages contain tool_use blocks
            if event_type == "assistant":
                message = event.get("message", {})
                for block in message.get("content", []):
                    if block.get("type") == "tool_use":
                        # Strip MCP prefix: mcp__distillery__distillery_store -> distillery_store
                        raw_name = block.get("name", "")
                        name = raw_name.split("mcp__distillery__")[-1] if "mcp__distillery__" in raw_name else raw_name
                        tool_calls.append(
                            {"name": name, "input": block.get("input", {})}
                        )
                    elif block.get("type") == "text":
                        response_text = block.get("text", "")

            # Result event has the final response and usage
            if "result" in event:
                response_text = event["result"]
            if "usage" in event:
                usage = event["usage"]
                input_tokens += usage.get("input_tokens", 0)
                output_tokens += usage.get("output_tokens", 0)

        if result.returncode != 0:
            error_msg = (
                f"Claude CLI exited with code {result.returncode}: "
                f"{result.stderr[:500]}"
            )
            if not response_text:
                return {"error": error_msg}
            # Partial output with non-zero exit — return output but flag it.
            return {
                "output": {
                    "text": f"[PARTIAL - CLI error] {response_text}",
                    "tool_calls": tool_calls,
                },
                "error": error_msg,
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
