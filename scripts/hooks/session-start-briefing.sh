#!/usr/bin/env bash
# session-start-briefing.sh — Distillery SessionStart hook for Claude Code
#
# Injects condensed briefing context at session start by calling the Distillery
# MCP HTTP endpoint and formatting recent/stale entry summaries.
#
# Usage: register in ~/.claude/settings.json (see scripts/hooks/README.md)
# Input: hook JSON on stdin (hook_event_name, session_id, cwd)
# Output: condensed briefing text on stdout → injected as system reminder
#
# Configuration (environment variables):
#   DISTILLERY_MCP_URL       MCP HTTP endpoint (default: http://localhost:8000/mcp)
#   DISTILLERY_BRIEFING_LIMIT  Number of recent entries to show (default: 5)
#   DISTILLERY_BEARER_TOKEN  Optional bearer token if OAuth is enabled

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
MCP_URL="${DISTILLERY_MCP_URL:-http://localhost:8000/mcp}"
LIMIT="${DISTILLERY_BRIEFING_LIMIT:-5}"
BEARER_TOKEN="${DISTILLERY_BEARER_TOKEN:-}"

# ── Read hook input ───────────────────────────────────────────────────────────
HOOK_JSON="$(cat)"
CWD="$(echo "$HOOK_JSON" | grep -o '"cwd":"[^"]*"' | head -1 | sed 's/"cwd":"//;s/"//')"

# Fall back to current directory if cwd not found in hook JSON
if [[ -z "$CWD" ]]; then
  CWD="$(pwd)"
fi

# ── Derive project name ───────────────────────────────────────────────────────
# Try git root basename first, fall back to cwd basename
PROJECT=""
if command -v git >/dev/null 2>&1; then
  GIT_ROOT="$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "$GIT_ROOT" ]]; then
    PROJECT="$(basename "$GIT_ROOT")"
  fi
fi
if [[ -z "$PROJECT" ]]; then
  PROJECT="$(basename "$CWD")"
fi

# ── Health check (2-second timeout) ──────────────────────────────────────────
# If MCP server is unreachable, exit silently — no output, no error
AUTH_HEADER=""
if [[ -n "$BEARER_TOKEN" ]]; then
  AUTH_HEADER="Authorization: Bearer ${BEARER_TOKEN}"
fi

health_check() {
  if [[ -n "$AUTH_HEADER" ]]; then
    curl --silent --max-time 2 --fail \
      -H "$AUTH_HEADER" \
      "${MCP_URL%/mcp}/health" >/dev/null 2>&1
  else
    curl --silent --max-time 2 --fail \
      "${MCP_URL%/mcp}/health" >/dev/null 2>&1
  fi
}

if ! health_check; then
  # Silent failure — server unreachable
  exit 0
fi

# ── JSON-RPC helper ───────────────────────────────────────────────────────────
call_tool() {
  local tool_name="$1"
  local params="$2"

  local payload
  payload="$(printf '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"%s","arguments":%s}}' \
    "$tool_name" "$params")"

  if [[ -n "$AUTH_HEADER" ]]; then
    curl --silent --max-time 10 --fail \
      -H "Content-Type: application/json" \
      -H "$AUTH_HEADER" \
      -d "$payload" \
      "$MCP_URL" 2>/dev/null
  else
    curl --silent --max-time 10 --fail \
      -H "Content-Type: application/json" \
      -d "$payload" \
      "$MCP_URL" 2>/dev/null
  fi
}

# ── Fetch recent entries ──────────────────────────────────────────────────────
RECENT_RAW=""
RECENT_PARAMS="$(jq -n --arg project "$PROJECT" --argjson limit "$LIMIT" '{project:$project,limit:$limit}')"
RECENT_RAW="$(call_tool "distillery_list" "$RECENT_PARAMS" 2>/dev/null || true)"

# ── Fetch stale entries ───────────────────────────────────────────────────────
STALE_RAW=""
STALE_PARAMS="$(jq -n --argjson days 30 --argjson limit 3 '{days:$days,limit:$limit}')"
STALE_RAW="$(call_tool "distillery_stale" "$STALE_PARAMS" 2>/dev/null || true)"

# ── Parse and format output ───────────────────────────────────────────────────
# Extract content snippets using robust JSON parsing
# The MCP response wraps content in: {"result":{"content":[{"type":"text","text":"..."}]}}
extract_text() {
  local raw="$1"
  if command -v jq >/dev/null 2>&1; then
    echo "$raw" | jq -r '.result.content[0].text // empty' 2>/dev/null || true
  else
    # Fallback to Python if jq is not available
    echo "$raw" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("result",{}).get("content",[{}])[0].get("text",""))' 2>/dev/null || true
  fi
}

RECENT_TEXT="$(extract_text "$RECENT_RAW")"
STALE_TEXT="$(extract_text "$STALE_RAW")"

# ── Build condensed briefing (max 20 lines) ───────────────────────────────────
BRIEFING_LINES=()
BRIEFING_LINES+=("[Distillery] Project: ${PROJECT}")

# Summarize recent entries
if [[ -n "$RECENT_TEXT" && "$RECENT_TEXT" != "null" ]]; then
  # Count entries by looking for entry patterns in the text
  ENTRY_COUNT="$(echo "$RECENT_TEXT" | grep -c '"id"' 2>/dev/null || echo "0")"
  if [[ "$ENTRY_COUNT" -gt 0 ]]; then
    BRIEFING_LINES+=("Recent (${ENTRY_COUNT}): $(echo "$RECENT_TEXT" | grep -o '"content":"[^"]*"' | head -3 | sed 's/"content":"//;s/"$//' | cut -c1-60 | tr '\n' ', ' | sed 's/, $//')")
  fi
fi

# Summarize stale entries
if [[ -n "$STALE_TEXT" && "$STALE_TEXT" != "null" ]]; then
  STALE_COUNT="$(echo "$STALE_TEXT" | grep -c '"id"' 2>/dev/null || echo "0")"
  if [[ "$STALE_COUNT" -gt 0 ]]; then
    BRIEFING_LINES+=("Stale (${STALE_COUNT}): $(echo "$STALE_TEXT" | grep -o '"content":"[^"]*"' | head -2 | sed 's/"content":"//;s/"$//' | cut -c1-60 | tr '\n' ', ' | sed 's/, $//')")
  fi
fi

# Output the briefing (cap at 20 lines)
LINE_COUNT=0
for line in "${BRIEFING_LINES[@]}"; do
  if [[ "$LINE_COUNT" -ge 20 ]]; then
    break
  fi
  echo "$line"
  LINE_COUNT=$((LINE_COUNT + 1))
done