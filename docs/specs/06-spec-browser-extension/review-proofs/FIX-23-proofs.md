# FIX-23 Proof Summary

**Task**: FIX-REVIEW: probeLocal fetch monkey-patch not restored on failure  
**Category**: A: Correctness  
**File**: browser-extension/src/background.js, function probeLocal() (lines 111-132)  
**Timestamp**: 2026-04-01T00:00:00Z

## Fix Description

Moved the `originalFetch` capture and `globalThis.fetch` monkey-patch to before the
`try` block, and moved both `globalThis.fetch = originalFetch` and `clearTimeout(timeoutId)`
into a `finally` block. This guarantees that the original fetch is always restored
regardless of whether `probe.initialize()` succeeds or throws.

## Root Cause

The original code declared `originalFetch` inside the `try` block, making it
inaccessible from the `catch` block. As a result, on any probe failure the patched
`globalThis.fetch` was never restored, leaving all subsequent service-worker fetch
calls using a stale AbortController signal.

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| FIX-23-01-before.txt | file (code inspection) | PASS |
| FIX-23-02-after.txt | file (code inspection) | PASS |
| FIX-23-03-git-diff.txt | cli (git diff) | PASS |

## Verification

The fix uses JavaScript's `finally` clause guarantee: the `finally` block runs
unconditionally after `try` or `catch` completes, ensuring `globalThis.fetch` is
always restored and the timeout is always cleared.
