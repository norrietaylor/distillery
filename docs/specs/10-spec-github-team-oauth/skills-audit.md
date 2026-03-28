# Skills Audit — HTTP Transport Compatibility

**Date:** 2026-03-28
**Scope:** Audit all Distillery skills for stdio-specific assumptions that may break when running over HTTP transport
**Transport Context:** Skills must work identically whether the MCP server runs over stdio (local) or HTTP (remote)

## Summary

All 6 core skills (distill, recall, bookmark, pour, minutes, classify) are **COMPATIBLE with HTTP transport**. No code changes are required.

Key findings:
- ✅ All skills use the MCP tool interface (`distillery_*` calls) which is transport-agnostic
- ✅ All skills respect HTTP mode constraints (no direct file I/O outside MCP)
- ✅ Authentication (GitHub OAuth) is transparent to skill implementations
- ✅ Author/project identification patterns work with both local and remote servers
- ✅ No documentation issues found that require follow-up
- 📋 All skills use common patterns from `CONVENTIONS.md` consistently

---

## Detailed Audit

### Skill: distill

**File:** `.claude/skills/distill/SKILL.md`

**Analysis:**

| Aspect | Status | Notes |
|--------|--------|-------|
| MCP tool usage | ✅ Pass | Uses `distillery_status`, `distillery_check_dedup`, `distillery_store` — all transport-agnostic |
| File I/O | ✅ Pass | No direct file access; all data flows through MCP tools |
| Auth handling | ✅ Pass | No auth logic in skill; server handles GitHub OAuth transparently |
| Author determination | ✅ Pass | Uses `git config user.name` and `DISTILLERY_AUTHOR` env var (both local, works remotely) |
| Project identification | ✅ Pass | Uses `git rev-parse --show-toplevel` (local only) with fallback to user prompt; works for HTTP |
| Transport assumptions | ✅ Pass | No stdlib assumptions; uses standard CLI conventions |
| Documentation references | ✅ Pass | References `docs/mcp-setup.md` (correct file) and `docs/team-setup.md` (new) |

**Verdict:** ✅ **COMPATIBLE** — No changes needed.

---

### Skill: recall

**File:** `.claude/skills/recall/SKILL.md`

**Analysis:**

| Aspect | Status | Notes |
|--------|--------|-------|
| MCP tool usage | ✅ Pass | Uses `distillery_status` and `distillery_search` — both transport-agnostic |
| File I/O | ✅ Pass | No direct file access |
| Auth handling | ✅ Pass | No auth logic; server handles GitHub OAuth transparently |
| Transport assumptions | ✅ Pass | Pure query interface, no process-level state |
| Documentation references | ✅ Pass | References `docs/mcp-setup.md` and `docs/team-setup.md` |

**Verdict:** ✅ **COMPATIBLE** — No changes needed.

---

### Skill: bookmark

**File:** `.claude/skills/bookmark/SKILL.md`

**Analysis:**

| Aspect | Status | Notes |
|--------|--------|-------|
| MCP tool usage | ✅ Pass | Uses `distillery_status`, `distillery_check_dedup`, `distillery_store` — all transport-agnostic |
| File I/O | ✅ Pass | No direct file access; URL fetching handled by Claude Code (not MCP) |
| Auth handling | ✅ Pass | No auth logic |
| Transport assumptions | ✅ Pass | Uses WebFetch (Claude Code native tool) for URL retrieval; works over HTTP |
| Author determination | ✅ Pass | Uses `git config user.name` + `DISTILLERY_AUTHOR` + user prompt (works with HTTP) |
| Documentation references | ✅ Pass | References `docs/mcp-setup.md` correctly |

**Verdict:** ✅ **COMPATIBLE** — No changes needed.

---

### Skill: pour

**File:** `.claude/skills/pour/SKILL.md`

**Analysis:**

| Aspect | Status | Notes |
|--------|--------|-------|
| MCP tool usage | ✅ Pass | Uses `distillery_status` and `distillery_search` (multi-pass) — transport-agnostic |
| File I/O | ✅ Pass | No direct file access |
| Auth handling | ✅ Pass | No auth logic |
| Transport assumptions | ✅ Pass | Query-only pattern; stateless |
| Project filtering | ✅ Pass | Uses `--project` flag or user prompt; works with HTTP |
| Documentation references | ✅ Pass | References `docs/mcp-setup.md` correctly |

**Verdict:** ✅ **COMPATIBLE** — No changes needed.

---

### Skill: minutes

**File:** `.claude/skills/minutes/SKILL.md`

**Analysis:**

| Aspect | Status | Notes |
|--------|--------|-------|
| MCP tool usage | ✅ Pass | Uses `distillery_status`, `distillery_store`, `distillery_get`, `distillery_update`, `distillery_search` — all transport-agnostic |
| File I/O | ✅ Pass | No direct file access |
| Auth handling | ✅ Pass | No auth logic |
| Author determination | ✅ Pass | Uses `git config user.name` + `DISTILLERY_AUTHOR` + user prompt |
| Meeting ID generation | ✅ Pass | Generates `meeting-<YYYY-MM-DD>-<random-id>` locally; UUID generation is local, not server-dependent |
| Documentation references | ✅ Pass | References `docs/mcp-setup.md` correctly |

**Verdict:** ✅ **COMPATIBLE** — No changes needed.

---

### Skill: classify

**File:** `.claude/skills/classify/SKILL.md`

**Analysis:**

| Aspect | Status | Notes |
|--------|--------|-------|
| MCP tool usage | ✅ Pass | Uses `distillery_status`, `distillery_get`, `distillery_classify` — all transport-agnostic |
| File I/O | ✅ Pass | No direct file access |
| Auth handling | ✅ Pass | No auth logic |
| Classification logic | ✅ Pass | Classification happens on server (MCP handler); skill just invokes it |
| Transport assumptions | ✅ Pass | No process-level state dependencies |
| Documentation references | ✅ Pass | References `docs/mcp-setup.md` correctly |

**Verdict:** ✅ **COMPATIBLE** — No changes needed.

---

## Findings

### No Issues Found — All Skills Transport-Agnostic

All 6 skills follow the established patterns in `CONVENTIONS.md`:

1. **MCP Tool Interface** — All skills use only the MCP tool interface (`distillery_*` calls), not direct server file access or process interaction. This makes them transport-agnostic by design.

2. **Author/Project Identification** — Common pattern used across all skills:
   - Author: `git config user.name` → `DISTILLERY_AUTHOR` env var → user prompt ✅
   - Project: `--project <name>` flag → `git rev-parse --show-toplevel` → user prompt ✅
   - Both patterns work equally well with HTTP transport (git/env vars are local to the client)

3. **Authentication Transparency** — Skills do not implement auth logic. When the server runs with GitHub OAuth, the token is managed by Claude Code's auth system. The skill calls are unchanged.

4. **No Direct I/O** — No skill directly accesses:
   - Server files or logs
   - Process control (start/stop/restart)
   - Network sockets (all network I/O is through MCP)

5. **Documentation** — All skills reference `docs/mcp-setup.md` for setup instructions. The new `docs/team-setup.md` covers remote (HTTP) setup scenarios.

---

## Recommendations

### For Team Members

- Use `docs/team-setup.md` for connecting to a remote Distillery instance
- Use `docs/mcp-setup.md` for local stdio setup (existing docs)
- All skills work identically regardless of transport mode

### For Operators

- Deploy with HTTP transport using `distillery-mcp --transport http --port 8000`
- Enable GitHub OAuth in `distillery.yaml` for team access control
- No skill-level configuration changes are needed

### For Contributors

- If new skills are added, follow the patterns in `CONVENTIONS.md`:
  - Use MCP tool interface, not direct file I/O
  - Support author/project identification as described
  - Document HTTP mode setup in skill prerequisites

---

## GitHub Issues (None Filed)

No issues were discovered that require follow-up. All skills are transport-agnostic by design.

---

## Verification Checklist

- [x] All 6 core skills reviewed for stdio-specific assumptions
- [x] MCP tool usage audited for transport compatibility
- [x] File I/O and process control patterns verified
- [x] Auth handling assessed for HTTP mode transparency
- [x] Author/project identification patterns confirmed working
- [x] Documentation references verified
- [x] No blocking issues found
- [x] All findings documented

---

## Conclusion

The Distillery skills suite is **ready for HTTP transport**. All skills are transport-agnostic and require no code changes. This audit confirms that the architectural design of using the MCP tool interface (rather than direct client-server plumbing) provides clean separation between skills and transport layers.
