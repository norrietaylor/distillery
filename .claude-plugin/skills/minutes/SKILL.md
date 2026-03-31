---
name: minutes
description: "Captures and manages meeting notes in the knowledge base. Triggered by: 'minutes', 'meeting notes', 'capture meeting', 'log meeting', '/minutes', '/minutes --update <meeting_id>', or '/minutes --list'."
---

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

Display: entry ID, meeting ID, version (1), project, and first 200 chars of notes.

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

Display: entry ID, meeting ID, new version, and first 200 chars of the update section.

---

## List Mode (/minutes --list)

### Step 3c: List Recent Meetings

```python
distillery_list(entry_type="minutes", limit=10)
```

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
