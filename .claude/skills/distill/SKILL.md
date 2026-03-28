---
name: distill
description: "Captures session knowledge and stores distilled decisions and insights. Triggered by: 'distill', 'capture this', 'save knowledge', 'log learnings', or '/distill [content]'."
---

# Distill — Session Knowledge Capture

Distill captures the decisions, architectural insights, and action items from a working session and stores them as a distilled knowledge entry in Distillery.

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- At the end of a productive session that produced decisions or insights worth preserving
- When asked to "capture this", "save knowledge", or "log learnings"
- When `/distill` is invoked, optionally with explicit content: `/distill "We decided to use DuckDB for local storage"`
- When `/distill --project <name>` is used to record knowledge under a specific project

## Process

### Step 1: Check MCP Availability

Call `distillery_status` to confirm the Distillery MCP server is running.

If the tool is unavailable or returns an error, display:

```
Warning: Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrie-distillery/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

Stop here if MCP is unavailable.

### Step 2: Determine Author

Determine the author for the stored entry using this priority order:

1. Run `git config user.name` — use the result if non-empty
2. Check the `DISTILLERY_AUTHOR` environment variable — use it if set
3. Ask the user: "What is your name (for author attribution)?"

Cache the author for the remainder of the session.

### Step 3: Determine Project

Determine the project context using this priority order:

1. If `--project <name>` was passed as an argument, use that value
2. Otherwise, run `git rev-parse --show-toplevel` to get the repository root, then extract the directory name as the project name
3. If neither is available, ask: "What project is this for?"

Cache the project for the remainder of the session.

Example: `/distill --project my-api` records entries under the "my-api" project.

### Step 4: Gather Content

**If explicit content was provided** (e.g., `/distill "We decided to use DuckDB"`), use that content directly.

**Otherwise, gather from the current session context:**

Collect and summarize:
- Project name and brief context
- Key decisions made during the session (with rationale)
- Architectural insights and design choices
- Action items and next steps
- Open questions or unresolved concerns
- Key files modified or created

If session context is unclear or thin, ask the user:

```
What should I capture from this session? For example:
- A specific decision or insight?
- Action items?
- Architectural notes?
```

Do not proceed without at least one concrete decision, insight, or action item.

### Step 5: Construct Distilled Summary

Synthesize the gathered content into a focused distilled summary. Follow these guidelines:

- **Lead with decisions**: State what was decided, not just what was discussed
- **Include rationale**: Why this decision was made (trade-offs, constraints)
- **Be concise**: Aim for dense, scannable content — not a raw transcript
- **Structure clearly**: Use short paragraphs or bullet points

Show the draft summary to the user before storing:

```
## Distilled Summary (preview)

[summary content here]

Ready to store? (yes / edit / skip)
```

If the user wants to edit, accept their revised version.

### Step 6: Check for Duplicates

Call `distillery_check_dedup` with the distilled content:

```
distillery_check_dedup(content="<distilled summary>")
```

This tool returns an `action` field that tells you what to do next:

**If `action` is `"create"`:**
No similar entries were found. Proceed directly to Step 7.

**If `action` is `"skip"`:**
The content is a near-exact duplicate. Display:

```
Near-duplicate detected (similarity: <highest_score * 100>%)

Reasoning: <reasoning from tool>

Similar entry:
| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| <id>     | <score%>  | <content_preview> |

How would you like to proceed?
1. Store anyway — save as a new entry
2. Skip — do not store this entry

Enter 1 or 2:
```

If the user chooses skip (2): Confirm "Skipped. No new entry was stored." and stop.
If the user chooses store anyway (1): Continue to Step 7.

**If `action` is `"merge"`:**
The content is very similar to an existing entry. Display:

```
Very similar entry found (similarity: <highest_score * 100>%)

Reasoning: <reasoning from tool>

Similar entries:
| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| <id>     | <score%>  | <content_preview> |

How would you like to proceed?
1. Store anyway — save as a new entry
2. Merge with existing — combine with the most similar entry
3. Skip — do not store this entry

Enter 1, 2, or 3:
```

If the user chooses merge (2):
- Combine the new summary with the most similar entry's content
- Call `distillery_update` with the entry ID and merged content
- Confirm: "Updated entry `<id>` with merged content."
- Stop here.

If the user chooses skip (3): Confirm "Skipped. No new entry was stored." and stop.
If the user chooses store anyway (1): Continue to Step 7.

**If `action` is `"link"`:**
The content is related but distinct. Display the similar entries and note that the new entry will be linked:

```
Related entries found (similarity: <highest_score * 100>%)

Reasoning: <reasoning from tool>

| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| <id>     | <score%>  | <content_preview> |

A new entry will be created and linked to these related entries.
Proceed? (yes / skip)
```

If the user chooses skip: Confirm "Skipped. No new entry was stored." and stop.
If yes: Continue to Step 7. When calling `distillery_store` (Step 8), include the related entry IDs in the metadata:
```
metadata={
  "session_id": "sess-<YYYY-MM-DD>-<short-random-id>",
  "related_entries": ["<id1>", "<id2>"]
}
```

### Step 7: Extract Tags

Automatically extract 2–5 relevant keywords from the distilled summary as tags.

Prefer hierarchical tags that reflect project context:

- Use `project/{repo-name}/sessions` as a base tag for the current project (e.g. `project/billing-v2/sessions`)
  - Sanitize repo names: convert to lowercase, replace underscores and dots with hyphens, remove any characters not matching `[a-z0-9-]`
- Use `project/{repo-name}/decisions` for decision entries
- Use `project/{repo-name}/architecture` for architectural insights
- Supplement with domain-specific tags (e.g. `domain/storage`, `domain/api-design`)
- Fall back to flat tags (e.g., `storage-decision`) only when no project context is available

Tag format rules:
- Tags are lowercase and hyphen-separated within each segment (e.g., `project/billing-v2/sessions`, `domain/api-design`)
- The user may also provide explicit tags via `#tag` syntax in the original invocation (e.g., `/distill #caching #architecture`)
- Explicit tags are merged with auto-extracted tags
- Strip any leading `#` characters from user-provided tags

### Step 8: Store Entry

Call `distillery_store` with:

```
distillery_store(
  content="<distilled summary>",
  entry_type="session",
  author="<determined in Step 2>",
  project="<determined in Step 3>",
  tags=["<tag1>", "<tag2>", ...],
  metadata={
    "session_id": "sess-<YYYY-MM-DD>-<short-random-id>"
  }
)
```

Generate `session_id` as a timestamp-based identifier (e.g., `sess-2026-03-22-a3f9`).

### Step 9: Confirm

Display the result to the user:

```
Stored as entry <entry-id> in project <project>

Summary:
<first 200 chars of distilled summary>...

Tags: <tag1>, <tag2>, ...
```

If an error is returned by `distillery_store`, display it clearly (see Rules below).

## Output Format

**Before storing** — preview panel:
```
## Distilled Summary (preview)
<summary text>
Ready to store? (yes / edit / skip)
```

**After storing** — confirmation:
```
Stored as entry <entry-id> in project <project>

Summary:
<first 200 chars of summary>...

Tags: tag1, tag2, tag3
```

**When duplicates found** — comparison table:
```
| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| abc-123  | 92%       | We decided to use DuckDB... |
```

**When skipped:**
```
Skipped. No new entry was stored.
```

**When merged:**
```
Updated entry <id> with merged content.
```

## Rules

- Never store raw session dumps — always distill to decisions, rationale, and insights
- Always show the distilled summary to the user before storing, so they can review and edit
- Always check for duplicates before storing using `distillery_check_dedup`
- Always respect the user's choice on duplicate handling (store / merge / skip)
- If session context is unclear, ask the user what to capture rather than guessing
- If MCP is unavailable, display the setup message and stop immediately
- If `distillery_store` or any MCP tool returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "API key invalid" → Re-check the embedding provider API key in your config
- If "Database error" → Ensure the database path is writable and the file exists
- If "No such entry" (on merge) → The entry may have been deleted; try storing anyway
```

- Do not enter infinite retry loops — if a store fails after one retry, report the error and stop
- Tags must be lowercase and hyphen-separated; strip any leading `#` characters from user-provided tags
- The `session_id` metadata field must be unique per invocation — use a timestamp with a short random suffix
