# Distillery Skills — Shared Conventions

This document establishes the common patterns and conventions used by all Distillery skills (`/distill`, `/recall`, `/pour`, `/bookmark`, `/minutes`, `/classify`, `/watch`, `/radar`, `/tune`, `/setup`).

## SKILL.md Structure

All skills follow the same structure for consistency and clarity:

```yaml
---
name: <skill-name>
description: "Description of the skill's purpose and trigger phrases (case-insensitive: e.g., 'use when user says ...', 'triggered by ...')"
min_server_version: "0.3.0"  # optional — minimum MCP server version required
---

# <Skill Name> — Purpose/Tagline

One-sentence introduction of what the skill does.

## When to Use

- Bullet list of situations when the user should invoke this skill
- Common invocation phrases (e.g., "when user says 'save knowledge', 'capture this'")

## Process

### Step 1: <First Step Title>

Description of the first step. Include code blocks, examples, and prompts where relevant.

### Step 2: <Next Steps>

Continue with clear, sequential steps.

### Step N: Confirmation

Report results back to the user with the output format expected.

## Output Format

Describe what the user will see after the skill completes:
- Field names
- Example output
- Format/styling rules (markdown, tables, etc.)

## Rules

- Bullet list of constraints, patterns, and best practices
- Examples: "Always ask before proceeding if context is unclear", "Omit empty sections"
```

**Key Points:**
- YAML frontmatter must include `name` (lowercase, no spaces) and `description` (triggers for voice/text invocation)
- Markdown body follows: **When to Use** → **Process (Steps)** → **Output Format** → **Rules**
- Use clear section hierarchies (# for title, ## for main sections, ### for steps)
- Provide examples and expected output
- Keep step descriptions concise but complete

## Progressive Disclosure

Skills that exceed 150 lines should move detailed or mode-specific content into a `references/` subdirectory alongside the main `SKILL.md`.

**Pattern:**
- `SKILL.md` describes purpose, flags, and dispatch logic — it stays concise
- Mode-specific detail, help text, and reference tables live in `references/<file>.md`
- The main skill reads the reference file on demand: `Read references/<file>.md for details`

**Canonical example:** `/setup` uses `references/transport-detection.md` and `references/cron-payloads.md` to keep its main SKILL.md focused on the wizard flow.

**When to split:** If adding a new mode or section would push `SKILL.md` past 150 lines, extract it to `references/`. Update the relevant step or mode in `SKILL.md` with a single `Read references/<file>.md` instruction.

## API Key Configuration

API keys required by Distillery (embedding provider, GitHub OAuth) are declared in `plugin.json` under `userConfig`. Keys marked `sensitive: true` are stored in the OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service) via Claude Code's secure config system.

**Preferred method:** `userConfig` in `plugin.json` — keys are prompted on first use and stored securely.

**Fallback:** Environment variables (`JINA_API_KEY`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`) for CI or environments without keychain access.

## Author & Project Resolution

Determine author and project once per conversation, then cache for subsequent skills.

**Author** (priority order): `git config user.name` → `DISTILLERY_AUTHOR` env var → ask user.

**Project** (priority order): `--project` flag if provided → `basename $(git rev-parse --show-toplevel)` → ask user.

If already resolved earlier in the conversation, reuse the cached values without re-running commands.

## MCP Health Check

Skills depend on the Distillery MCP server. Call `distillery_metrics(scope="summary")` at the start of the first skill invoked in a conversation. **If `distillery_metrics(scope="summary")` has already succeeded earlier in the same conversation, skip the check and proceed directly.**

If the check fails, display:

```
Warning: Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.
Setup: see docs/mcp-setup.md
```

Stop immediately if MCP is unavailable.

**Authentication errors** (HTTP transport with OAuth): If `distillery_metrics(scope="summary")` returns an authentication error rather than a connection failure, direct the user to run `/setup` or complete the OAuth flow via the MCP server menu.

### Server Version Compatibility

Skills that require MCP tools added in a specific server version should declare `min_server_version` in their frontmatter. During the MCP health check, if `distillery_metrics(scope="summary")` succeeds, compare the returned `version` field against `min_server_version`. If the server version is older, display:

```text
Warning: This skill requires Distillery MCP server >= {min_server_version}.
Your server is running {actual_version}. Update with: pip install --upgrade distillery-mcp
```

## Canonical Dedup Flow

All write skills (`/distill`, `/bookmark`, `/minutes`, `/radar`) must check for duplicates before storing a new entry. The canonical deduplication flow follows a uniform 4-outcome pattern via the `distillery_find_similar(dedup_action=true)` MCP tool.

**When to Check:** Before calling `distillery_store`, invoke `distillery_find_similar(content="<content to store>", dedup_action=true)`.

**The 4 Outcomes:**

1. **`"create"`** — No similar entries found. Proceed to store the entry normally.

2. **`"skip"`** — Near-exact duplicate (similarity >= skip threshold, default 0.95). Show the user:
   ```
   Similar entry found (99% match):
   
   | Entry ID | Type | Author | Created | Preview |
   |----------|------|--------|---------|---------|
   | <id> | <type> | <author> | <date> | <preview> |
   
   Options:
   1. Store anyway (create a separate entry)
   2. Skip (don't store)
   ```
   
   On "skip": Confirm "Skipped. No new entry was stored." and stop.

3. **`"merge"`** — Very similar entry exists (similarity >= merge threshold, default 0.80). Show the user:
   ```
   Very similar entry exists (88% match):
   
   | Entry ID | Type | Author | Created | Preview |
   |----------|------|--------|---------|---------|
   | <id> | <type> | <author> | <date> | <preview> |
   
   Options:
   1. Store anyway (create a separate entry)
   2. Merge with existing (append new content to this entry)
   3. Skip (don't store)
   ```
   
   On "merge": Call `distillery_update(<entry_id>, merged_content)`, confirm success, and stop.
   
   On "store anyway" or "skip": Handle as directed.

4. **`"link"`** — Related but distinct entry exists (similarity >= link threshold, default 0.60). Show the user:
   ```
   Related entry found (72% match):
   
   | Entry ID | Type | Author | Created | Preview |
   |----------|------|--------|---------|---------|
   | <id> | <type> | <author> | <date> | <preview> |
   
   New entry will be linked to this related entry.
   
   Options:
   1. Store with link
   2. Skip
   ```
   
   On "store with link": Include `"related_entries": ["<id>", ...]` in the metadata passed to `distillery_store`, then proceed normally.
   
   On "skip": Confirm "Skipped. No new entry was stored." and stop.

**Implementation Pattern:**

```python
# Step 1: Check for duplicates
response = await distillery_find_similar(content="<content>", dedup_action=true)
action = response["action"]  # One of: create, skip, merge, link

# Step 2: Handle by action
if action == "create":
    # Proceed to store
    await distillery_store(...)

elif action == "skip":
    # Show similar entries, ask user
    # If user chooses "skip": stop
    # If user chooses "store anyway": await distillery_store(...)

elif action == "merge":
    # Show similar entries, ask user
    # If user chooses "merge": await distillery_update(entry_id, merged_content)
    # If user chooses "store anyway": await distillery_store(...)
    # If user chooses "skip": stop

elif action == "link":
    # Show related entry, ask user
    # If user chooses "store with link": 
    #   - Add related_entries to metadata
    #   - await distillery_store(metadata={"related_entries": [...]}, ...)
    # If user chooses "skip": stop
```

## Confirmation Format

All write skills (`/distill`, `/bookmark`, `/minutes`, `/radar`) must follow a unified confirmation template when storing entries. This ensures consistent user experience and predictable output parsing.

**Standard Confirmation Template:**

```
[<entry_type>] Stored: <entry-id>
Project: <project> | Author: <author>
Summary: <first 200 chars>...
Tags: tag1, tag2, tag3
```

**Field Definitions:**

- **`<entry_type>`** — The entry type in uppercase badge (e.g., `[SESSION]`, `[BOOKMARK]`, `[MINUTES]`). Use the canonical name from the Entry Types table below.
- **`<entry-id>`** — The UUID returned by `distillery_store` or `distillery_update`.
- **`<project>`** — The project name or "None" if not specified.
- **`<author>`** — The author determined per the Author & Project Resolution section.
- **Summary** — First 200 characters of the content, with `...` if truncated. If content is shorter, show the whole content.
- **Tags** — Comma-separated list of tags assigned to the entry (lowercase, hyphen-separated, hierarchical). If no tags, show "none".

**Example confirmations:**

```
[SESSION] Stored: a1b2c3d4-e5f6-47g8-9h0i-j1k2l3m4n5o6
Project: distillery | Author: Alice
Summary: This session covered the dedup flow refactor, which consolidates four outcomes (create, skip, merge, link) into a...
Tags: session, architecture, dedup

[BOOKMARK] Stored: f7e8d9c0-b1a2-93c4-5d6e-7f8g9h0i1j2k
Project: None | Author: Bob
Summary: Excellent reference on embeddings and vector search in databases.
Tags: database, embeddings, vector-search

[MINUTES] Stored: 2e3f4g5h-6i7j-k8l9-m0n1-o2p3q4r5s6t7
Project: distillery-team | Author: Carol
Summary: Discussed progress on skill UX improvements, dedup standardization, and entry type documentation. Decisions: proceed with confirmation format...
Tags: meeting, distillery, planning, decisions
```

## Entry Types

The following table lists all valid `entry_type` values, their producing skills, required metadata fields, and use cases.

| Type | Producing Skill | Required Metadata | Optional Metadata | Use Case |
|------|---|---|---|---|
| `session` | `/distill` | — | — | Captured work session, context snapshot, or conversation excerpt |
| `bookmark` | `/bookmark` | — | `url`, `title` | Saved URLs, external references, articles |
| `minutes` | `/minutes` | `meeting_id` | `attendees`, `version` | Meeting notes, discussion records, standup summaries |
| `meeting` | — (future) | — | — | Structured meeting agenda and outcomes (reserved for future use) |
| `reference` | — (manual) | — | — | Reference documents, snippets, facts (typically imported or manual) |
| `idea` | — (manual) | — | — | Ideas, hypotheses, open questions (typically manual entries) |
| `inbox` | `/classify` (internal state) | — | — | Unsorted entries awaiting classification or review |
| `person` | — (manual) | `expertise` (list) | `github_username`, `team`, `role`, `email` | Team member profiles, contributor records, contact cards |
| `project` | — (manual) | `repo` | `status`, `language`, `description` | Project records, repository metadata, initiative tracking |
| `digest` | `/radar` | `period_start`, `period_end` | `sources`, `summary` | Periodic summaries of feed activity and signals |
| `github` | `/watch` (poll) | `repo`, `ref_type`, `ref_number` | `title`, `url`, `state` | GitHub issues, PRs, discussions, releases (ref_type constrained to: issue, pr, discussion, release) |
| `feed` | `/watch` (poll) | `source_url`, `source_type` | `title`, `item_url`, `published_at`, `relevance_score` | Entries from monitored RSS or GitHub feeds (source_type: rss or github) |

**Notes:**

- Types marked "—" under Producing Skill are not typically generated by skills (they are manual, imported, or reserved for future use).
- Required metadata fields must be present when storing an entry of that type, or validation will fail.
- Optional metadata fields may be included but are not required.
- The `metadata.meeting_id` for `minutes` entries follows the format `<slugified-title>-<YYYY-MM-DD>`.

## Entry Sources

The following table lists all valid `source` values, describing their origin and trust semantics.

| Source | Trust Level | Use Case |
|--------|-------------|----------|
| `claude-code` | High | Created by a Claude Code skill (e.g., `/distill`, `/bookmark`, `/minutes`). Verify once before trusting. |
| `manual` | High | Created directly by a human operator. Most trustworthy; user-curated. |
| `import` | Medium | Bulk-imported from an external source or dump. May need review or reconciliation. |
| `inference` | Low | Auto-extracted by hooks or LLM analysis (e.g., code comments, error logs, transcripts). Verify before using in decisions. |
| `documentation` | Medium-High | Extracted from docs, README, API references, or other verifiable sources. Trustworthy if the source is current. |
| `external` | Low | From web search, external APIs, or third-party data (e.g., Stack Overflow, RSS feeds). May be outdated or inaccurate. |

**Trust Hierarchy (highest to lowest):** `manual` > `claude-code` > `documentation` > `import` > `external` > `inference`.

Use the `source` filter in `/recall` to retrieve entries by provenance (e.g., search only documentation sources for verified facts).

## Error Handling

If any MCP tool returns an error, display it and stop (no retry loops):

```
Error: <error message>

Actions:
- "API key invalid" → Check embedding provider credentials
- "Database error" → Ensure database path is writable
- "Entry not found" → Verify entry ID or search with /recall
- "Connection error" → Verify MCP server is running
```

## Tag Extraction

- Auto-extract 2–5 keywords from content; merge with explicit `#tag` arguments
- Tags are lowercase, hyphen-separated within segments
- Prefer hierarchical: `project/{repo}/sessions`, `domain/{topic}`, `source/bookmark/{domain}`
- Strip leading `#` from user-provided tags

## Provenance

Search results must include: entry ID, `[type]` badge, author, created date, similarity %.

Format: `ID: <uuid> | Author: <name> | Project: <project> | <date>`

## Corrections

When a user disputes or corrects information in a retrieved entry — "that's wrong", "actually it's X", "this is outdated" — use `distillery_correct(wrong_entry_id, content)` instead of `distillery_update`. Update edits in place; correct creates an audit trail.

**When to correct (not update):**
- The entry's factual content is wrong ("the API uses OAuth" → actually it uses API keys)
- Information has become false since it was stored ("we use Postgres" → migrated to DuckDB)
- The user explicitly says an entry is incorrect

**When to update (not correct):**
- Adding tags, changing status, fixing typos, appending notes
- The original content isn't wrong, just incomplete

**Flow:** Compose the full corrected text (not a diff), call `distillery_correct` with the wrong entry's ID. The tool inherits entry_type, author, project, and tags from the original — only override these if they also changed. The original is archived automatically; the correction links to it via a `corrects` relation.

## Consistency Rules

1. Errors first — report and stop before proceeding
2. Ask before proceeding if critical context is unclear
3. Markdown output (headers, tables, code blocks)
4. No retry loops — if a tool fails, report and stop
5. Confirm store/update operations with entry ID and summary

## Skills Registry

The following skills are available in `skills/`:

| Skill | Directory | Primary MCP Tools | Purpose |
|-------|-----------|-------------------|---------|
| `/distill` | `distill/` | distillery_store, distillery_find_similar | Capture knowledge from conversations |
| `/recall` | `recall/` | distillery_search | Semantic search over the knowledge base |
| `/pour` | `pour/` | distillery_search, distillery_tag_tree | Multi-entry synthesis with citations and tag-based query expansion |
| `/bookmark` | `bookmark/` | distillery_store, distillery_find_similar | Save and annotate URLs |
| `/minutes` | `minutes/` | distillery_store, distillery_update, distillery_list | Record and update meeting notes |
| `/classify` | `classify/` | distillery_classify, distillery_list(output_mode=review), distillery_resolve_review | Classify and review entries |
| `/watch` | `watch/` | distillery_watch | Manage monitored feed sources + auto-poll scheduling (CronCreate local; GitHub Actions for hosted) |
| `/radar` | `radar/` | distillery_search, distillery_interests, distillery_list (fallback), distillery_store | Interest-driven feed digest and source suggestions |
| `/tune` | `tune/` | distillery_metrics | Display and adjust feed relevance thresholds |
| `/setup` | `setup/` | distillery_metrics | MCP connectivity wizard and transport configuration |
| `/digest` | `digest/` | distillery_list, distillery_aggregate, distillery_metrics, distillery_search, distillery_store, distillery_find_similar | Generate structured summaries of internal team activity |
| `/gh-sync` | `gh-sync/` | distillery_store, distillery_get, distillery_update, distillery_list, distillery_relations | Sync GitHub issues and PRs into the knowledge base |
| `/investigate` | `investigate/` | distillery_search, distillery_get, distillery_relations, distillery_tag_tree, distillery_list, distillery_metrics | Deep context builder combining semantic search with relationship traversal |
| `/briefing` | `briefing/` | distillery_metrics, distillery_list, distillery_aggregate, distillery_interests, distillery_search, distillery_stale, distillery_tag_tree | Single-command team knowledge dashboard |

## Custom Agents

The `distillery-researcher` agent (`.claude/agents/distillery-researcher.md`) is pre-wired with all Distillery read tools and is invoked automatically for `/pour` and `/radar` workflows that require deep multi-pass retrieval or ambient digest synthesis.

---

**Document Version:** 2.4
**Last Updated:** 2026-04-08
