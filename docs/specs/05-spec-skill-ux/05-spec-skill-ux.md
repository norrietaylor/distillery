# 05-spec-skill-ux

## Introduction/Overview

Address 8 skill UX gaps (issue #98, high + medium priority) that affect consistency, data integrity, and user experience across the 10 Distillery skills. This covers dedup standardization, `--project` filtering, output format consistency, `/radar` consent, token budget reduction, `/tune` runtime config application, entry type documentation, and progressive disclosure for complex skills.

## Goals

1. All write skills use `distillery_find_similar(dedup_action=true)` with the same 4-outcome flow (create/skip/merge/link)
2. All list/search/batch operations support `--project` filtering
3. Store confirmations follow a single format template defined in CONVENTIONS.md
4. `/radar` defaults to display-only (no auto-store), requiring `--store` for persistence
5. `/tune` applies threshold changes at runtime via a new `distillery_configure` MCP tool

## User Stories

- As a **user storing meeting notes**, I want `/minutes` to check for duplicates so that I don't accidentally create duplicate meeting records.
- As a **team member**, I want `--project` filtering on all skills so that I can scope operations to my project in a shared knowledge base.
- As a **user reading confirmations**, I want a consistent format across all skills so that I can quickly parse entry IDs, tags, and metadata regardless of which skill I used.
- As a **user running `/radar`**, I want to see the digest without it being stored by default so that I control what enters the knowledge base.
- As a **user tuning thresholds**, I want `/tune` to apply changes immediately without manually editing YAML and restarting the server.

## Demoable Units of Work

### Unit 1: Dedup Standardization Across Write Skills

**Purpose:** Ensure all skills that create entries use `distillery_find_similar(dedup_action=true)` with the canonical 4-outcome flow, closing the data integrity gap where `/minutes` and `/radar` can create duplicates unchecked.

**Functional Requirements:**
- `/minutes` SKILL.md shall call `distillery_find_similar(content="<meeting notes summary>", dedup_action=true)` before storing a new meeting record (not on `--update` mode, which modifies an existing entry).
- `/minutes` dedup shall match on content similarity, with an additional check: if `metadata.meeting_id` matches an existing entry, treat as `"skip"` and suggest `--update` instead.
- `/radar` SKILL.md shall call `distillery_find_similar(content="<digest summary>", dedup_action=true)` before storing a digest (when `--store` is specified — see Unit 3).
- Both skills shall handle all 4 outcomes (create/skip/merge/link) identically to `/distill` and `/bookmark`.
- CONVENTIONS.md shall include a `## Canonical Dedup Flow` section documenting the standard dedup pattern that all write skills must follow, referencing `distillery_find_similar(dedup_action=true)` and the 4 outcomes with user-facing prompts.

**Proof Artifacts:**
- File: `.claude-plugin/skills/minutes/SKILL.md` contains `distillery_find_similar(dedup_action=true)` call
- File: `.claude-plugin/skills/radar/SKILL.md` contains `distillery_find_similar(dedup_action=true)` call
- File: `.claude-plugin/skills/CONVENTIONS.md` contains `## Canonical Dedup Flow` section

### Unit 2: `--project` Filtering and Output Format Standardization

**Purpose:** Add `--project` filtering to all skills that list or search entries, and define a single confirmation format template in CONVENTIONS.md that all write skills follow.

**Functional Requirements:**
- The following skills shall support a `--project <name>` flag that filters results by the `project` field:
  - `/classify --inbox` and `/classify --review` — filter pending/review entries by project
  - `/minutes --list` — filter meeting records by project
  - `/radar` — scope digest generation to entries from a specific project
- Each skill's SKILL.md shall document the `--project` flag in its flags table and pass `project=<name>` to the relevant MCP tool calls (`distillery_list`, `distillery_search`, `distillery_list(output_mode="review")`).
- CONVENTIONS.md shall include a `## Confirmation Format` section defining the standard output template for all store operations:
  ```
  [<entry_type>] Stored: <entry-id>
  Project: <project> | Author: <author>
  Summary: <first 200 chars>...
  Tags: tag1, tag2, tag3
  ```
- All write skills (`/distill`, `/bookmark`, `/minutes`, `/radar`) shall update their confirmation output to follow this template.
- CONVENTIONS.md shall include an `## Entry Types` table listing all valid `entry_type` values, their producing skills, and their expected metadata fields:

  | Type | Producing Skill | Required Metadata |
  |------|----------------|-------------------|
  | `session` | `/distill` | — |
  | `bookmark` | `/bookmark` | `url`, `title` |
  | `minutes` | `/minutes` | `meeting_id` |
  | `feed` | `/watch` (poll) | `source_url`, `source_type` |
  | `digest` | `/radar` | `period_start`, `period_end` |

**Proof Artifacts:**
- File: `/classify`, `/minutes`, `/radar` SKILL.md files document `--project` flag
- File: CONVENTIONS.md contains `## Confirmation Format` section
- File: CONVENTIONS.md contains `## Entry Types` table with 5+ entry types
- File: `/distill`, `/bookmark`, `/minutes` SKILL.md confirmation outputs follow the template

### Unit 3: `/radar` Consent and `/tune` Runtime Configuration

**Purpose:** Flip `/radar` to display-only by default and add a `distillery_configure` MCP tool so `/tune` can apply threshold changes at runtime without manual YAML editing.

**Functional Requirements:**
- `/radar` SKILL.md shall change the default behavior: digests are displayed but NOT stored unless `--store` is explicitly passed.
- The `--no-store` flag shall be removed (it becomes the default).
- A `--store` flag shall be added that triggers digest storage with dedup checking (from Unit 1).
- The MCP server shall register a new tool `distillery_configure` that accepts configuration changes and applies them at runtime:
  - Parameters: `section` (string, e.g., `"feeds.thresholds"`), `key` (string, e.g., `"alert"`), `value` (string/number)
  - The tool shall update the in-memory config AND write the change to `distillery.yaml` on disk.
  - The tool shall validate that the new value is within acceptable ranges (e.g., thresholds between 0.0 and 1.0, alert >= digest).
  - The tool shall return the previous and new values for confirmation.
- `/tune` SKILL.md shall be updated to call `distillery_configure` instead of printing YAML snippets.
- `/tune` shall display before/after values and confirm the change was applied.
- The `distillery_configure` tool shall be added to `/tune`'s `allowed-tools` list.

**Proof Artifacts:**
- File: `/radar` SKILL.md documents `--store` flag and display-only default
- File: `/radar` SKILL.md does NOT contain `--no-store` flag
- File: `src/distillery/mcp/server.py` (or domain module) registers `distillery_configure` tool
- Test: `pytest tests/test_mcp_configure.py` passes with validation and persistence tests
- File: `/tune` SKILL.md calls `distillery_configure` instead of printing YAML

### Unit 4: Token Budget Reduction and Progressive Disclosure

**Purpose:** Reduce SKILL.md token consumption for heavy skills by moving detailed reference material into `references/` subdirectories, and split complex skill modes into separate reference files.

**Functional Requirements:**
- `/setup` SKILL.md (287 lines) shall be refactored to move the following into `references/` files:
  - Cron job payload definitions → `references/cron-payloads.md`
  - Transport detection logic → `references/transport-detection.md`
  - The main SKILL.md shall reference these files with "Read `references/<file>.md` for details" instructions.
  - Target: SKILL.md body ≤150 lines (excluding frontmatter).
- `/watch` SKILL.md shall move scheduling/webhook configuration into `references/scheduling.md` if present (currently 111 lines — may not need splitting if already lean).
- `/classify` SKILL.md shall split its 3 modes (`--inbox`, `--review`, `<entry_id>`) into reference files if the main SKILL.md exceeds 150 lines.
- Complex skills (`/setup`, `/classify`, `/watch`) shall use progressive disclosure: the main SKILL.md describes the skill purpose, flags, and dispatch logic; mode-specific details live in `references/` and are read on demand.
- CONVENTIONS.md shall document the `references/` pattern as a standard for skills exceeding 150 lines.

**Proof Artifacts:**
- File: `.claude-plugin/skills/setup/references/cron-payloads.md` exists
- File: `.claude-plugin/skills/setup/references/transport-detection.md` exists
- File: `.claude-plugin/skills/setup/SKILL.md` body is ≤150 lines
- File: CONVENTIONS.md documents the `references/` progressive disclosure pattern

## Non-Goals (Out of Scope)

- Low-priority items (9–15): help mode, `--dry-run`, skill chaining, batch operations, feedback/rating, error recovery paths, skill versioning — deferred to future spec
- Server-side MCP refactoring (spec 05 covers that)
- Skill frontmatter changes (spec 04 already addressed `allowed-tools`, `disable-model-invocation`, etc.)
- Entry storage logic changes beyond dedup — no changes to how entries are stored, only to pre-store validation
- Changes to `/recall` or `/pour` (they already support `--project`)

## Design Considerations

No specific design requirements identified. All changes are to SKILL.md files, CONVENTIONS.md, and one new MCP tool.

## Repository Standards

- **Conventional Commits**: `chore(skills):` for SKILL.md changes, `feat(mcp):` for `distillery_configure` tool, `docs(conventions):` for CONVENTIONS.md
- **mypy --strict** on the new MCP tool handler
- **pytest** unit tests for `distillery_configure` validation logic

## Technical Considerations

- **`distillery_configure`**: Must write to `distillery.yaml` atomically (write to temp file, rename). Must reload the in-memory config object after writing. Must handle concurrent access safely (lock or serialize writes).
- **Dedup in `/minutes`**: The `meeting_id` match should take precedence over content similarity — if the same `meeting_id` exists, always suggest `--update` rather than creating a new entry.
- **`--project` on `distillery_list(output_mode="review")`**: The MCP tool must already support a `project` parameter, or the filter must be applied client-side in the skill. Check the tool schema before implementing.
- **Token counting**: Use `wc -l` as a proxy for token budget. The 150-line target for SKILL.md bodies corresponds to roughly 2,000 tokens.

## Security Considerations

- `distillery_configure` writes to `distillery.yaml` — ensure it only accepts known configuration keys (allowlist, not blocklist) to prevent arbitrary file writes.
- Validate threshold ranges server-side, not just in the skill — the MCP tool is the enforcement point.

## Success Metrics

| Metric | Target |
|--------|--------|
| Write skills with dedup | 4/4 (`/distill`, `/bookmark`, `/minutes`, `/radar`) |
| Skills supporting `--project` | All list/search/batch operations |
| Confirmation format consistency | All write skills follow CONVENTIONS.md template |
| `/radar` default behavior | Display-only (no auto-store) |
| `/tune` runtime apply | Changes applied via MCP, no manual YAML editing |
| `/setup` SKILL.md line count | ≤150 lines (body) |

## Open Questions

1. **`distillery_list(output_mode="review")` project filter**: Does the MCP tool's current schema accept a `project` parameter? If not, the tool needs a schema update alongside the skill change.
2. **Config hot-reload**: When `distillery_configure` writes to YAML, does the in-memory config need a full reload, or can individual values be patched? A full reload is safer but may have side effects if other config sections are being used concurrently.
