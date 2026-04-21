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

## Retrieval Hygiene for Skills with a Known Current Focus

Skills that call `distillery_search` or `distillery_find_similar` for context about a specific entry the user is working on (`/pour`, `/recall`, `/investigate`, triage-style workflows) should follow these patterns to avoid noise, self-references, and decorative citations.

### Rule 1 — Self-filter before citing (mandatory)

When a retrieval skill has a known current focus (an entry being synthesized about, an issue being triaged, a bookmark being annotated), filter out any returned entry whose id matches the focus before presenting results to the model. With real semantic embeddings (Jina v5, OpenAI `text-embedding-3`, or any OpenAI-compatible embedding endpoint), the search will rank the current entry at or near the top of every call against its own content — it is closer to itself than anything else in the KB, typically scoring 0.98–1.00 versus 0.85–0.95 for the next-most-relevant entries.

Without this filter, the model tends to "discover" its own current focus as the top related prior entry and cites it as such, which is always nonsensical.

### Rule 2 — Mandatory visible classification step (recommended)

**Status:** Recommended. Validated on the single benchmark below. Adopt in new retrieval skills where citation noise is a concern; do not retrofit across all skills until another skill replicates the effect.

When a skill's primary task is generation (writing a triage comment, a synthesis, a reply, a review) and retrieval is a supporting step, force the model to produce a visible classification of each retrieved entry as a required output section *before* it writes the main output. Good tags to emit inline per entry:

- `skip-self` — filtered per Rule 1
- `cite-as-duplicate` — materially the same problem or feature as the current focus
- `cite-as-precedent` — prior PR or fix that implements the pattern this focus asks for
- `cite-as-decision` — prior design decision or rejection relevant to how this focus should be approached
- `skip-decorative` — semantically related (same subsystem, file, topic) but does not change the recommendation

The section must emit one line per returned entry — no silent omissions.

Progressively stricter "only cite if…" rules produced *fewer* citations in the benchmark below, dropping from round 1's ~12 to round 3's 1. Round 4 replaced the rules with a mandatory visible classification step and citation count jumped to 29 across 11/13 focuses with all 4 high-value recoveries. The diagnosis is instruction dilution — background rules layered onto a generation task get silently dropped; a required output line is a visible contract the model cannot omit.

**Does not apply to `/pour`.** `/pour`'s SKILL.md requires citing every factual claim as an audit trail, which is cite-everywhere by design. Rule 2's cite-only-when-it-matters guidance is for decision-support skills (`/recall`, `/investigate`, triage-style workflows) where decorative citations bury real precedents. Skills whose citations serve as an audit trail (`/pour`, `/digest`) should disregard Rule 2; the other rules still apply.

### Rule 3 — Query hygiene: no identifiers or titles verbatim (mandatory)

When constructing a semantic search query from a known current focus, exclude:

- The focus's unique numeric identifier (e.g. `#116`, `issue-9999`)
- The focus's title verbatim
- Any other near-unique-token string that identifies the focus

```
# Bad — biases retrieval toward the focus's own KB entry
query = "issue #116 EOL dependencies detected"

# Good — symbols, concepts, affected paths
query = "ansible-core 2.18 Debian 12 EOL CI test matrix"
```

Unique numbers and titles are near-unique tokens that dominate semantic similarity at the embedding layer. Including them anchors the self-match at the top of results and crowds out actually-relevant prior entries. Use subsystem concepts, file paths, variable names, task names, and error messages instead.

### Rule 4 — Fabricated examples, never real test data (mandatory)

When a skill's prompt includes a worked example of correct output, the example must use fabricated data — hypothetical IDs (`#issue-9999`), made-up short-ids (`aaaaaaaa`), invented scenarios — never a real entry that could realistically show up in the wild.

In one round of the benchmark below a prompt's worked example used `#issue-116` (a real issue in the test set) with real citations (`#pr-93`, `#pr-114`) showing correct `cite-as-*` tags. When the model subsequently ran the triage for the real `#116`, its output was nearly identical to the example — copying the specific short-ids, justifications, and phrasing verbatim. That is pattern-matching against an answer key, not independent reasoning. Rewriting the example to use a fabricated `#issue-9999` and invented short-ids made the real output stop being identical to the example, and it continued to recover the correct citations via actual semantic search.

### Benchmark that produced these findings

Four-round benchmark comparing prompt variants for a triage workflow that uses `distillery_search` to retrieve prior issues and PRs as context, run on a separate repo's 13-issue test set against a 123-entry `jina-embeddings-v5-text-small` KB. Same issues, same model, same KB throughout — only the prompt changed between rounds.

| Round | Prompt pattern | Total citations | High-value recoveries | Self-refs | Format compliance |
|---|---|---|---|---|---|
| 1 | Loose rules, "cite what's relevant" | ~12 | 4/4 | 5/13 | 2/13 |
| 2 | Strict rule: "only cite if removing changes recommendation" | 6 | 0/4 | 0/13 | 13/13 |
| 3 | Enumerated cases: duplicate / precedent / decision | 1 | 1/4 | 0/13 | 13/13 |
| 4 | Mandatory visible KB analysis section + fabricated example | 29 | 4/4 | 0/13 | 13/13 |

Rounds 2 and 3 tightened rule language to reduce noise; they reduced noise but also reduced signal to the point where high-value citations disappeared. Round 4 replaced filter rules with a mandatory visible classification step and a fabricated example — signal recovered fully without reintroducing noise.

## MCP Health Check

Skills depend on the Distillery MCP server. Call `distillery_status()` at the start of the first skill invoked in a conversation. **If this check has already succeeded earlier in the same conversation, skip and proceed directly.**

If the check fails, display:

```
Warning: Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.
Setup: see docs/mcp-setup.md
```

Stop immediately if MCP is unavailable.

**Authentication errors** (HTTP transport with OAuth): If the health check returns an authentication error rather than a connection failure, direct the user to run `/setup` or complete the OAuth flow via the MCP server menu.

### Server Version Compatibility

Skills that require MCP tools added in a specific server version should declare `min_server_version` in their frontmatter. During the `distillery_status()` health check, compare the returned `version` field against `min_server_version`. If the server version is older, display:

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

## Forked Context Constraints

Skills with `context: fork` run in an isolated agent context with a restricted `allowed-tools` list. Due to platform limitations, the forked context may attempt to use tools outside its allowlist (such as Bash or Python) when an MCP tool call fails. To defend against this:

1. Every `context: fork` skill MUST include these two rules at the top of its `## Rules` section:
   - `NEVER use Bash, Python, or any tool not listed in allowed-tools`
   - `If an MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.`
2. The forked context must not attempt to work around MCP errors by shelling out, running scripts, or using any tool not declared in `allowed-tools`.
3. On any MCP tool failure, the skill must display the error per the Error Handling section below and halt immediately.

**Skills currently using `context: fork`:** `/pour`, `/radar`, `/digest`, `/investigate`, `/briefing`, `/gh-sync`.

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
| `/pour` | `pour/` | distillery_search, distillery_list | Multi-entry synthesis with citations and tag-based query expansion |
| `/bookmark` | `bookmark/` | distillery_store, distillery_find_similar | Save and annotate URLs |
| `/minutes` | `minutes/` | distillery_store, distillery_update, distillery_list | Record and update meeting notes |
| `/classify` | `classify/` | distillery_classify, distillery_list(output_mode=review), distillery_resolve_review | Classify and review entries |
| `/watch` | `watch/` | distillery_watch | Manage monitored feed sources + auto-poll scheduling (Claude Code routines) |
| `/radar` | `radar/` | distillery_search, distillery_list, distillery_store | Interest-driven feed digest and source suggestions |
| `/tune` | `tune/` | distillery_configure | Display and adjust feed relevance thresholds |
| `/setup` | `setup/` | distillery_list, distillery_watch | MCP connectivity wizard and transport configuration |
| `/digest` | `digest/` | distillery_list, distillery_search, distillery_store, distillery_find_similar | Generate structured summaries of internal team activity |
| `/gh-sync` | `gh-sync/` | distillery_store, distillery_get, distillery_update, distillery_list, distillery_relations | Sync GitHub issues and PRs into the knowledge base |
| `/investigate` | `investigate/` | distillery_search, distillery_get, distillery_relations, distillery_list | Deep context builder combining semantic search with relationship traversal |
| `/briefing` | `briefing/` | distillery_list, distillery_relations, distillery_search | Solo-first knowledge dashboard with optional team mode |

## Custom Agents

The `distillery-researcher` agent (`.claude/agents/distillery-researcher.md`) is pre-wired with all Distillery read tools and is invoked automatically for `/pour` and `/radar` workflows that require deep multi-pass retrieval or ambient digest synthesis.

---

**Document Version:** 2.5
**Last Updated:** 2026-04-21
