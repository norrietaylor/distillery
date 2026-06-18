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
# If output is non-empty it must start with the expected briefing prefix
if [[ -z "$OUTPUT8" ]]; then
  pass "SessionStart output empty (no MCP server — expected)"
elif [[ "$OUTPUT8" == *"[Distillery]"* ]]; then
  pass "SessionStart output contains valid briefing prefix"
else
  fail "SessionStart output is non-empty but malformed: ${OUTPUT8:0:100}"
fi

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

# ── T12: Briefing hook probes MCP endpoint (no /health dependency) ────────────
# Regression test for issue #347: the hook must not rely on a sibling /health
# route (which FastMCP deployments on Fly.io return 404 for) and must emit a
# visible diagnostic on stderr when the MCP endpoint is unreachable rather
# than silently no-op'ing.
echo ""
echo "T12: Briefing hook reports unreachable MCP endpoint"

BRIEFING_HOOK="${SCRIPT_DIR}/session-start-briefing.sh"

if [[ ! -f "$BRIEFING_HOOK" ]]; then
  fail "session-start-briefing.sh present" "not found at ${BRIEFING_HOOK}"
else
  # Point at a blackhole port on loopback so the probe fails fast.
  BAD_URL="http://127.0.0.1:1/mcp"
  STDERR_FILE="$(mktemp)"
  STDOUT_T12="$(hook_json SessionStart "${BASE_SESSION}-t12" "/tmp" \
    | DISTILLERY_MCP_URL="$BAD_URL" bash "$BRIEFING_HOOK" 2>"$STDERR_FILE")"
  EXIT_T12=$?
  STDERR_T12="$(cat "$STDERR_FILE")"
  rm -f "$STDERR_FILE"

  assert_exit_zero "unreachable endpoint still exits 0" "$EXIT_T12"
  assert_empty "unreachable endpoint produces no stdout briefing" "$STDOUT_T12"
  assert_contains "unreachable endpoint emits diagnostic on stderr" \
    "briefing disabled" "$STDERR_T12"
  assert_contains "diagnostic includes the attempted URL" \
    "$BAD_URL" "$STDERR_T12"
fi

# ── T13: QUIET=1 suppresses the unreachable diagnostic ───────────────────────
echo ""
echo "T13: DISTILLERY_BRIEFING_QUIET=1 silences stderr"

if [[ -f "$BRIEFING_HOOK" ]]; then
  STDERR_FILE="$(mktemp)"
  hook_json SessionStart "${BASE_SESSION}-t13" "/tmp" \
    | DISTILLERY_MCP_URL="http://127.0.0.1:1/mcp" \
      DISTILLERY_BRIEFING_QUIET=1 \
      bash "$BRIEFING_HOOK" >/dev/null 2>"$STDERR_FILE"
  STDERR_T13="$(cat "$STDERR_FILE")"
  rm -f "$STDERR_FILE"
  assert_empty "quiet mode suppresses diagnostic" "$STDERR_T13"
fi

# ── T14: Hook treats a 404-on-/health deployment as reachable ────────────────
# Start a tiny Python HTTP stub that returns 404 on every path EXCEPT the
# exact MCP endpoint — where it returns a JSON-RPC `tools/list` response.
# This reproduces the production staging behaviour described in #347 and
# verifies the probe succeeds via the MCP endpoint itself.
echo ""
echo "T14: Hook succeeds even when sibling /health route 404s"

if [[ -f "$BRIEFING_HOOK" ]] && command -v python3 >/dev/null 2>&1; then
  STUB_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"

  python3 - "$STUB_PORT" >/dev/null 2>/dev/null <<'PYEOF' &
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[1])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args, **_kwargs):  # silence
        return

    def do_GET(self):  # noqa: N802
        # Simulate FastMCP/Fly: every GET (including /health) returns 404.
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not Found")

    def do_POST(self):  # noqa: N802
        if self.path != "/mcp":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "result": {"tools": [{"name": "distillery_list"}]},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
PYEOF
  STUB_PID=$!

  # Wait for stub to become reachable (bounded).
  READY=0
  for _ in $(seq 1 50); do
    if curl -sf --max-time 1 -H 'Content-Type: application/json' \
        -H 'Accept: application/json, text/event-stream' \
        -d '{"jsonrpc":"2.0","id":0,"method":"tools/list","params":{}}' \
        "http://127.0.0.1:${STUB_PORT}/mcp" >/dev/null 2>&1; then
      READY=1
      break
    fi
    sleep 0.1
  done

  if [[ "$READY" -ne 1 ]]; then
    fail "stub MCP server started" "did not become ready within 5s"
  else
    STDERR_FILE="$(mktemp)"
    STDOUT_T14="$(hook_json SessionStart "${BASE_SESSION}-t14" "/tmp" \
      | DISTILLERY_MCP_URL="http://127.0.0.1:${STUB_PORT}/mcp" \
        bash "$BRIEFING_HOOK" 2>"$STDERR_FILE")"
    EXIT_T14=$?
    STDERR_T14="$(cat "$STDERR_FILE")"
    rm -f "$STDERR_FILE"

    assert_exit_zero "probe succeeds against 404-on-/health MCP" "$EXIT_T14"
    assert_contains "probe success yields briefing header on stdout" \
      "[Distillery] Project:" "$STDOUT_T14"
    # stderr must NOT contain an unreachable diagnostic in this path.
    if echo "$STDERR_T14" | grep -q "briefing disabled"; then
      fail "no unreachable diagnostic when probe succeeds" \
        "unexpected stderr: ${STDERR_T14}"
    else
      pass "no unreachable diagnostic when probe succeeds"
    fi
  fi

  # Teardown
  kill "$STUB_PID" 2>/dev/null || true
  wait "$STUB_PID" 2>/dev/null || true
fi

# ── T15: 401 from MCP produces an auth-specific diagnostic ────────────────────
# Matches the staging MCP behaviour for unauthenticated requests: the probe
# should not silently drop the briefing, it should tell the user to authenticate.
echo ""
echo "T15: Hook reports 401 with auth-specific diagnostic"

if [[ -f "$BRIEFING_HOOK" ]] && command -v python3 >/dev/null 2>&1; then
  STUB_PORT_2="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"

  python3 - "$STUB_PORT_2" >/dev/null 2>/dev/null <<'PYEOF' &
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(sys.argv[1])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args, **_kwargs):
        return

    def do_POST(self):  # noqa: N802
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        body = b'{"error":"invalid_token"}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("127.0.0.1", port), Handler).serve_forever()
PYEOF
  STUB_PID_2=$!

  READY=0
  for _ in $(seq 1 50); do
    if curl -s --max-time 1 -o /dev/null -w '%{http_code}' \
        -H 'Content-Type: application/json' \
        -H 'Accept: application/json, text/event-stream' \
        -d '{"jsonrpc":"2.0","id":0,"method":"tools/list","params":{}}' \
        "http://127.0.0.1:${STUB_PORT_2}/mcp" 2>/dev/null | grep -q '^401$'; then
      READY=1
      break
    fi
    sleep 0.1
  done

  if [[ "$READY" -ne 1 ]]; then
    fail "401 stub MCP server started" "did not become ready within 5s"
  else
    STDERR_FILE="$(mktemp)"
    STDOUT_T15="$(hook_json SessionStart "${BASE_SESSION}-t15" "/tmp" \
      | DISTILLERY_MCP_URL="http://127.0.0.1:${STUB_PORT_2}/mcp" \
        bash "$BRIEFING_HOOK" 2>"$STDERR_FILE")"
    EXIT_T15=$?
    STDERR_T15="$(cat "$STDERR_FILE")"
    rm -f "$STDERR_FILE"

    assert_exit_zero "401 endpoint still exits 0" "$EXIT_T15"
    assert_empty "401 endpoint produces no stdout briefing" "$STDOUT_T15"
    assert_contains "401 diagnostic mentions HTTP status" "401" "$STDERR_T15"
    assert_contains "401 diagnostic mentions authentication" \
      "authenticate" "$STDERR_T15"
  fi

  kill "$STUB_PID_2" 2>/dev/null || true
  wait "$STUB_PID_2" 2>/dev/null || true
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
