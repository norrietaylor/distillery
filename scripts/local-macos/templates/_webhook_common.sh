#!/bin/zsh
# Shared helpers for the webhook worker scripts (poll.sh, classify.sh,
# rescore.sh, maintenance.sh). Source this file; do not execute directly.
#
# Usage:
#   source "$HOME/.distillery/_webhook_common.sh"
#   call_webhook <name> <url> <timeout_seconds> <ok_codes_regex>

SERVER_BASE="http://127.0.0.1:8000"

call_webhook() {
  local name="$1"
  local url="$2"
  local timeout="$3"
  local ok_re="$4"   # anchored regex, e.g. '^(200|202|409|429)$'

  local secret
  secret=$(security find-generic-password -a "$USER" -s DISTILLERY_WEBHOOK_SECRET -w 2>/dev/null || true)
  if [ -z "$secret" ]; then
    echo "[$(date -Iseconds)] DISTILLERY_WEBHOOK_SECRET not in Keychain; skipping $name" >&2
    return 0
  fi

  # Bail quietly if the server is unreachable — launchd will retry on schedule.
  if ! curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$SERVER_BASE/" 2>/dev/null \
       | grep -Eq '^[2345]'; then
    echo "[$(date -Iseconds)] server at $SERVER_BASE unreachable; skipping $name" >&2
    return 0
  fi

  local ts resp code body
  ts=$(date -Iseconds)
  resp=$(curl -sS --max-time "$timeout" \
    -H "Authorization: Bearer $secret" \
    -w '\n%{http_code}' \
    -X POST "$url" || true)
  code=$(printf '%s' "$resp" | tail -n1)
  body=$(printf '%s' "$resp" | sed '$d')

  if printf '%s' "$code" | grep -Eq "$ok_re"; then
    echo "[$ts] $name $code $body"
    return 0
  fi
  echo "[$ts] $name FAILED $code $body" >&2
  return 1
}
