# Code Review Report

**Reviewed**: 2026-04-02
**Branch**: feature/browser-extension
**Base**: main
**Commits**: 18 extension commits, 13 implementation files
**Overall**: CHANGES REQUESTED

## Summary

- **Blocking Issues**: 8 (A: 4 correctness, B: 1 security, C: 2 spec compliance, A+C: 1 mixed)
- **Advisory Notes**: 10
- **Files Reviewed**: 13 / 13 implementation files (proofs/vendor excluded)
- **FIX Tasks Created**: #23, #24, #25, #26, #27, #28, #29

## Blocking Issues

### [ISSUE-1] A: probeLocal fetch monkey-patch not restored on failure
- **File**: `browser-extension/src/background.js:111-135`
- **Severity**: Blocking
- **Description**: `probeLocal()` monkey-patches `globalThis.fetch` to inject an AbortSignal but doesn't restore the original in a `finally` block. After a failed probe, all subsequent fetch() calls are corrupted.
- **Fix**: Move restore into `finally` block or pass signal without monkey-patching.
- **Task**: FIX-REVIEW #23

### [ISSUE-2] A: context menu handler sends message to itself
- **File**: `browser-extension/src/background.js:389-401`
- **Severity**: Blocking
- **Description**: `handleContextMenuClick` uses `chrome.runtime.sendMessage` from the service worker to itself. This doesn't work -- use the in-scope `connectionState` variable directly.
- **Fix**: Replace sendMessage with direct variable access.
- **Task**: FIX-REVIEW #24

### [ISSUE-3] A+C: host_permissions too narrow and missing GitHub API
- **File**: `browser-extension/manifest.json:19-21`
- **Severity**: Blocking
- **Description**: `http://localhost:*/` only matches root path (MCP requests to `/mcp` fail). Missing `https://api.github.com/*` (auth.js user fetch blocked by CORS).
- **Fix**: Change to `http://localhost:*/*` and add `https://api.github.com/*`.
- **Task**: FIX-REVIEW #25

### [ISSUE-4] A: Watch tab invisible due to inline style override
- **File**: `browser-extension/src/popup.html:145`
- **Severity**: Blocking
- **Description**: Inline `style="display: none;"` overrides `.tab-panel.active { display: block; }`. Watch tab can never become visible.
- **Fix**: Remove inline style; CSS classes already handle visibility.
- **Task**: FIX-REVIEW #26

### [ISSUE-5] C: Missing entry_type and source in bookmark store call
- **File**: `browser-extension/src/popup.js:515-524`
- **Severity**: Blocking
- **Description**: Spec requires `entry_type: "bookmark"` and `source: "browser-extension"` in the `distillery_store` call. Neither field is present.
- **Fix**: Add both fields to the bookmark message and background handler.
- **Task**: FIX-REVIEW #27

### [ISSUE-6] B: CSS selector injection in content script meta queries
- **File**: `browser-extension/src/content.js:26-38`
- **Severity**: Blocking
- **Description**: `getMetaByName()` and `getOgMeta()` interpolate parameters directly into CSS attribute selectors without escaping.
- **Fix**: Use `CSS.escape()` on interpolated values.
- **Task**: FIX-REVIEW #28

### [ISSUE-7] A: GitHub repo regex matches non-repo paths
- **File**: `browser-extension/src/content.js:149-163`
- **Severity**: Blocking
- **Description**: Regex matches `github.com/settings/profile`, `github.com/features/actions`, etc. as repos. No exclusion for known non-repo paths.
- **Fix**: Add exclusion set for GitHub top-level paths.
- **Task**: FIX-REVIEW #29

## Advisory Notes

### [NOTE-1] A: _parseSSE returns last result, not first as documented
- **File**: `browser-extension/src/mcp-client.js:326-367`
- **Suggestion**: Fix docstring or change logic to match documented behavior.

### [NOTE-2] B: OAuth flow omits state parameter
- **File**: `browser-extension/src/auth.js:67-74`
- **Suggestion**: Add `state` parameter for CSRF defense-in-depth per RFC 6749.

### [NOTE-3] B: setAuthToken message handler lacks validation
- **File**: `browser-extension/src/background.js:734-735`
- **Suggestion**: Validate token format before persisting.

### [NOTE-4] C: 429 Retry-After not implemented
- **File**: `browser-extension/src/mcp-client.js:246-260`
- **Suggestion**: Implement retry/backoff logic in callers.

### [NOTE-5] C: author placed in metadata instead of top-level arg
- **File**: `browser-extension/src/background.js:404-421`
- **Suggestion**: Move author to top-level `distillery_store` argument.

### [NOTE-6] A: Offline queue load-save not serialized
- **File**: `browser-extension/src/offline-queue.js:52-77`
- **Suggestion**: Add a mutex/lock to prevent concurrent write races.

### [NOTE-7] D: Monolithic 270-line switch in onMessage
- **File**: `browser-extension/src/background.js:569-841`
- **Suggestion**: Extract handler functions for each message type.

### [NOTE-8] C: Three-tab layout vs spec's two-tab design
- **File**: `browser-extension/src/popup.html:24-28`
- **Suggestion**: Document if intentional or consolidate Status into header.

### [NOTE-9] B: Options URL validation accepts unsafe schemes
- **File**: `browser-extension/src/options.js:43-52`
- **Suggestion**: Restrict to http/https only.

### [NOTE-10] C: Atom feeds mapped to source_type 'atom' instead of 'rss'
- **File**: `browser-extension/src/content.js:134`
- **Suggestion**: Map Atom feeds to `source_type: 'rss'` per Distillery's supported types.

## Files Reviewed

| File | Status | Issues |
|------|--------|--------|
| `browser-extension/manifest.json` | New | 2 blocking |
| `browser-extension/src/background.js` | New | 2 blocking, 3 advisory |
| `browser-extension/src/mcp-client.js` | New | 2 advisory |
| `browser-extension/src/auth.js` | New | 1 advisory |
| `browser-extension/src/offline-queue.js` | New | 1 advisory |
| `browser-extension/src/content.js` | New | 2 blocking, 2 advisory |
| `browser-extension/src/popup.html` | New | 1 blocking, 1 advisory |
| `browser-extension/src/popup.js` | New | 1 blocking, 1 advisory |
| `browser-extension/src/popup.css` | New | Clean |
| `browser-extension/src/options.html` | New | 1 advisory |
| `browser-extension/src/options.js` | New | 1 advisory |
| `browser-extension/src/options.css` | New | Clean |
| `browser-extension/README.md` | New | Clean |

## Checklist

- [x] No hardcoded credentials or secrets
- [x] Error handling at system boundaries
- [ ] Input validation on user-facing endpoints (CSS selector injection)
- [ ] Changes match spec requirements (missing entry_type/source)
- [x] Follows repository patterns and conventions
- [x] No obvious performance regressions
