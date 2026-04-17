#!/usr/bin/env bash
# session-start-briefing.sh — Thin wrapper for the Python briefing hook
#
# Delegates to session_start_briefing.py which handles dynamic MCP transport
# resolution (HTTP, stdio, or auto-detected from config files).
#
# Usage: register in ~/.claude/settings.json (see scripts/hooks/README.md)
# Input: hook JSON on stdin (hook_event_name, session_id, cwd)
# Output: condensed briefing text on stdout -> injected as system reminder
#
# Configuration (environment variables):
#   DISTILLERY_MCP_URL         MCP HTTP endpoint (skips auto-detection)
#   DISTILLERY_MCP_COMMAND     MCP stdio command (skips auto-detection)
#   DISTILLERY_BRIEFING_LIMIT  Number of recent entries to show (default: 5)
#   DISTILLERY_BEARER_TOKEN    Optional bearer token if OAuth is enabled

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="${SCRIPT_DIR}/session_start_briefing.py"

# Require Python 3.11+
PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  # No Python available — exit silently
  exit 0
fi

# Exec the Python script, passing stdin through
exec "$PYTHON" "$PYTHON_SCRIPT"
