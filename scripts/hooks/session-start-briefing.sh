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
#   DISTILLERY_MCP_URL         MCP HTTP endpoint (default: http://localhost:8000/mcp)
#   DISTILLERY_BRIEFING_LIMIT  Number of recent entries to show (default: 5)
#   DISTILLERY_BEARER_TOKEN    Optional bearer token if OAuth is enabled
#   DISTILLERY_BRIEFING_QUIET  If set to "1", suppress unreachable diagnostics on stderr

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
MCP_URL="${DISTILLERY_MCP_URL:-http://localhost:8000/mcp}"
LIMIT="${DISTILLERY_BRIEFING_LIMIT:-5}"
BEARER_TOKEN="${DISTILLERY_BEARER_TOKEN:-}"
QUIET="${DISTILLERY_BRIEFING_QUIET:-0}"

# ── Read hook input ───────────────────────────────────────────────────────────
HOOK_JSON="$(cat)"
CWD="$(echo "$HOOK_JSON" | grep -oE '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"cwd"[[:space:]]*:[[:space:]]*"//;s/"//')"

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

# ── Diagnostics helper ────────────────────────────────────────────────────────
# Emit a diagnostic to stderr unless QUIET=1. Users see stderr in Claude Code
# hook logs / terminal so they learn *why* the briefing did not appear.
diag() {
  if [[ "$QUIET" != "1" ]]; then
    echo "[Distillery] $*" >&2
  fi
}

# ── Auth header ───────────────────────────────────────────────────────────────
AUTH_HEADER=""
if [[ -n "$BEARER_TOKEN" ]]; then
  AUTH_HEADER="Authorization: Bearer ${BEARER_TOKEN}"
fi

# ── MCP reachability probe (replaces the unreliable /health sibling route) ───
# Fixes #347: some HTTP MCP deployments (e.g. FastMCP streamable-http on Fly.io)
# do not expose a sibling /health endpoint, so probing `<MCP_URL%/mcp>/health`
# returns 404 and the hook would silently no-op. Instead, probe the MCP endpoint
# directly with a minimal JSON-RPC `tools/list` request. This is the canonical
# MCP liveness check, works uniformly over every HTTP MCP deployment, and
# exercises the same code path the briefing tool calls will use.
#
# Writes the probe's HTTP status code to PROBE_STATUS and the response body to
# PROBE_BODY so the caller can distinguish network failure from auth failure.
PROBE_STATUS=0
PROBE_BODY=""
mcp_probe() {
  local probe_payload='{"jsonrpc":"2.0","id":0,"method":"tools/list","params":{}}'
  local raw
  local -a curl_args=(
    --silent
    --max-time 3
    -w '\n__HTTP_STATUS__:%{http_code}'
    -H "Content-Type: application/json"
    -H "Accept: application/json, text/event-stream"
    -d "$probe_payload"
  )
  if [[ -n "$AUTH_HEADER" ]]; then
    curl_args+=(-H "$AUTH_HEADER")
  fi
  # Do NOT use --fail: we want the body+status on non-2xx so we can classify
  # the failure mode (401 vs 404 vs network).
  if ! raw="$(curl "${curl_args[@]}" "$MCP_URL" 2>/dev/null)"; then
    PROBE_STATUS=0
    PROBE_BODY=""
    return 1
  fi
  # Split body from the status marker we asked curl to append.
  PROBE_STATUS="${raw##*__HTTP_STATUS__:}"
  PROBE_BODY="${raw%__HTTP_STATUS__:*}"
  # Strip the trailing newline we injected before __HTTP_STATUS__.
  PROBE_BODY="${PROBE_BODY%$'\n'}"
  if ! [[ "$PROBE_STATUS" =~ ^[0-9]+$ ]]; then
    PROBE_STATUS=0
    return 1
  fi
  if [[ "$PROBE_STATUS" -lt 200 || "$PROBE_STATUS" -ge 300 ]]; then
    return 1
  fi
  # Require the response to look like a JSON-RPC result payload (either raw
  # JSON or SSE-framed). FastMCP returns SSE by default; parse both.
  if echo "$PROBE_BODY" | grep -qE '"jsonrpc"[[:space:]]*:[[:space:]]*"2\.0"'; then
    return 0
  fi
  return 1
}

if ! mcp_probe; then
  case "$PROBE_STATUS" in
    401 | 403)
      diag "briefing disabled — MCP endpoint ${MCP_URL} rejected the request (HTTP ${PROBE_STATUS}); set DISTILLERY_BEARER_TOKEN or run \`/setup\` to authenticate"
      ;;
    0)
      diag "briefing disabled — MCP endpoint unreachable at ${MCP_URL} (connection failed or timed out; set DISTILLERY_BRIEFING_QUIET=1 to silence)"
      ;;
    *)
      diag "briefing disabled — MCP endpoint at ${MCP_URL} returned HTTP ${PROBE_STATUS} (set DISTILLERY_BRIEFING_QUIET=1 to silence)"
      ;;
  esac
  exit 0
fi

# ── JSON-RPC helper ───────────────────────────────────────────────────────────
call_tool() {
  local tool_name="$1"
  local params="$2"

  local payload
  payload="$(printf '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"%s","arguments":%s}}' \
    "$tool_name" "$params")"

  local -a curl_args=(
    --silent
    --max-time 10
    --fail
    -H "Content-Type: application/json"
    -H "Accept: application/json, text/event-stream"
    -d "$payload"
  )
  if [[ -n "$AUTH_HEADER" ]]; then
    curl_args+=(-H "$AUTH_HEADER")
  fi
  curl "${curl_args[@]}" "$MCP_URL" 2>/dev/null
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
# Extract content snippets using robust JSON parsing. FastMCP may respond with
# either raw JSON (Content-Type: application/json) or an SSE stream
# (text/event-stream) that wraps the payload in `data: {...}` lines, so we
# normalize SSE framing before extracting.
# The MCP response wraps content in: {"result":{"content":[{"type":"text","text":"..."}]}}
extract_text() {
  local raw="$1"
  # Strip SSE `data: ` prefixes (if any) to recover the JSON payload on a
  # single line. We keep only the last non-empty data line — FastMCP emits a
  # single data frame per JSON-RPC response.
  local json_line
  json_line="$(echo "$raw" | sed -n 's/^data:[[:space:]]*//p' | tail -n 1)"
  if [[ -z "$json_line" ]]; then
    json_line="$raw"
  fi
  if command -v jq >/dev/null 2>&1; then
    echo "$json_line" | jq -r '.result.content[0].text // empty' 2>/dev/null || true
  else
    # Fallback to Python if jq is not available
    echo "$json_line" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("result",{}).get("content",[{}])[0].get("text",""))' 2>/dev/null || true
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
