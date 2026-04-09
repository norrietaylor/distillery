#!/usr/bin/env bash
# distillery-hooks.sh — Distillery hook dispatcher for Claude Code
#
# Single dispatcher script that routes Claude Code hook events to the
# appropriate handler based on hook_event_name. Register this script for
# all three hook events in ~/.claude/settings.json (see scripts/hooks/README.md).
#
# Usage: register in ~/.claude/settings.json (see README.md)
# Input: hook JSON on stdin (hook_event_name, session_id, cwd, transcript_path)
# Output: hook-specific output on stdout (nudge text, briefing, etc.)
#
# Configuration (environment variables):
#   DISTILLERY_MCP_URL         MCP HTTP endpoint (default: http://localhost:8000/mcp)
#   DISTILLERY_NUDGE_INTERVAL  Prompts between memory nudges (default: 30)
#   DISTILLERY_BEARER_TOKEN    Optional bearer token if OAuth is enabled

# ── Silent error handler ──────────────────────────────────────────────────────
# Hooks must never block the user — all errors exit 0 silently.
trap 'exit 0' ERR

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
MCP_URL="${DISTILLERY_MCP_URL:-http://localhost:8000/mcp}"
NUDGE_INTERVAL="${DISTILLERY_NUDGE_INTERVAL:-30}"

# ── Read hook input ───────────────────────────────────────────────────────────
HOOK_JSON="$(cat)" || exit 0

# Parse fields from hook JSON (no jq dependency — portable grep/sed)
HOOK_EVENT="$(echo "$HOOK_JSON" | grep -o '"hook_event_name":"[^"]*"' | head -1 | sed 's/"hook_event_name":"//;s/"//')" || true
SESSION_ID="$(echo "$HOOK_JSON" | grep -o '"session_id":"[^"]*"' | head -1 | sed 's/"session_id":"//;s/"//')" || true
CWD="$(echo "$HOOK_JSON" | grep -o '"cwd":"[^"]*"' | head -1 | sed 's/"cwd":"//;s/"//')" || true

# Fall back to current directory if cwd not found
if [[ -z "${CWD:-}" ]]; then
  CWD="$(pwd)"
fi

# ── Handler: UserPromptSubmit ─────────────────────────────────────────────────
handle_user_prompt_submit() {
  # Require a session_id to scope the counter file
  if [[ -z "${SESSION_ID:-}" ]]; then
    return 0
  fi

  local counter_file="/tmp/distillery-prompt-count-${SESSION_ID}"
  local count=0

  # Atomically increment the counter using flock
  # The lock file is the counter file itself; flock releases on subshell exit
  (
    exec 200>"${counter_file}.lock"
    flock -x 200

    # Read current count (file may not exist yet on first prompt)
    if [[ -f "$counter_file" ]]; then
      count="$(cat "$counter_file" 2>/dev/null || echo 0)"
      # Ensure count is a non-negative integer
      if ! [[ "$count" =~ ^[0-9]+$ ]]; then
        count=0
      fi
    fi

    count=$((count + 1))
    echo "$count" > "$counter_file"

    # Output nudge at interval boundary
    if (( count % NUDGE_INTERVAL == 0 )); then
      echo "[Distillery] You've exchanged ${count} messages this session. Consider whether any decisions, insights, or corrections from this conversation should be stored with /distill."
    fi
  ) || return 0
}

# ── Handler: PreCompact ───────────────────────────────────────────────────────
handle_pre_compact() {
  # PreCompact auto-extraction is deferred to a future spec.
  # Placeholder: exits silently.
  return 0
}

# ── Handler: SessionStart ─────────────────────────────────────────────────────
handle_session_start() {
  # Delegate to the spec-14 briefing hook script.
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  local briefing_hook="${script_dir}/session-start-briefing.sh"

  if [[ -x "$briefing_hook" ]]; then
    # Re-feed the hook JSON to the briefing script
    echo "$HOOK_JSON" | bash "$briefing_hook" || return 0
  fi
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
case "${HOOK_EVENT:-}" in
  UserPromptSubmit)
    handle_user_prompt_submit
    ;;
  PreCompact)
    handle_pre_compact
    ;;
  SessionStart)
    handle_session_start
    ;;
  *)
    # Unknown event — silently ignore
    ;;
esac

exit 0
