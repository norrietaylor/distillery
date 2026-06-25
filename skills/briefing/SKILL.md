---
name: briefing
description: "Produce a knowledge dashboard with recent entries, corrections, expiring soon, stale knowledge, and unresolved items. In team mode, also shows team activity, related entries from teammates, and the review queue."
allowed-tools:
  - "mcp__*__distillery_status"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_relations"
  - "mcp__*__distillery_search"
  - "Bash(git rev-parse --show-toplevel)"
context: fork
effort: medium
---

<!-- Trigger phrases: briefing, /briefing, knowledge briefing, knowledge dashboard, project overview, my briefing, team briefing -->

# Briefing — Knowledge Dashboard (Solo & Team)

Briefing produces a single-command knowledge dashboard: recent entries, pending corrections, soon-to-expire items, stale knowledge, and unresolved work — all scoped to your project. When multiple authors are detected (or `--team` is passed), team sections are added automatically.

## When to Use

- Starting a work session to orient yourself (`/briefing`)
- Checking the state of your knowledge base at a glance
- Getting a project-scoped overview of what needs attention
- "knowledge briefing", "project dashboard", "my briefing", "knowledge overview"
- Scoping to a specific project (`/briefing --project distillery`)
- Viewing team activity and cross-author context (`/briefing --team`)

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Resolve Project

Determine project using the standard resolution order from CONVENTIONS.md:

1. `--project <name>` flag if provided
2. `basename $(git rev-parse --show-toplevel)` from the current working directory
3. Ask the user

If already resolved earlier in the conversation, reuse the cached value.

### Step 3: Parse Arguments

| Flag | Description |
|------|-------------|
| `--project <name>` | Scope results to a specific project (auto-detected if omitted) |
| `--team` | Force team mode regardless of author count |

This is a display-only skill with no configurable lookback window. Team mode is activated by `--team` or auto-detected in Step 4f.

### Step 4: Gather Data

Execute all calls in sequence. Non-fatal calls are noted — continue if they fail.

**4a. Recent entries (project-wide fetch):**

```python
distillery_list(project=<project>, limit=50, output_mode="summary")
```

This single project-scoped, newest-first fetch backs three sections — Recent Entries, Corrections, and Expiring Soon — so they share one round-trip instead of issuing duplicate project lists. Use `output_mode="summary"` (NOT `full`): summary returns the full `metadata` blob (incl. `expires_at`, `corrects` / `corrected_by`) plus a ~200-char `content_preview` per entry — enough for the 100-char previews these sections render — while keeping the response to a few tens of KB instead of the ~80 KB that `output_mode="full"` returned at `limit=50`.

For **Recent Entries (Section 1)**, take the first 10 entries of this result (already sorted newest first). Record all 50 returned entries for reuse by the steps below.

**4b. Corrections (non-fatal):**

From the entries fetched in Step 4a, identify candidate correction entries: those whose `metadata` carries `corrects` or `corrected_by`. For each such candidate, resolve the correction pair best-effort:

```python
distillery_relations(action="get", entry_id=<id>, relation_type="corrects")
```

This relations lookup is best-effort — never block the briefing on it. Treat an empty/sparse result as a non-error (skip that pair and continue). If a lookup returns an `INTERNAL` error whose message contains `"NetworkX not installed"`, emit a single one-line note `Run \`pip install distillery-mcp[graph]\` to enable relation lookups.` and stop issuing further relation lookups for this section. When the relation lookup is unavailable, fall back to pairing from the `metadata.corrects` / `metadata.corrected_by` ids resolved against the entries already fetched above.

Collect correction pairs `(corrector_entry, original_entry)`, limit to 5 chains. If no candidate entries carry correction metadata, omit the Corrections section.

**4c. Expiring soon (non-fatal):**

From the 50 entries fetched in Step 4a, post-filter for entries where `metadata.expires_at` is set and falls within the next 7 days (between today and today + 7 days inclusive). Sort ascending by `expires_at`. If no entries have an upcoming `expires_at`, omit the Expiring Soon section.

**4d. Stale knowledge (non-fatal):**

```python
distillery_list(stale_days=30, limit=5, project=<project>, output_mode="full")
```

Record stale entries. If this call fails, omit the Stale Knowledge section.

**4e. Unresolved (non-fatal):**

```python
distillery_list(project=<project>, verification="testing", limit=5, output_mode="full")
```

Returns entries in the "testing" verification state (entries that have been flagged as needing review but are not yet verified). If this call fails or returns nothing, omit the Unresolved section.

**4f. Team mode detection:**

If `--team` was passed, set `team_mode = true` and skip the author count check.

Otherwise, call:

```python
distillery_list(group_by="author", project=<project>)
```

If the response contains more than one author group, set `team_mode = true`. If the call fails, set `team_mode = false` and continue (non-fatal).

**4g. Team activity (team mode only, non-fatal):**

Only execute if `team_mode = true`.

Reuse the 50 entries already fetched in Step 4a (same project, newest-first) — no extra `distillery_list` call is needed, since summary mode carries `author`, `entry_type`, and `created_at`. Filter to those created within the past 7 days, group by author, and for each author count entries by `entry_type`. If Step 4a yielded no entries within the past 7 days, omit the Team Activity section.

**4h. Related from team (team mode only, non-fatal):**

Only execute if `team_mode = true`.

Use the project name and recent entry content as context for the query. Call:

```python
distillery_search(query=<project_context>, limit=5, output_mode="full")
```

where `<project_context>` is formed from the project name combined with a short summary of the most recent entries (first 50 chars of each). Do not apply an author filter — this surfaces entries from all authors. Record similarity percentage for each result. If this call fails or yields no results, omit the Related from Team section.

**4i. Pending review (team mode only, non-fatal):**

Only execute if `team_mode = true`.

```python
distillery_list(status="pending_review", limit=5, output_mode="full")
```

Returns entries awaiting classification. If this call fails or returns nothing, omit the Pending Review section.

### Step 5: Synthesize Briefing

Produce the briefing in markdown. Omit any section entirely if it has no data.

**Header:**

```
# Briefing: <project> (solo)       ← when team_mode = false
# Briefing: <project> (team)       ← when team_mode = true
Generated: <YYYY-MM-DD HH:MM> UTC
```

**Section 1 — Recent Entries:**

For each of the 10 most recent entries from Step 4a, show one line:

```
- [<TYPE>] <content preview, max 100 chars> — <relative timestamp>
```

- `[TYPE]` badge: entry type in uppercase, e.g., `[SESSION]`, `[BOOKMARK]`, `[MINUTES]`
- Content preview: first 100 characters of entry content, truncated with `…` if longer
- Relative timestamp: human-readable age, e.g., "2 hours ago", "3 days ago", "just now"

**Section 2 — Corrections:**

For each correction chain from Step 4b:

```
- [<TYPE>] <corrector preview, max 100 chars> corrects → [<TYPE>] <original preview, max 100 chars>
```

Show at most 5 chains. Omit this section if no correction relations exist.

**Section 3 — Expiring Soon:**

For each entry expiring within 7 days from Step 4c, sorted soonest first:

```
- [<TYPE>] <content preview, max 100 chars> — expires <relative timestamp> (<YYYY-MM-DD>)
```

Omit this section if no entries are expiring soon.

**Section 4 — Stale Knowledge:**

For each stale entry from Step 4d:

```
- [<TYPE>] <content preview, max 100 chars> — last accessed <relative timestamp>
```

Omit this section if no stale entries are found.

**Section 5 — Unresolved:**

For each entry from Step 4e:

```
- [<TYPE>] <content preview, max 100 chars> — <relative timestamp>
```

Omit this section if no unresolved entries exist.

**Section 6 — Team Activity (team mode only):**

Only render if `team_mode = true`. Omit if no data from Step 4g.

For each author group (sorted by entry count descending), show:

```
## Team Activity (7 days)

- <Author>: <N> entries (<type1_count> <type1>, <type2_count> <type2>, …)
```

Example:

```
- Alice: 5 entries (3 sessions, 2 bookmarks)
- Bob: 2 entries (1 reference, 1 idea)
```

Include only entry types with count > 0. Omit this section entirely if no team entries found in the past 7 days.

**Section 7 — Related from Team (team mode only):**

Only render if `team_mode = true`. Omit if no data from Step 4h.

For each result from the team semantic search:

```
- [<TYPE>] <Author> — <content preview, max 100 chars> — <similarity>% relevant
```

Show at most 5 results. Omit this section if the search returned no results.

**Section 8 — Pending Review (team mode only):**

Only render if `team_mode = true`. Omit if no data from Step 4i.

For each entry from Step 4i:

```
- [<TYPE>] <content preview, max 100 chars> — awaiting review
```

Show at most 5 entries. Omit this section if no entries are in `pending_review` status.

### Step 6: Display

Display the synthesized briefing. This skill is display-only — there is no `--store` flag.

## Output Format

Solo mode (`/briefing` or `/briefing --project distillery` with single author):

```
# Briefing: <project> (solo)
Generated: 2026-04-08 09:15 UTC

---

## Recent Entries

- [SESSION] Refactored the dedup flow to handle four outcomes… — 2 hours ago
- [BOOKMARK] Vector search in DuckDB — key patterns and pitfalls… — 1 day ago
- [MINUTES] Standup 2026-04-07: decided to ship the briefing ski… — 1 day ago

---

## Corrections

- [SESSION] The correct threshold for merge is 0.80, not 0.75… corrects → [SESSION] Dedup thresholds: skip=0.95, merge=0.75…

---

## Expiring Soon

- [BOOKMARK] Trial API key for embedding provider — expires in 3 days (2026-04-11)

---

## Stale Knowledge

- [REFERENCE] Old deployment notes for the pre-Fly.io setup… — last accessed 45 days ago

---

## Unresolved

- [SESSION] Spike: evaluate pgvector as an alternative to DuckDB… — 5 days ago
```

Team mode appends these additional sections after the solo sections (`/briefing --team` or auto-detected when >1 author):

```
# Briefing: <project> (team)
Generated: 2026-04-08 09:15 UTC

---

## Recent Entries
…(same solo sections)…

---

## Team Activity (7 days)

- Alice: 5 entries (3 sessions, 2 bookmarks)
- Bob: 2 entries (1 reference, 1 idea)

---

## Related from Team

- [SESSION] Alice — DuckDB VSS benchmarks show HNSW outperforms flat… — 87% relevant
- [BOOKMARK] Bob — FastMCP 3.1 migration guide with async context… — 74% relevant

---

## Pending Review

- [INBOX] Unclassified feed item about vector search… — awaiting review
```

## Rules

- NEVER use Bash, Python, or any tool not listed in allowed-tools
- MCP availability is the once-per-conversation `distillery_status()` check (Step 1, see CONVENTIONS.md) — skip it if already confirmed this conversation. Do NOT issue a separate `distillery_list(limit=1)` health probe; the recent-entries call (Step 4a) is the first real data call and proves availability.
- If a required (non-optional) MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.
- If a call is marked non-fatal below (corrections, stale knowledge, unresolved items, team-mode probes, and team sections 6/7/8), omit that section and continue.
- Auto-detect project from `basename $(git rev-parse --show-toplevel)` when `--project` is not provided
- Display-only — no `--store` flag, no storing of output
- Omit any section that has no data — never show empty section headings
- Entry previews are capped at 100 characters with `…` truncation; never show raw multi-line content inline
- Type badges are uppercase: `[SESSION]`, `[BOOKMARK]`, `[MINUTES]`, `[REFERENCE]`, `[FEED]`, `[DIGEST]`, `[GITHUB]`, `[INBOX]`, `[IDEA]`, `[PERSON]`, `[PROJECT]`
- Relative timestamps use human-readable form: "just now", "5 minutes ago", "2 hours ago", "3 days ago"
- Expiring-soon filter is applied client-side from already-fetched entries — no extra MCP call needed
- Corrections section detects candidates from `metadata.corrects` / `metadata.corrected_by` in the Step 4a `output_mode="summary"` list (summary carries full `metadata`), then resolves pairs via `distillery_relations(action="get", relation_type="corrects")` — this relation lookup is best-effort: empty/sparse results and a `"NetworkX not installed"` `INTERNAL` error are non-fatal (emit the one-line `pip install distillery-mcp[graph]` note and fall back to metadata-only pairing)
- Stale knowledge failure is non-fatal — omit the section and continue
- Unresolved failure is non-fatal — omit the section and continue
- Team mode is activated by `--team` flag or auto-detected: `distillery_list(group_by="author", project=<project>)` returning >1 author group
- Header shows `(solo)` or `(team)` based on detected mode
- Team sections (6, 7, 8) are additive — solo sections are always rendered unchanged
- Team activity groups entries by author from the past 7 days only — entries older than 7 days are excluded
- Related from team uses `distillery_search` without author filter — all authors are included
- Pending review uses `status="pending_review"` — limited to 5 entries
- Team aggregate call failure is non-fatal — fall back to solo mode
- Team activity, related from team, and pending review failures are non-fatal — omit each failed section
- On MCP errors in fatal calls (Step 1 `distillery_status()` health check, Step 4a recent-entries list), see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
