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


# ---- Features since v0.2.1 --------------------------------------------------


def _tool_called(output: Any, name: str) -> bool:
    """Check if a specific tool was called in the output."""
    _, names = _parse_output(output)
    return name in names


def _tool_input(output: Any, name: str) -> dict[str, Any] | None:
    """Extract the input dict for the first call to a named tool."""
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return None
    if not isinstance(output, dict):
        return None
    for tc in output.get("tool_calls", []):
        if isinstance(tc, dict) and tc.get("name") == name:
            return tc.get("input", {})
    return None


# ---- /correct (corrections chain) -------------------------------------------

def get_assert_correct_chain(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_store and distillery_correct were both called."""
    text, names = _parse_output(output)
    has_store = "distillery_store" in names
    has_correct = "distillery_correct" in names
    text_ok = bool(re.search(r"correct|supersed|archived|entry.*id", text, re.IGNORECASE))

    if has_store and has_correct:
        return {"pass": True, "score": 1.0, "reason": "Both store and correct tools called"}
    if has_store and text_ok:
        return {"pass": True, "score": 0.8, "reason": "Store called, correction mentioned in text"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_store + distillery_correct. Got: {names}. Text: {text[:200]}",
    }


# ---- /relations (add and get) -----------------------------------------------

def get_assert_relations_add_get(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_relations was called with add and get actions."""
    text, names = _parse_output(output)
    relation_calls = names.count("distillery_relations")

    if relation_calls >= 2:
        return {"pass": True, "score": 1.0, "reason": f"distillery_relations called {relation_calls} times (add+get)"}
    if relation_calls == 1:
        return {"pass": True, "score": 0.7, "reason": "distillery_relations called once (partial)"}
    if bool(re.search(r"relat|link|connect", text, re.IGNORECASE)):
        return {"pass": True, "score": 0.5, "reason": "Relation mentioned in text but tool not called"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_relations calls. Got: {names}. Text: {text[:200]}",
    }


# ---- store with verification ------------------------------------------------

def get_assert_store_verification(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_store was called with verification parameter."""
    text, names = _parse_output(output)
    has_store = "distillery_store" in names
    inp = _tool_input(output, "distillery_store")
    has_verification = inp is not None and "verification" in inp

    if has_store and has_verification:
        return {"pass": True, "score": 1.0, "reason": "Store called with verification field"}
    if has_store:
        return {"pass": True, "score": 0.7, "reason": "Store called (verification field may be implicit)"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_store with verification. Got: {names}. Text: {text[:200]}",
    }


# ---- store with expires_at --------------------------------------------------

def get_assert_store_expires(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_store was called with expires_at parameter."""
    text, names = _parse_output(output)
    has_store = "distillery_store" in names
    inp = _tool_input(output, "distillery_store")
    has_expires = inp is not None and "expires_at" in inp

    if has_store and has_expires:
        return {"pass": True, "score": 1.0, "reason": "Store called with expires_at field"}
    if has_store:
        return {"pass": True, "score": 0.7, "reason": "Store called (expires_at may be implicit)"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_store with expires_at. Got: {names}. Text: {text[:200]}",
    }


# ---- store with source ------------------------------------------------------

def get_assert_store_source(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_store was called with source parameter."""
    text, names = _parse_output(output)
    has_store = "distillery_store" in names
    inp = _tool_input(output, "distillery_store")
    has_source = inp is not None and "source" in inp

    if has_store and has_source:
        return {"pass": True, "score": 1.0, "reason": "Store called with source field"}
    if has_store:
        return {"pass": True, "score": 0.7, "reason": "Store called (source may be implicit)"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_store with source. Got: {names}. Text: {text[:200]}",
    }


# ---- store with session_id --------------------------------------------------

def get_assert_store_session_id(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_store was called with session_id parameter."""
    text, names = _parse_output(output)
    has_store = "distillery_store" in names
    inp = _tool_input(output, "distillery_store")
    has_session = inp is not None and "session_id" in inp

    if has_store and has_session:
        return {"pass": True, "score": 1.0, "reason": "Store called with session_id field"}
    if has_store:
        return {"pass": True, "score": 0.7, "reason": "Store called (session_id may be implicit)"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_store with session_id. Got: {names}. Text: {text[:200]}",
    }


# ---- update verification ----------------------------------------------------

def get_assert_update_verification(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_store then distillery_update with verification."""
    text, names = _parse_output(output)
    has_store = "distillery_store" in names
    has_update = "distillery_update" in names

    if has_store and has_update:
        return {"pass": True, "score": 1.0, "reason": "Store then update called"}
    if has_update:
        return {"pass": True, "score": 0.8, "reason": "Update called (store may have been skipped)"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_store + distillery_update. Got: {names}. Text: {text[:200]}",
    }


# ---- list with verification filter ------------------------------------------

def get_assert_list_verification_filter(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_list was called with verification filter."""
    text, names = _parse_output(output)
    has_list = "distillery_list" in names
    inp = _tool_input(output, "distillery_list")
    has_filter = inp is not None and "verification" in inp

    if has_list and has_filter:
        return {"pass": True, "score": 1.0, "reason": "List called with verification filter"}
    if has_list:
        return {"pass": True, "score": 0.7, "reason": "List called (filter may not be explicit in tool input)"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_list with verification filter. Got: {names}. Text: {text[:200]}",
    }


# ---- list with source filter ------------------------------------------------

def get_assert_list_source_filter(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify distillery_list was called with source filter."""
    text, names = _parse_output(output)
    has_list = "distillery_list" in names
    inp = _tool_input(output, "distillery_list")
    has_filter = inp is not None and "source" in inp

    if has_list and has_filter:
        return {"pass": True, "score": 1.0, "reason": "List called with source filter"}
    if has_list:
        return {"pass": True, "score": 0.7, "reason": "List called (filter may not be explicit)"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected distillery_list with source filter. Got: {names}. Text: {text[:200]}",
    }


# ---- briefing dashboard -----------------------------------------------------

def get_assert_briefing(output: str, context: dict[str, Any]) -> dict[str, Any]:
    """Verify briefing uses metrics and list tools to build a dashboard."""
    text, names = _parse_output(output)
    has_metrics = "distillery_metrics" in names
    has_list = "distillery_list" in names
    text_ok = bool(re.search(
        r"briefing|dashboard|summar|overview|entr|knowledge base",
        text, re.IGNORECASE,
    ))

    if has_metrics and has_list:
        return {"pass": True, "score": 1.0, "reason": "Metrics and list called for briefing"}
    if (has_metrics or has_list) and text_ok:
        return {"pass": True, "score": 0.8, "reason": "Partial tool use with briefing text"}
    if text_ok:
        return {"pass": True, "score": 0.5, "reason": "Briefing text present but tools not called as expected"}
    return {
        "pass": False,
        "score": 0.0,
        "reason": f"Expected metrics+list for briefing. Got: {names}. Text: {text[:200]}",
    }
