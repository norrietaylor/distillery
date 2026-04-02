# Code Review Report

**Reviewed**: 2026-04-02
**Branch**: feature/skill-ux
**Base**: main
**Commits**: 13 commits, 55 files changed
**Overall**: CHANGES REQUESTED

## Summary

- **Blocking Issues**: 1 (A: 1 correctness, B: 0 security, C: 0 spec compliance)
- **Advisory Notes**: 2
- **Files Reviewed**: 15 / 15 implementation files (proof artifacts excluded)
- **FIX Tasks Created**: #21

## Blocking Issues

### [ISSUE-1] Category A: /radar missing distillery_update in allowed-tools
- **File**: `.claude-plugin/skills/radar/SKILL.md:4-11`
- **Severity**: Blocking
- **Description**: The dedup merge flow (line 91) calls `distillery_update` to merge content with an existing entry, but `distillery_update` is not in the `allowed-tools` frontmatter. The merge outcome will fail at runtime.
- **Fix**: Add `- "mcp__*__distillery_update"` to the allowed-tools block.
- **Task**: FIX-REVIEW #21

## Advisory Notes

### [NOTE-1] Category D: Server docstring says "23 tools" but there are 24
- **File**: `src/distillery/mcp/server.py:1`
- **Description**: The module docstring says "23 tools over stdio or HTTP" but after adding `distillery_configure`, there are 24.
- **Suggestion**: Update to "24 tools".

### [NOTE-2] Category D: feeds.max_items_per_poll not in distillery_configure allowlist
- **File**: `src/distillery/mcp/tools/configure.py:36-71`
- **Description**: The spec (Unit 3) mentions `feeds.max_items_per_poll` as a configurable key, but it's not in the `_ALLOWED_KEYS` dict. The /tune SKILL.md handles this gracefully by noting the limitation to users.
- **Suggestion**: Add `("feeds", "max_items_per_poll")` to the allowlist if the config model supports it, or accept the current workaround.

## Files Reviewed

| File | Status | Issues |
|------|--------|--------|
| `src/distillery/mcp/tools/configure.py` | New | Clean — solid validation, atomic write, revert on failure |
| `src/distillery/mcp/server.py` | Modified | 1 advisory (docstring count) |
| `src/distillery/mcp/tools/classify.py` | Modified | Clean |
| `src/distillery/mcp/tools/__init__.py` | Modified | Clean |
| `.claude-plugin/skills/CONVENTIONS.md` | Modified | Clean — all 4 new sections present |
| `.claude-plugin/skills/radar/SKILL.md` | Modified | 1 blocking (missing allowed-tool) |
| `.claude-plugin/skills/minutes/SKILL.md` | Modified | Clean — dedup + meeting_id check correct |
| `.claude-plugin/skills/tune/SKILL.md` | Modified | Clean — uses distillery_configure correctly |
| `.claude-plugin/skills/distill/SKILL.md` | Modified | Clean — confirmation template applied |
| `.claude-plugin/skills/bookmark/SKILL.md` | Modified | Clean — confirmation template applied |
| `.claude-plugin/skills/classify/SKILL.md` | Modified | Clean — 148 lines, --project added |
| `.claude-plugin/skills/classify/references/modes.md` | New | Clean |
| `.claude-plugin/skills/setup/SKILL.md` | Modified | Clean — 133 lines (target ≤150) |
| `.claude-plugin/skills/setup/references/cron-payloads.md` | New | Clean |
| `.claude-plugin/skills/setup/references/transport-detection.md` | New | Clean |

## Checklist

- [x] No hardcoded credentials or secrets
- [x] Error handling at system boundaries (configure.py reverts on disk-write failure)
- [x] Input validation on user-facing endpoints (allowlist, range, cross-field constraints)
- [x] Changes match spec requirements (1 minor gap: max_items_per_poll)
- [x] Follows repository patterns and conventions
- [x] No obvious performance regressions
