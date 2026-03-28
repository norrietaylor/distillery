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

## Author Identification

Skills must determine the author of stored entries. Use this priority order:

1. **git config user.name** — If the user has configured git with a name, use it
2. **DISTILLERY_AUTHOR environment variable** — If the env var is set, use it
3. **Ask the user** — Prompt: "What is your name (for author attribution)?" and cache the answer for the session

**Implementation Pattern (Pseudocode):**

```
author = git_config("user.name") or env("DISTILLERY_AUTHOR") or ask_user("Name for author attribution?")
# Cache author for remainder of session
```

**In SKILL.md:**
Include a step that determines the author, e.g.:

```markdown
### Step N: Determine Author

The skill will use your git config name if set, the `DISTILLERY_AUTHOR` environment variable if present, or ask you for a name.

If prompted, provide your first and last name (or team identifier).
```

## Project Identification

Skills must determine the project context. Use this priority order:

1. **Current git repository name** — Extract from `git rev-parse --show-toplevel`, convert to project name
2. **--project flag** — If skill arguments contain `--project <name>`, use that
3. **Ask the user** — Prompt: "What project is this for?" and cache for the session

**Implementation Pattern (Pseudocode):**

```
if "--project" in arguments:
    project = arguments["--project"]
else:
    project = git_repository_name() or ask_user("Project name?")
# Cache project for remainder of session
```

**In SKILL.md:**
Include a step that determines the project, e.g.:

```markdown
### Step N: Determine Project

The skill will extract the project name from the current git repository. If you want to override it, use the `--project <name>` flag, or the skill will ask you to confirm/specify the project.

Example: `/distill --project my-api` will record entries under the "my-api" project.
```

## MCP Unavailability Detection

Skills depend on the Distillery MCP server being configured and running. **Every skill must detect MCP unavailability and provide a helpful message.**

**Detection Method:**

Attempt to call a basic MCP tool (e.g., `distillery_status`) at the start of the skill. If the tool is unavailable or returns an error, display:

```
⚠️  Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrie-distillery/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

**In SKILL.md:**
Include a note about MCP setup:

```markdown
## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.
```

## Error Handling

MCP tools return responses in JSON format. Some responses include error information.

**Error Detection Pattern:**

If an MCP tool returns a response with `"error": true`, display the error clearly to the user:

```
❌ Error: <error message from MCP tool>

Suggested Action: <based on the error type>
- If "API key invalid" → Re-check the embedding provider API key
- If "Database error" → Ensure the database path is writable and the file exists
- If "No such entry" → Verify the entry ID and try a new search
```

**In SKILL.md:**
Include an error handling section in Rules:

```markdown
## Rules

- If an MCP tool returns an error, the skill displays the error message clearly and suggests next steps
- Common errors:
  - "Invalid API key" → Check your embedding provider credentials in DISTILLERY_CONFIG
  - "Entry not found" → Verify the entry ID or try a new search
```

## Tag Extraction

Skills that store entries (distill, bookmark, minutes) should extract tags from content.

**Pattern:**
- Auto-extract keywords from the entry content (2-5 most relevant words)
- Allow manual tag specification (e.g., `/bookmark url #tag1 #tag2`)
- Include tag list in stored metadata
- Tags are lowercase and hyphen-separated

**In SKILL.md:**
```markdown
### Step N: Tag Extraction

The skill automatically extracts relevant keywords as tags from the content. You can also provide explicit tags using the `#tag` syntax in arguments.

Example: `/bookmark https://example.com #caching #architecture` will add "caching" and "architecture" as explicit tags.
```

## Common MCP Tools Used by Skills

All skills use one or more of these tools:

| Tool | Used By | Purpose |
|------|---------|---------|
| `distillery_status` | All | Check server availability and database stats |
| `distillery_store` | distill, bookmark, minutes, radar | Store a new entry |
| `distillery_search` | recall, pour | Semantic search for entries |
| `distillery_find_similar` | distill, bookmark | Find duplicate/similar entries |
| `distillery_get` | (used for verification) | Retrieve a single entry by ID |
| `distillery_update` | minutes | Partially update an existing entry |
| `distillery_list` | minutes, radar | List entries with filtering |
| `distillery_suggest_sources` | radar | Suggest new feed sources based on interests |
| `distillery_watch` | watch | Manage monitored feed source registry |
| `distillery_poll` | (background) | Poll configured feed sources for new items |

**Error Response Format:**

All tools may return:
```json
{
  "error": true,
  "message": "Human-readable error description"
}
```

**Success Response Format (varies by tool):**
- `distillery_status`: `{ "status": "ok", "total_entries": 0, ... }`
- `distillery_store`: `{ "entry_id": "uuid", "status": "stored", ... }`
- `distillery_search`: `{ "results": [...], "total": N }`
- etc.

Check the tool's documentation in the MCP server for full response schema.

## Metadata Storage

When storing entries, skills include metadata that supports filtering and tracking:

**Common Metadata Fields:**

- `author` — Name of the person who created the entry
- `project` — Project or context for the entry
- `session_id` — (For `/distill`) Unique session identifier
- `meeting_id` — (For `/minutes`) Meeting identifier in format `<topic-slug>-YYYY-MM-DD`
- `url` — (For `/bookmark`) Original URL
- `summary` — (For `/bookmark`) Auto-generated summary
- `attendees` — (For `/minutes`) List of meeting attendees
- `version` — (For `/minutes`) Version number after each update

**Metadata Format:**
```json
{
  "author": "Alice Smith",
  "project": "distillery",
  "tags": ["api", "storage"],
  "session_id": "sess-2026-03-22-abc123",
  "custom_field": "value"
}
```

## Response Provenance

Skills that display search results (`/recall`, `/pour`) must include full provenance for each entry:

**Minimum Provenance Fields:**
- Entry ID (full UUID)
- Entry type badge (e.g., `[session]`, `[bookmark]`)
- Author name
- Created date (ISO format or relative, e.g., "2 days ago")
- Similarity score (as percentage, if from search)

**Format Example:**
```
ID: 550e8400-e29b-41d4-a716-446655440000 | Type: [session] | Author: Alice Smith | 2026-03-22 | Similarity: 87%
```

## Versioning and Updates

Skills that modify entries (`/minutes --update`) must:

1. Preserve the original content in full
2. Append new content below a timestamped heading
3. Increment a `version` counter
4. Provide the new version number in confirmation

**Update Format (stored as part of content):**
```markdown
# Meeting: standup

Original content here...

## Update — 2026-03-22 14:30:00 UTC

New notes appended here...

## Update — 2026-03-22 15:45:00 UTC

Additional notes...
```

## Consistency Rules

All skills must follow these rules for consistency:

1. **Case sensitivity** — Skill names are lowercase in code; user-facing prompts use Title Case
2. **Errors first** — If MCP is unavailable or an error occurs, report it immediately before proceeding
3. **Ask before proceeding** — If critical context (author, project, entry content) is unclear, ask the user rather than guessing
4. **Markdown output** — All output is markdown formatted (headers, tables, code blocks)
5. **No interactive loops without guard** — If a skill enters a retry loop, provide a max iteration count to prevent infinite loops
6. **Confirm actions** — Always confirm the result of store/update operations (entry ID, summary, etc.)

## Testing Conventions

Skills are tested via manual invocation in Claude Code with the Distillery MCP server connected.

**Manual Testing Pattern:**
1. Start Claude Code with Distillery MCP server configured
2. Invoke the skill: `/skill-name [arguments]`
3. Verify the result (check entry ID returned, search for the entry via `/recall`, etc.)
4. Confirm that no errors were raised

**Proof Artifacts:**
- File: `.claude/skills/<skill-name>/SKILL.md` exists
- Test: Manual invocation and verification of stored/retrieved entries
- Screenshots or text output showing successful execution

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
| `/watch` | `watch/` | distillery_watch | Manage monitored feed sources |
| `/radar` | `radar/` | distillery_list, distillery_suggest_sources, distillery_store | Ambient feed digest and source suggestions |
| `/tune` | `tune/` | distillery_status | Display and adjust feed relevance thresholds |

---

**Document Version:** 1.1
**Last Updated:** 2026-03-27
**Applies To:** All Distillery skills in `.claude/skills/<skill-name>/SKILL.md`
