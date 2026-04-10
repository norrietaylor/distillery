# Task 18 Proof Summary

## Task: FIX-REVIEW: McpBridge.connect() missing timeout guard

## Fix Applied

Added `Promise.race` timeout guard to `McpBridge._doConnect()` in
`dashboard/src/lib/mcp-bridge.ts`.

The `_doConnect` method now races `this.app.connect(t)` against a
`setTimeout`-based rejection. If the connect call does not resolve within
`this.timeoutMs` milliseconds, a `McpBridgeError` is thrown with the message
`"connect() timed out after {ms}ms"`. The timeout handle is always cleared via
`finally` to prevent timer leaks.

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| 18-01-test.txt | test | PASS |

## Test Results

- 31/31 tests pass in `src/lib/mcp-bridge.test.ts`
- 1 new test added: `"rejects with McpBridgeError when connect() times out"`
  - Uses `vi.useFakeTimers()` to simulate timeout expiry without real wall time
  - Verifies `isConnected` remains `false` after timeout

## Sanitization

No credentials, tokens, API keys, or secrets found in proof files.
