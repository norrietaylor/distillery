#!/usr/bin/env bash
# distillery-hooks.sh — Distillery hook dispatcher for Claude Code
#
# Single dispatcher script that routes Claude Code hook events to the
# appropriate handler based on hook_event_name. Register this script for
# the SessionStart hook in ~/.claude/settings.json (see scripts/hooks/README.md).
#
# Usage: register in ~/.claude/settings.json (see README.md)
# Input: hook JSON on stdin (hook_event_name, session_id, cwd, transcript_path)
# Output: hook-specific output on stdout (briefing, etc.)
#
# Configuration (environment variables):
#   DISTILLERY_BEARER_TOKEN    Optional bearer token if OAuth is enabled

# ── Silent error handler ──────────────────────────────────────────────────────
# Hooks must never block the user — all errors exit 0 silently.
trap 'exit 0' ERR

set -euo pipefail

# ── Read hook input ───────────────────────────────────────────────────────────
HOOK_JSON="$(cat)" || exit 0

# Parse fields from hook JSON (no jq dependency — portable grep/sed)
# Patterns allow optional whitespace around the colon for flexibility
HOOK_EVENT="$(echo "$HOOK_JSON" | grep -oE '"hook_event_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"hook_event_name"[[:space:]]*:[[:space:]]*"//;s/"//')" || true
CWD="$(echo "$HOOK_JSON" | grep -oE '"cwd"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"cwd"[[:space:]]*:[[:space:]]*"//;s/"//')" || true

# Fall back to current directory if cwd not found
if [[ -z "${CWD:-}" ]]; then
  CWD="$(pwd)"
fi

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
