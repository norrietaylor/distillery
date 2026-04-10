---
name: distill
description: "Capture decisions, insights, and action items from the current session into the knowledge base"
allowed-tools:
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_find_similar"
  - "mcp__*__distillery_update"
  - "Bash(git config *)"
disable-model-invocation: true
effort: medium
---

<!-- Trigger phrases: distill, capture this, save knowledge, log learnings, /distill [content] -->

# Distill — Session Knowledge Capture

Distill captures decisions, architectural insights, and action items from a working session and stores them as knowledge entries in Distillery.

## When to Use

- At the end of a productive session with decisions or insights worth preserving
- When asked to "capture this", "save knowledge", or "log learnings"
- When `/distill` is invoked, optionally with content: `/distill "We decided to use DuckDB for local storage"`
- When `/distill --project <name>` targets a specific project

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Determine Author & Project

See CONVENTIONS.md for resolution order. Cache for the session.

### Step 3: Gather Content

**If explicit content was provided** (e.g., `/distill "We decided to use DuckDB"`), use it directly.

**Otherwise, gather from the current session context:**

- Key decisions made (with rationale)
- Architectural insights and design choices
- Action items and next steps
- Open questions or unresolved concerns
- Key files modified or created

If session context is thin, ask what to capture. Do not proceed without at least one concrete decision, insight, or action item.

### Step 4: Construct Distilled Summary

Synthesize gathered content into a focused summary:

- **Lead with decisions**: State what was decided, not what was discussed
- **Include rationale**: Trade-offs and constraints behind decisions
- **Be concise**: Dense, scannable content — not a transcript
- **Structure clearly**: Short paragraphs or bullet points

Show the draft to the user before storing:

```
## Distilled Summary (preview)
[summary content]
Ready to store? (yes / edit / skip)
```

Accept revisions if the user wants to edit.

### Step 5: Check for Duplicates

Call `distillery_find_similar(content="<distilled summary>", dedup_action=true)`. Handle by `action` field:

**`"create"`:** No similar entries. Proceed to Step 6.

**`"skip"`:** Near-exact duplicate. Show similarity table and offer: (1) Store anyway, (2) Skip. Display table format:

```
| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| <id>     | <score%>  | <content_preview> |
```

**`"merge"`:** Very similar entry exists. Show similarity table and offer: (1) Store anyway, (2) Merge with existing, (3) Skip.

For merge: combine new summary with the most similar entry's content, call `distillery_update` with the entry ID and merged content, confirm and stop.

**`"link"`:** Related but distinct. Show similarity table, note new entry will be linked. Ask to proceed or skip. If proceeding, include `"related_entries": ["<id1>", ...]` in metadata at Step 7.

For skip in any case: confirm "Skipped. No new entry was stored." and stop.

### Step 6: Extract Tags

Auto-extract 2-5 keywords from the summary. Prefer hierarchical tags:

- `project/{repo-name}/sessions` as base tag for the current project
- `project/{repo-name}/decisions` for decision entries
- `project/{repo-name}/architecture` for architectural insights
- `domain/{topic}` for domain-specific tags (e.g., `domain/storage`, `domain/api-design`)
- Fall back to flat tags only when no project context is available

Repo name sanitization: lowercase, replace non-`[a-z0-9-]` chars with hyphens, collapse consecutive hyphens, trim leading/trailing hyphens, prefix with `repo-` if result doesn't start with `[a-z0-9]`. Final segment must match `[a-z0-9][a-z0-9\-]*`.

Merge with any explicit `#tag` arguments (strip leading `#`). Tags are lowercase, hyphen-separated within segments.

### Step 7: Store Entry

Call `distillery_store` with:

```
distillery_store(
  content="<distilled summary>",
  entry_type="session",
  author="<from Step 2>",
  project="<from Step 2>",
  tags=["<tag1>", "<tag2>", ...],
  metadata={"session_id": "sess-<YYYY-MM-DD>-<short-random-id>"}
)
```

The `session_id` must be unique per invocation (timestamp + short random suffix).

### Step 8: Confirm

```
[session] Stored: <entry-id>
Project: <project> | Author: <author>
Summary: <first 200 chars>...
Tags: tag1, tag2, tag3
```

## Output Format

**Preview** (before storing):
```
## Distilled Summary (preview)
<summary text>
Ready to store? (yes / edit / skip)
```

**Confirmation** (after storing):
```
[session] Stored: <entry-id>
Project: <project> | Author: <author>
Summary: <first 200 chars>...
Tags: tag1, tag2, tag3
```

**Duplicate comparison table:**
```
| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| abc-123  | 92%       | We decided to use DuckDB... |
```

## Rules

- Never store raw session dumps — always distill to decisions, rationale, and insights
- Always show the summary to the user before storing for review/edit
- Always check for duplicates before storing using `distillery_find_similar(dedup_action=true)`
- Always respect the user's choice on duplicate handling (store / merge / skip)
- If session context is unclear, ask what to capture rather than guessing
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- Do not enter retry loops — if a store fails after one attempt, report and stop
- Tags must be lowercase and hyphen-separated; strip leading `#` from user-provided tags
- The `session_id` metadata field must be unique per invocation
