---
name: minutes
description: "Capture meeting notes or append updates to an existing meeting record"
allowed-tools:
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_find_similar"
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_update"
  - "mcp__*__distillery_list"
disable-model-invocation: true
effort: medium
---

<!-- Trigger phrases: minutes, meeting notes, capture meeting, log meeting, /minutes, /minutes --update <meeting_id>, /minutes --list -->

# Minutes — Meeting Notes with Append Updates

Minutes captures structured meeting notes, stores them in the Distillery knowledge base, and supports appending updates or listing recent meetings.

## When to Use

- Capture notes from a meeting or call (`/minutes`)
- Append notes to an existing meeting (`/minutes --update <meeting_id>`)
- View recent meetings (`/minutes --list`)

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Mode

- **No flags** → **New Meeting Mode** (default)
- `--update <meeting_id>` → **Update Mode**
- `--list` → **List Mode**

**Optional flags (all modes):**

| Flag | Parameter | Description |
|------|-----------|-------------|
| `--project` | `<name>` | Filter by project name (used in List Mode to scope results) |

---

## New Meeting Mode (default)

### Step 3a: Gather Meeting Details

Collect from the user (or extract from invocation context): title/topic, attendees, key discussion points, decisions, action items (with owners), and optional follow-ups. Require at least a title and one discussion point, decision, or action item.

### Step 4a: Generate meeting_id

Format: `<slugified-title>-<YYYY-MM-DD>` — lowercase, replace non-alphanumeric with hyphens, collapse multiples.

Examples: "Architecture Review" on 2026-03-22 → `arch-review-2026-03-22`, "Daily Standup" → `daily-standup-2026-03-22`

### Step 5a: Format and Preview

Compose structured notes:

```markdown
# Meeting: <Title>

**Date:** <YYYY-MM-DD>
**Attendees:** <comma-separated list>
**Meeting ID:** <meeting_id>

## Discussion
<bullet list or short paragraphs>

## Decisions
<bullet list>

## Action Items
<bullet list with owners/deadlines>

## Follow-ups
<if any — omit section if empty>
```

Show preview and ask: `Ready to store? (yes / edit / skip)`. If skip: "Skipped. No meeting entry was stored."

### Step 6a: Author, Project, Tags

Determine author & project per CONVENTIONS.md. Auto-extract 2-5 lowercase, hyphen-separated tags from the content.

### Step 6.5: Check for Duplicates

First, check for an existing meeting with the same `meeting_id`:

```python
distillery_search(query="<meeting_id>", entry_type="minutes", limit=5)
```

If any result has `metadata.meeting_id == <meeting_id>`, treat this as a duplicate meeting record. Display:

```
A meeting entry with ID "<meeting_id>" already exists (entry <entry-id>).
Use /minutes --update <meeting_id> to append new content instead.
Proceed anyway? (yes / skip)
```

If user chooses skip: "Skipped. No new entry was stored." and stop.

If no `meeting_id` match found, call `distillery_find_similar(content="<meeting notes summary>", dedup_action=True)`. Handle by `action` field:

**`"create"`:** No similar entries. Proceed to Step 7a.

**`"skip"`:** Near-exact duplicate. Show similarity table and offer: (1) Store anyway, (2) Skip.

**`"merge"`:** Very similar entry exists. Show similarity table and offer: (1) Store anyway, (2) Merge with existing, (3) Skip.

For merge: combine new notes with the most similar entry's content, call `distillery_update` with the entry ID and merged content, confirm and stop.

**`"link"`:** Related but distinct. Show similarity table, note new entry will be linked. Ask to proceed or skip. If proceeding, include `"related_entries": ["<id1>", ...]` in metadata at Step 7a.

```
Similar entries found:

| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| <id>     | <score%>  | <content_preview> |
```

On skip in any case: "Skipped. No new entry was stored." and stop.

### Step 7a: Store Entry

```python
distillery_store(
  content="<formatted notes>",
  entry_type="minutes",
  author="<author>",
  project="<project>",
  tags=[...],
  metadata={
    "meeting_id": "<meeting_id>",
    "attendees": ["<attendee1>", ...],
    "version": 1
  }
)
```

- On MCP errors, see CONVENTIONS.md error handling — display and stop.

### Step 8a: Confirm

```
[minutes] Stored: <entry-id>
Project: <project> | Author: <author>
Summary: <first 200 chars of notes>...
Tags: tag1, tag2, tag3
```

---

## Update Mode (/minutes --update <meeting_id>)

### Step 3b: Find Existing Meeting

```python
distillery_search(query="<meeting_id>", entry_type="minutes", limit=5)
```

Match on `metadata.meeting_id`. If no match: offer to create a new meeting instead, or stop with "No changes made." The `--update` flag requires a `meeting_id`; if omitted, ask which meeting to update.

### Step 4b: Gather Update Content

Show a brief summary of the existing meeting (title, date, version). Collect new notes, decisions, action item updates, or corrections. Require at least one meaningful addition.

### Step 5b: Compose and Preview Update

Append under a timestamped heading (never overwrite original):

```markdown
## Update — <YYYY-MM-DD HH:MM:SS UTC>

<new content>
```

Show the appended section and ask: `Ready to append? (yes / edit / skip)`

### Step 6b: Update Entry

Set `new_version = current_version + 1`. Call `distillery_update` with the full content (original + appended section) and updated metadata including the new version.

- On MCP errors, see CONVENTIONS.md error handling — display and stop.

### Step 7b: Confirm

```
[minutes] Stored: <entry-id>
Project: <project> | Author: <author>
Summary: <first 200 chars of update section>...
Tags: tag1, tag2, tag3
```

---

## List Mode (/minutes --list)

### Step 3c: List Recent Meetings

```python
distillery_list(entry_type="minutes", limit=10, output_mode="full")
```

If `--project` was specified, also pass `project=<name>` to scope results to that project.

If none found: "No meeting entries found. Use /minutes to capture your first meeting."

Otherwise display a compact table:

```text
Recent Meetings (10 most recent):

| Meeting ID                   | Title                | Date       | Attendees |
|------------------------------|----------------------|------------|-----------|
| arch-review-2026-03-22       | Architecture Review  | 2026-03-22 | 4         |
```

Columns: `metadata.meeting_id`, title from `# Meeting:` heading, date from content or `created_at`, count of `metadata.attendees`.

---

## Rules

- `meeting_id` format: `<slugified-title>-<YYYY-MM-DD>`
- Updates always append under `## Update — <timestamp>`; never overwrite original content
- `version` starts at 1, increments by 1 on each update
- Always preview notes/updates before storing
- Always use `entry_type="minutes"` for store/list/search calls
- `metadata.attendees` must be a list of strings, not comma-separated
- Tags must be lowercase and hyphen-separated
- Follow shared author/project/error patterns from CONVENTIONS.md
- No retry loops — if a tool fails after one attempt, report and stop
