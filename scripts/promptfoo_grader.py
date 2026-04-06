"""promptfoo Python grading functions for Distillery eval assertions.

Each function receives (output, context) and returns a GradingResult dict:
    {"pass": True/False, "score": 0.0-1.0, "reason": "..."}

The output is the structured dict from promptfoo_provider.py:
    {"text": "...", "tool_calls": [{"name": "...", "input": {...}}, ...]}
"""

from __future__ import annotations

import json
import re
from typing import Any


def _parse_output(output: Any) -> tuple[str, list[str]]:
    """Extract text and tool call names from provider output."""
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return output, []

    if isinstance(output, dict):
        text = output.get("text", "")
        tool_calls = output.get("tool_calls")
        if not isinstance(tool_calls, list):
            tool_calls = []
        names = [t.get("name", "") for t in tool_calls if isinstance(t, dict)]
        return str(text), names

    return str(output), []


def _grade(
    output: Any,
    tool_names: list[str],
    text_pattern: str,
) -> dict[str, Any]:
    """Common grading logic: pass if any expected tool was called OR text matches pattern."""
    text, names = _parse_output(output)
    tool_match = any(n in names for n in tool_names)
    text_match = bool(re.search(text_pattern, text, re.IGNORECASE))

    if tool_match or text_match:
        return {"pass": True, "score": 1.0, "reason": "Tool called or text matched"}

    return {
        "pass": False,
        "score": 0.0,
        "reason": f"No matching tool call ({tool_names}) and text did not match /{text_pattern}/. "
                  f"Tools called: {names}. Text preview: {text[:200]}",
    }


# ---- /distill ----------------------------------------------------------------

def get_assert_distill_store(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_metrics", "distillery_store", "distillery_find_similar"],
        r"stored|saved|entry.*id|created",
    )


def get_assert_distill_dedup(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_metrics", "distillery_find_similar", "distillery_store"],
        r"stored|saved|entry.*id|created|duplicate|dedup",
    )


# ---- /recall -----------------------------------------------------------------

def get_assert_recall_search(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_search"],
        r"duckdb|storage|database",
    )


def get_assert_recall_empty(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_search"],
        r"no.*(?:entries|results|information|data)|knowledge base|search|cach|doesn.t have",
    )


# ---- /bookmark ---------------------------------------------------------------

def get_assert_bookmark_store(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_metrics", "distillery_store", "distillery_find_similar"],
        r"bookmark|stored|saved|entry.*id",
    )


def get_assert_bookmark_dedup(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_find_similar", "distillery_store", "distillery_metrics"],
        r"bookmark|stored|saved|duplicate|already|entry.*id",
    )


# ---- /pour -------------------------------------------------------------------

def get_assert_pour_synthesis(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_search"],
        r"storage|architecture|duckdb|decision",
    )


def get_assert_pour_sparse(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_search"],
        r"decision|log|no.*(?:entries|results)|knowledge|pour|synthe",
    )


# ---- /watch ------------------------------------------------------------------

def get_assert_watch_list(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_watch", "distillery_metrics"],
        r"feed.*source|watch|no.*(?:sources|feeds)|configured|empty|sources.*monitored",
    )


def get_assert_watch_add(output: str, context: dict[str, Any]) -> dict[str, Any]:
    return _grade(
        output,
        ["distillery_watch"],
        r"added|registered|hacker news|rss|feed.*source",
    )
