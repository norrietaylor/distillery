---
name: minutes
description: "Captures and manages meeting notes in the knowledge base. Triggered by: 'minutes', 'meeting notes', 'capture meeting', 'log meeting', '/minutes', '/minutes --update <meeting_id>', or '/minutes --list'."
---

# Minutes — Meeting Notes with Append Updates

Minutes captures structured meeting notes, stores them in the Distillery knowledge base, and supports appending updates to existing meeting records or listing recent meetings.

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- When you want to capture notes from a meeting or call
- When invoked via `/minutes` to start a new meeting record
- When invoked via `/minutes --update <meeting_id>` to append notes to an existing meeting
- When invoked via `/minutes --list` to view recent meetings
- When asked to "capture meeting", "log meeting", or "meeting notes"

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

### Step 2: Parse Mode

Inspect the invocation arguments to determine the operating mode:

- **No flags** or no arguments → **New Meeting Mode** (default)
- `--update <meeting_id>` → **Update Mode**
- `--list` → **List Mode**

Proceed to the corresponding section below.

---

## New Meeting Mode (default)

### Step 3a: Gather Meeting Details

Collect the following from the user interactively. Ask for all fields in a single prompt if context is sparse, or extract them from any content already provided in the invocation:

```
Please provide the following meeting details:

1. Meeting title/topic:
2. Attendees (names or identifiers, comma-separated):
3. Key discussion points:
4. Decisions made:
5. Action items (include owners where known, e.g. "Alice: set up DB by Friday"):
6. Follow-ups needed (optional):
```

Do not proceed without at least a title and one discussion point, decision, or action item.

### Step 4a: Generate meeting_id

Generate a `meeting_id` from today's date and the slugified meeting title:

- Slugify the title: lowercase, replace spaces and special characters with hyphens, collapse multiple hyphens
- Append the current date in `YYYY-MM-DD` format
- Format: `<slugified-title>-<YYYY-MM-DD>`

Examples:
- "Architecture Review" on 2026-03-22 → `arch-review-2026-03-22`
- "Daily Standup" on 2026-03-22 → `daily-standup-2026-03-22`
- "Q1 Retro" on 2026-03-22 → `q1-retro-2026-03-22`

### Step 5a: Format Meeting Notes

Compose the structured meeting notes content using the gathered information:

```markdown
# Meeting: <Title>

**Date:** <YYYY-MM-DD>
**Attendees:** <comma-separated list>
**Meeting ID:** <meeting_id>

## Discussion

<key discussion points, as bullet list or short paragraphs>

## Decisions

<decisions made, as bullet list>

## Action Items

<action items with owners and deadlines if known, as bullet list>

## Follow-ups

<follow-up items if any, or omit section if empty>
```

Show the formatted notes to the user before storing:

```
## Meeting Notes (preview)

<formatted content>

Ready to store? (yes / edit / skip)
```

If the user wants to edit, accept their revised version. If the user chooses skip:

```
Skipped. No meeting entry was stored.
```

### Step 6a: Determine Author

Determine the author for the stored entry using this priority order:

1. Run `git config user.name` — use the result if non-empty
2. Check the `DISTILLERY_AUTHOR` environment variable — use it if set
3. Ask the user: "What is your name (for author attribution)?"

Cache the author for the remainder of the session.

### Step 7a: Determine Project

Determine the project context using this priority order:

1. Run `git rev-parse --show-toplevel` to get the repository root, then extract the directory name as the project name
2. If no git repository is found, ask: "What project is this for?"

Cache the project for the remainder of the session.

### Step 8a: Extract Tags

Auto-extract 2–5 relevant keywords from the meeting content as tags. Tags must be lowercase and hyphen-separated (e.g., `architecture`, `action-items`, `q1-planning`).

### Step 9a: Store Entry

Call `distillery_store` with:

```
distillery_store(
  content="<formatted meeting notes>",
  entry_type="minutes",
  author="<determined in Step 6a>",
  project="<determined in Step 7a>",
  tags=["<tag1>", "<tag2>", ...],
  metadata={
    "meeting_id": "<generated meeting_id>",
    "attendees": ["<attendee1>", "<attendee2>", ...],
    "version": 1
  }
)
```

### Step 10a: Confirm

Display the result to the user:

```
Meeting notes stored.

Entry ID: <entry-id>
Meeting ID: <meeting_id>
Version: 1
Project: <project>

Preview:
<first 200 chars of formatted notes>...
```

If `distillery_store` returns an error, display it clearly (see Rules below).

---

## Update Mode (/minutes --update <meeting_id>)

### Step 3b: Find Existing Meeting

Call `distillery_search` with the `meeting_id` as the query and filter by `entry_type` "minutes":

```
distillery_search(
  query="<meeting_id>",
  entry_type="minutes",
  limit=5
)
```

Search through the results for an entry whose `metadata.meeting_id` exactly matches the provided `meeting_id`.

**If no match is found:**

```
No meeting found with ID: <meeting_id>

Would you like to create a new meeting entry instead? (yes / no)
```

If the user confirms yes, proceed with New Meeting Mode starting from Step 3a (using the `meeting_id` slug as the title hint).
If the user says no, confirm "No changes made." and stop.

**If a match is found**, continue to Step 4b.

### Step 4b: Gather Update Content

Display a brief summary of the existing meeting to orient the user:

```
Found meeting: <Title> (<meeting_id>)
Date: <original date>
Current version: <version>

What would you like to add? You can provide:
- Additional notes or context
- New decisions made since the last update
- Updated action items (new, resolved, or changed)
- Any corrections or clarifications
```

Collect the new content. Do not proceed without at least one meaningful addition.

### Step 5b: Compose Update

Append the new content to the existing entry's content under a timestamped heading:

```markdown
## Update — <YYYY-MM-DD HH:MM:SS UTC>

<new notes, decisions, action item updates, etc.>
```

The full updated content = original content + appended update section.

Show the appended section to the user before storing:

```
## Appending to <meeting_id>

## Update — <timestamp>

<new content>

Ready to append? (yes / edit / skip)
```

### Step 6b: Update Entry

Determine the new version number: `new_version = current_version + 1`.

Call `distillery_update` with:

```
distillery_update(
  entry_id="<entry-id from search>",
  content="<original content + appended update section>",
  metadata={
    "meeting_id": "<meeting_id>",
    "attendees": ["<original attendees>"],
    "version": <new_version>
  }
)
```

### Step 7b: Confirm

Display the result to the user:

```
Meeting notes updated.

Entry ID: <entry-id>
Meeting ID: <meeting_id>
Version: <new_version>

Appended:
<first 200 chars of the update section>...
```

If `distillery_update` returns an error, display it clearly (see Rules below).

---

## List Mode (/minutes --list)

### Step 3c: List Recent Meetings

Call `distillery_list` with:

```
distillery_list(
  entry_type="minutes",
  limit=10
)
```

### Step 4c: Display Results

If no meetings are found:

```
No meeting entries found in the knowledge base.

Use /minutes to capture your first meeting.
```

If meetings are found, display a compact table:

```
Recent Meetings (10 most recent):

| Meeting ID                   | Title                | Date       | Attendees |
|------------------------------|----------------------|------------|-----------|
| arch-review-2026-03-22       | Architecture Review  | 2026-03-22 | 4         |
| daily-standup-2026-03-22     | Daily Standup        | 2026-03-22 | 6         |
| q1-retro-2026-03-20          | Q1 Retro             | 2026-03-20 | 8         |
```

- **Meeting ID**: from `metadata.meeting_id`
- **Title**: extracted from the first `# Meeting:` heading in the content
- **Date**: extracted from the `**Date:**` field in the content or `created_at`
- **Attendees**: count of items in `metadata.attendees`

---

## Output Format

**New meeting — preview before storing:**
```
## Meeting Notes (preview)

# Meeting: Architecture Review

**Date:** 2026-03-22
**Attendees:** Alice, Bob, Carol
**Meeting ID:** arch-review-2026-03-22

## Discussion
...

Ready to store? (yes / edit / skip)
```

**New meeting — confirmation after storing:**
```
Meeting notes stored.

Entry ID: <entry-id>
Meeting ID: arch-review-2026-03-22
Version: 1
Project: distillery

Preview:
# Meeting: Architecture Review...
```

**Update — preview before appending:**
```
## Appending to arch-review-2026-03-22

## Update — 2026-03-22 15:30:00 UTC

New decision: deploy to staging by end of week.
Action items updated: Bob to provision the server.

Ready to append? (yes / edit / skip)
```

**Update — confirmation after updating:**
```
Meeting notes updated.

Entry ID: <entry-id>
Meeting ID: arch-review-2026-03-22
Version: 2

Appended:
## Update — 2026-03-22 15:30:00 UTC...
```

**List — recent meetings table:**
```
Recent Meetings (10 most recent):

| Meeting ID                   | Title                | Date       | Attendees |
|------------------------------|----------------------|------------|-----------|
| arch-review-2026-03-22       | Architecture Review  | 2026-03-22 | 4         |
```

**When meeting not found for update:**
```
No meeting found with ID: retro-2026-03-20

Would you like to create a new meeting entry instead? (yes / no)
```

**When skipped:**
```
Skipped. No meeting entry was stored.
```

## Rules

- `meeting_id` format is always `<slugified-title>-<YYYY-MM-DD>` — slugify by lowercasing and replacing non-alphanumeric characters with hyphens
- Updates always append under a `## Update — <timestamp>` heading; never overwrite the original content
- The `version` metadata field starts at 1 for new meetings and increments by 1 on each update
- Always show the formatted notes or the appended section to the user before storing or updating
- Always use `entry_type="minutes"` when calling `distillery_store` or filtering with `distillery_list`/`distillery_search`
- The `metadata.attendees` field must be a list of strings, not a comma-separated string
- Follow shared author/project determination patterns from CONVENTIONS.md
- If MCP is unavailable, display the setup message and stop immediately
- If `distillery_store`, `distillery_update`, or any MCP tool returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "API key invalid" -> Re-check the embedding provider API key in your config
- If "Database error" -> Ensure the database path is writable and the file exists
- If "No such entry" (on update) -> The entry may have been deleted; try creating a new meeting
- If "Connection error" -> Verify the Distillery MCP server is running
```

- Do not enter infinite retry loops — if a store or update fails after one retry, report the error and stop
- Omit the "Follow-ups" section from formatted notes if no follow-ups were provided
- Tags must be lowercase and hyphen-separated
- The `--update` flag requires a `meeting_id` argument; if omitted, ask: "Which meeting ID would you like to update?"
