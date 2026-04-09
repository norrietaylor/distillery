# T27 Proof Summary

**Task**: FIX-REVIEW #27 - missing entry_type and source in bookmark store call
**Status**: COMPLETED
**Date**: 2026-04-01

## Issue

The bookmark save flow in popup.js didn't include `entry_type: "bookmark"` or
`source: "browser-extension"` in the message sent to background for `distillery_store`.
The spec (06-spec-browser-extension.md lines 73-76) requires both fields.

## Fix Applied

### popup.js (browser-extension/src/popup.js lines 515-526)

Added `entry_type: 'bookmark'` and `source: 'browser-extension'` to the
`chrome.runtime.sendMessage` call that triggers the bookmark save flow.

### background.js (browser-extension/src/background.js lines 762-786)

Updated the `bookmark` case handler to:
1. Destructure `entry_type` and `source` from the incoming request
2. Pass them through to the `distillery_store` MCP args with fallback defaults
   (`entry_type || 'bookmark'` and `source || 'browser-extension'`)

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T27-01-code-review.txt | Code verification - popup.js | PASS |
| T27-02-code-review.txt | Code verification - background.js | PASS |

## Spec Compliance

From spec Unit 2 (Bookmark and Context Menu):
- `entry_type: "bookmark"` - now included in popup.js message and background.js args
- `source: "browser-extension"` - now included in popup.js message and background.js args
