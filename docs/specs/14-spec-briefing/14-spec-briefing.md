# 14-spec-briefing

## Introduction/Overview

Add a `/briefing` skill that provides a single-command knowledge dashboard for starting work sessions. In solo mode it surfaces recent entries, corrections, expiring items, stale knowledge, and unresolved entries for the current project. In team mode it adds cross-author activity, semantically relevant entries from teammates, and the review queue. A companion SessionStart hook script automates context injection at the beginning of every Claude Code session.

Refs: [#155](https://github.com/norrietaylor/distillery/issues/155), [#191](https://github.com/norrietaylor/distillery/issues/191)

## Goals

1. Provide a single `/briefing` command that replaces multiple manual queries at session start
2. Auto-detect solo vs team mode based on author count in the knowledge base
3. Surface time-sensitive information (expiring entries, stale knowledge, unresolved items) without requiring the user to remember to check
4. Enable automatic context injection via a SessionStart hook script that calls /briefing output
5. Work entirely with existing MCP tools — no new tools or migrations required

## User Stories

- As a solo developer starting a session, I want a one-command overview of my project's knowledge state so I can pick up where I left off
- As a team member, I want to see what my teammates have captured so I don't duplicate work or miss relevant context
- As a Claude Code user with hooks, I want briefing context injected automatically at session start so the LLM has awareness of prior decisions without me asking
- As a developer, I want to see which entries are expiring soon so I can act before credentials rotate or deadlines pass

## Demoable Units of Work

### Unit 1: Solo briefing skill

**Purpose:** Create the `/briefing` SKILL.md that orchestrates existing MCP tools into a formatted knowledge dashboard for solo use.

**Functional Requirements:**

- The skill shall be invoked as `/briefing` (auto-detect project from cwd) or `/briefing --project X`
- The skill shall follow shared conventions: MCP health check, author/project resolution per `skills/CONVENTIONS.md`
- The skill shall produce 5 sections using existing MCP tools:
  1. **Recent entries** — `distillery_list(project=$project, limit=10)` sorted by recency
  2. **Corrections** — `distillery_list(project=$project, limit=20)` then `distillery_relations(action="get", entry_id=..., relation_type="corrects", direction="outgoing")` for each to find correction chains
  3. **Expiring soon** — `distillery_list(project=$project, limit=50)` then post-filter entries where `expires_at` is within the next 7 days
  4. **Stale knowledge** — `distillery_stale(days=30, limit=5, entry_type=null)` optionally filtered by project
  5. **Unresolved** — `distillery_list(project=$project, verification="testing", limit=5)`
- The skill shall omit empty sections (e.g. if no entries are expiring, skip that section)
- The skill shall format output as markdown with entry previews (first 100 chars), type badges, and relative timestamps
- The skill shall display a header: `# Briefing: <project> (solo)` with generation timestamp

**Proof Artifacts:**

- File: `skills/briefing/SKILL.md` exists with YAML frontmatter, follows CONVENTIONS.md structure
- File: `skills/briefing/SKILL.md` references only existing MCP tools (list, stale, relations, search)
- Test: manual invocation of `/briefing --project distillery` produces formatted output with all 5 sections

### Unit 2: Team mode

**Purpose:** Extend the briefing skill with team-oriented sections activated by `--team` flag or auto-detection.

**Functional Requirements:**

- The skill shall accept an optional `--team` flag to force team mode
- The skill shall auto-detect team mode when `distillery_aggregate(group_by="author")` returns more than one author
- In team mode, the skill shall add 3 additional sections after the solo sections:
  6. **Team activity** — `distillery_list(limit=20)` grouped by author with entry type counts for the past 7 days
  7. **Related from team** — `distillery_search(query=$project_context)` without author filter to surface semantically relevant entries from other authors, showing similarity percentage
  8. **Pending review** — `distillery_list(status="pending_review", limit=5)` showing entries awaiting classification
- The skill shall change the header to `# Briefing: <project> (team)` when in team mode
- Solo sections shall remain unchanged in team mode (team sections are additive)
- The skill shall omit empty team sections

**Proof Artifacts:**

- File: `skills/briefing/SKILL.md` contains team mode logic with `--team` flag documentation
- Test: `/briefing --team --project distillery` produces output with all 8 sections when multiple authors exist

### Unit 3: SessionStart hook script

**Purpose:** Provide a bash hook script that injects briefing context automatically when a Claude Code session starts.

**Functional Requirements:**

- The script shall be placed at `scripts/hooks/session-start-briefing.sh`
- The script shall read the hook JSON from stdin to extract `session_id` and `cwd`
- The script shall derive the project name from the cwd (basename of git root, or basename of cwd)
- The script shall call `distillery_list` and `distillery_stale` via the MCP HTTP endpoint using `curl` and JSON-RPC
- The script shall format a concise briefing (shorter than the full `/briefing` output — max 20 lines) suitable for system prompt injection
- The script shall output text to stdout that Claude Code injects as a system reminder
- The script shall perform a 2-second health check timeout — if the MCP server is unreachable, output nothing (silent failure)
- The script shall be documented with a setup section explaining how to register it in Claude Code's `settings.json` hooks
- The script shall include a `DISTILLERY_MCP_URL` environment variable (default: `http://localhost:8000/mcp`) for the MCP endpoint
- The script shall include a `DISTILLERY_BRIEFING_LIMIT` environment variable (default: `5`) for the number of recent entries

**Proof Artifacts:**

- File: `scripts/hooks/session-start-briefing.sh` exists, is executable, and contains bash with proper error handling
- File: `scripts/hooks/README.md` documents setup, configuration, and expected behavior
- CLI: `echo '{"hook_event_name":"SessionStart","session_id":"test","cwd":"/tmp"}' | bash scripts/hooks/session-start-briefing.sh` produces formatted output (or exits silently if no MCP server)

## Non-Goals (Out of Scope)

- **New MCP tools**: the skill orchestrates existing tools only
- **`stale_days` parameter on `distillery_list`**: tracked in #196, not a dependency for this spec
- **`expires_at` filtering on `distillery_list`**: post-filtering in the skill is sufficient
- **UserPromptSubmit hook** (periodic memory nudge): client-side only, documented as a pattern but not implemented here
- **PreCompact hook** (auto-extraction): separate concern per #191
- **NetworkX graph analysis**: the original #155 referenced #138 but the solo/team briefing doesn't need graph infrastructure
- **`/whois` skill**: team mode uses aggregate + list instead

## Design Considerations

### Output Format

```
# Briefing: distillery (solo)
Generated: 2026-04-09 10:30 UTC

## Recent (5)
- [session] Implemented corrections chain with entry_relations... (2h ago)
- [bookmark] FastMCP 3.1 migration guide... (yesterday)
...

## Corrections (1)
- "Earth is a geoid" corrects "Earth is an oblate spheroid" (3h ago)

## Expiring Soon (1)
- [reference] Jina API key rotation -- expires 2026-04-15

## Stale (2)
- [session] Sprint planning notes... -- last accessed 45 days ago
...

## Unresolved (1)
- [idea] Hybrid search RRF constant tuning -- verification: testing
```

Team mode appends:

```
## Team Activity (7 days)
- Alice: 5 entries (3 sessions, 2 bookmarks)
- Bob: 2 entries (1 reference, 1 idea)

## Related from Team (3)
- [Alice/session] DuckDB VSS benchmarks... -- 87% relevant
...

## Pending Review (1)
- [inbox] Unclassified feed item... -- awaiting review
```

### Hook Output Format (Condensed)

```
[Distillery] Project: distillery | 5 recent entries | 1 expiring soon | 2 stale
Recent: corrections chain (2h ago), FastMCP guide (yesterday), ...
Expiring: Jina API key rotation (Apr 15)
Stale: Sprint planning (45d), ...
```

## Repository Standards

- **Skill structure**: `skills/briefing/SKILL.md` with YAML frontmatter (`name`, `description`, `min_server_version`)
- **Skill conventions**: follow `skills/CONVENTIONS.md` (health check, author/project resolution, error handling)
- **Hook script**: bash, POSIX-compatible, `set -euo pipefail`, proper quoting
- **Commit format**: `feat(skills): add /briefing skill`, `feat(hooks): add SessionStart briefing hook`
- **Documentation**: update Skills Registry table in `skills/CONVENTIONS.md`

## Technical Considerations

- **Corrections section**: requires iterating recent entries and checking for `corrects` relations via `distillery_relations`. This is O(N) relation lookups where N is the number of recent entries. Limit to 20 entries to keep latency reasonable.
- **Expiring soon post-filter**: `distillery_list` returns entries with `expires_at` in the response. The skill filters client-side for `expires_at` within 7 days of now. This avoids needing a new filter parameter on `list`.
- **Team auto-detection**: `distillery_aggregate(group_by="author")` returns author counts. If `total_groups > 1`, enable team mode. Cached for the skill invocation (one call).
- **Hook JSON-RPC**: the hook calls the MCP server via HTTP JSON-RPC (`POST /mcp`). It needs to construct `tools/call` requests manually since it's bash, not an MCP client. The `Authorization: Bearer` header is required if OAuth is enabled.
- **Hook auth**: the script needs either a pre-obtained token or the MCP server running without auth (local stdio transport won't work from a hook — hooks run as shell commands, not MCP clients). Document that the hook targets the HTTP transport.
- **Skill vs hook**: the skill runs inside an MCP session with full tool access. The hook runs outside MCP as a bash script making HTTP calls. They produce different output formats (full markdown vs condensed one-liner).

## Security Considerations

- The hook script may contain or reference MCP endpoint URLs and bearer tokens. Document that `DISTILLERY_MCP_URL` and `DISTILLERY_BEARER_TOKEN` should not be committed to version control.
- The hook outputs entry previews into the system prompt. Entry content may contain sensitive information — the skill/hook should not filter for this (the user already stored it), but document the behavior.

## Success Metrics

- `/briefing` produces a formatted dashboard in under 5 seconds for a knowledge base with < 1000 entries
- The SessionStart hook injects context in under 3 seconds (including MCP round-trip)
- Solo mode works with zero configuration beyond project detection
- Team mode activates automatically when multiple authors exist

## Open Questions

No open questions at this time.
