# Distillery Skills — Shared Conventions

This document establishes the common patterns and conventions used by all Distillery skills (`/distill`, `/recall`, `/pour`, `/bookmark`, `/minutes`).

## SKILL.md Structure

All skills follow the same structure for consistency and clarity:

```yaml
---
name: <skill-name>
description: "Description of the skill's purpose and trigger phrases (case-insensitive: e.g., 'use when user says ...', 'triggered by ...')"
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

Skills depend on the Distillery MCP server. Call `distillery_status` at the start of the first skill invoked in a conversation. **If `distillery_status` has already succeeded earlier in the same conversation, skip the check and proceed directly.**

If the check fails, display:

```
Warning: Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.
Setup: see docs/mcp-setup.md
```

Stop immediately if MCP is unavailable.

**Authentication errors** (HTTP transport with OAuth): If `distillery_status` returns an authentication error rather than a connection failure, direct the user to run `/setup` or complete the OAuth flow via the MCP server menu.

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

## Consistency Rules

1. Errors first — report and stop before proceeding
2. Ask before proceeding if critical context is unclear
3. Markdown output (headers, tables, code blocks)
4. No retry loops — if a tool fails, report and stop
5. Confirm store/update operations with entry ID and summary

## Skills Registry

The following skills are available in `.claude/skills/`:

| Skill | Directory | Primary MCP Tools | Purpose |
|-------|-----------|-------------------|---------|
| `/distill` | `distill/` | distillery_store, distillery_find_similar | Capture knowledge from conversations |
| `/recall` | `recall/` | distillery_search | Semantic search over the knowledge base |
| `/pour` | `pour/` | distillery_search | Multi-entry synthesis with citations |
| `/bookmark` | `bookmark/` | distillery_store, distillery_find_similar | Save and annotate URLs |
| `/minutes` | `minutes/` | distillery_store, distillery_update, distillery_list | Record and update meeting notes |
| `/classify` | `classify/` | distillery_classify, distillery_review_queue, distillery_resolve_review | Classify and review entries |
| `/watch` | `watch/` | distillery_watch | Manage monitored feed sources + auto-poll scheduling (CronCreate local; GitHub Actions for hosted) |
| `/radar` | `radar/` | distillery_list, distillery_suggest_sources, distillery_store | Ambient feed digest and source suggestions |
| `/tune` | `tune/` | distillery_status | Display and adjust feed relevance thresholds |

---

**Document Version:** 2.0
**Last Updated:** 2026-03-29
