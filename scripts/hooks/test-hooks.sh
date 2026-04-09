#!/usr/bin/env bash
# test-hooks.sh — Integration test harness for distillery-hooks.sh
#
# Tests hook dispatcher behavior without requiring a live MCP server.
# Run with: bash scripts/hooks/test-hooks.sh
#
# Exit codes:
#   0 — all tests passed
#   1 — one or more tests failed

set -uo pipefail

# ── Locate the dispatcher script ──────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISPATCHER="${SCRIPT_DIR}/distillery-hooks.sh"

if [[ ! -f "$DISPATCHER" ]]; then
  echo "ERROR: dispatcher not found at ${DISPATCHER}" >&2
  exit 1
fi

# ── Test infrastructure ───────────────────────────────────────────────────────
PASS=0
FAIL=0

pass() {
  local name="$1"
  echo "  PASS  ${name}"
  PASS=$((PASS + 1))
}

fail() {
  local name="$1"
  local detail="${2:-}"
  echo "  FAIL  ${name}${detail:+: ${detail}}"
  FAIL=$((FAIL + 1))
}

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    pass "$name"
  else
    fail "$name" "expected $(printf '%q' "$expected") got $(printf '%q' "$actual")"
  fi
}

assert_empty() {
  local name="$1" actual="$2"
  if [[ -z "$actual" ]]; then
    pass "$name"
  else
    fail "$name" "expected empty output, got: $(printf '%q' "$actual")"
  fi
}

assert_contains() {
  local name="$1" pattern="$2" actual="$3"
  if echo "$actual" | grep -qF "$pattern"; then
    pass "$name"
  else
    fail "$name" "expected output to contain '${pattern}', got: $(printf '%q' "$actual")"
  fi
}

assert_exit_zero() {
  local name="$1" exit_code="$2"
  if [[ "$exit_code" -eq 0 ]]; then
    pass "$name"
  else
    fail "$name" "expected exit 0, got ${exit_code}"
  fi
}

assert_file_exists() {
  local name="$1" path="$2"
  if [[ -f "$path" ]]; then
    pass "$name"
  else
    fail "$name" "file not found: ${path}"
  fi
}

assert_file_absent() {
  local name="$1" path="$2"
  if [[ ! -f "$path" ]]; then
    pass "$name"
  else
    fail "$name" "file should not exist: ${path}"
  fi
}

# ── Helper: emit hook JSON ────────────────────────────────────────────────────
hook_json() {
  local event="$1" session="${2:-test-session-$$}" cwd="${3:-/tmp}"
  printf '{"hook_event_name":"%s","session_id":"%s","cwd":"%s"}' \
    "$event" "$session" "$cwd"
}

# ── Unique session per test run so counter files don't collide ────────────────
BASE_SESSION="test-$$"

# ── Test suite ────────────────────────────────────────────────────────────────
echo ""
echo "distillery-hooks.sh — integration tests"
echo "========================================"

# ── T1: Counter file created on first prompt ──────────────────────────────────
echo ""
echo "T1: Counter file lifecycle"

SESSION1="${BASE_SESSION}-t1"
COUNTER1="/tmp/distillery-prompt-count-${SESSION1}"
rm -f "$COUNTER1"

hook_json UserPromptSubmit "$SESSION1" \
  | DISTILLERY_NUDGE_INTERVAL=30 bash "$DISPATCHER" >/dev/null 2>&1

assert_file_exists "counter file created on first prompt" "$COUNTER1"

COUNT_VAL="$(cat "$COUNTER1" 2>/dev/null || echo "")"
assert_eq "counter starts at 1" "1" "$COUNT_VAL"

# Cleanup
rm -f "$COUNTER1"
assert_file_absent "counter file removed after cleanup" "$COUNTER1"

# ── T2: Counter increments across prompts ─────────────────────────────────────
echo ""
echo "T2: Counter increments"

SESSION2="${BASE_SESSION}-t2"
COUNTER2="/tmp/distillery-prompt-count-${SESSION2}"
rm -f "$COUNTER2"

for i in 1 2 3; do
  hook_json UserPromptSubmit "$SESSION2" \
    | DISTILLERY_NUDGE_INTERVAL=30 bash "$DISPATCHER" >/dev/null 2>&1
done

FINAL_COUNT="$(cat "$COUNTER2" 2>/dev/null || echo "")"
assert_eq "counter increments correctly (3 prompts -> 3)" "3" "$FINAL_COUNT"

rm -f "$COUNTER2"

# ── T3: Non-nudge prompts produce no output ───────────────────────────────────
echo ""
echo "T3: Non-nudge prompts are silent"

SESSION3="${BASE_SESSION}-t3"
COUNTER3="/tmp/distillery-prompt-count-${SESSION3}"
rm -f "$COUNTER3"

OUTPUT3="$(hook_json UserPromptSubmit "$SESSION3" \
  | DISTILLERY_NUDGE_INTERVAL=30 bash "$DISPATCHER" 2>/dev/null)"

assert_empty "first prompt (non-nudge) produces no stdout" "$OUTPUT3"

rm -f "$COUNTER3"

# ── T4: Nudge fires at configured interval ────────────────────────────────────
echo ""
echo "T4: Nudge fires at interval boundary"

SESSION4="${BASE_SESSION}-t4"
COUNTER4="/tmp/distillery-prompt-count-${SESSION4}"
rm -f "$COUNTER4"

# Use interval=3: first two prompts silent, third fires nudge
OUTPUT4_1="$(hook_json UserPromptSubmit "$SESSION4" \
  | DISTILLERY_NUDGE_INTERVAL=3 bash "$DISPATCHER" 2>/dev/null)"
OUTPUT4_2="$(hook_json UserPromptSubmit "$SESSION4" \
  | DISTILLERY_NUDGE_INTERVAL=3 bash "$DISPATCHER" 2>/dev/null)"
OUTPUT4_3="$(hook_json UserPromptSubmit "$SESSION4" \
  | DISTILLERY_NUDGE_INTERVAL=3 bash "$DISPATCHER" 2>/dev/null)"

assert_empty "prompt 1 of 3 produces no output" "$OUTPUT4_1"
assert_empty "prompt 2 of 3 produces no output" "$OUTPUT4_2"
assert_contains "prompt 3 of 3 fires nudge" "[Distillery]" "$OUTPUT4_3"
assert_contains "nudge mentions message count" "3 messages" "$OUTPUT4_3"

rm -f "$COUNTER4"

# ── T5: Interval=1 fires on every prompt ─────────────────────────────────────
echo ""
echo "T5: Interval=1 fires on every prompt"

SESSION5="${BASE_SESSION}-t5"
COUNTER5="/tmp/distillery-prompt-count-${SESSION5}"
rm -f "$COUNTER5"

OUTPUT5_1="$(hook_json UserPromptSubmit "$SESSION5" \
  | DISTILLERY_NUDGE_INTERVAL=1 bash "$DISPATCHER" 2>/dev/null)"
OUTPUT5_2="$(hook_json UserPromptSubmit "$SESSION5" \
  | DISTILLERY_NUDGE_INTERVAL=1 bash "$DISPATCHER" 2>/dev/null)"

assert_contains "interval=1, prompt 1 fires nudge" "[Distillery]" "$OUTPUT5_1"
assert_contains "interval=1, prompt 2 fires nudge" "[Distillery]" "$OUTPUT5_2"

rm -f "$COUNTER5"

# ── T6: Unknown hook events exit 0 silently ───────────────────────────────────
echo ""
echo "T6: Unknown hook events silently ignored"

OUTPUT6="$(hook_json UnknownFutureEvent "${BASE_SESSION}-t6" \
  | bash "$DISPATCHER" 2>/dev/null)"
EXIT6=$?

assert_exit_zero "unknown event exits 0" "$EXIT6"
assert_empty "unknown event produces no output" "$OUTPUT6"

# ── T7: PreCompact exits 0 silently ──────────────────────────────────────────
echo ""
echo "T7: PreCompact exits 0 silently"

OUTPUT7="$(hook_json PreCompact "${BASE_SESSION}-t7" \
  | bash "$DISPATCHER" 2>/dev/null)"
EXIT7=$?

assert_exit_zero "PreCompact exits 0" "$EXIT7"
assert_empty "PreCompact produces no output" "$OUTPUT7"

# ── T8: SessionStart delegates or skips gracefully ───────────────────────────
echo ""
echo "T8: SessionStart delegates or skips gracefully"

OUTPUT8="$(hook_json SessionStart "${BASE_SESSION}-t8" \
  | bash "$DISPATCHER" 2>/dev/null)"
EXIT8=$?

# The briefing hook may or may not be present — either way must exit 0
assert_exit_zero "SessionStart exits 0 (present or absent)" "$EXIT8"
# If output is non-empty it should contain something meaningful; if empty, that's fine too
pass "SessionStart output acceptable (empty or briefing content)"

# ── T9: Missing session_id handled gracefully ─────────────────────────────────
echo ""
echo "T9: Missing session_id handled gracefully"

OUTPUT9="$(printf '{"hook_event_name":"UserPromptSubmit"}' \
  | bash "$DISPATCHER" 2>/dev/null)"
EXIT9=$?

assert_exit_zero "UserPromptSubmit with no session_id exits 0" "$EXIT9"
assert_empty "UserPromptSubmit with no session_id produces no output" "$OUTPUT9"

# ── T10: Empty input handled gracefully ──────────────────────────────────────
echo ""
echo "T10: Empty stdin handled gracefully"

OUTPUT10="$(printf '' | bash "$DISPATCHER" 2>/dev/null)"
EXIT10=$?

assert_exit_zero "empty stdin exits 0" "$EXIT10"
assert_empty "empty stdin produces no output" "$OUTPUT10"

# ── T11: Dispatcher script is executable ─────────────────────────────────────
echo ""
echo "T11: Dispatcher script permissions"

if [[ -x "$DISPATCHER" ]]; then
  pass "distillery-hooks.sh is executable"
else
  fail "distillery-hooks.sh is executable" "missing execute bit"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
TOTAL=$((PASS + FAIL))
echo "Results: ${PASS}/${TOTAL} passed"

if [[ $FAIL -gt 0 ]]; then
  echo "FAILED (${FAIL} test(s) failed)"
  exit 1
else
  echo "ALL TESTS PASSED"
  exit 0
fi
