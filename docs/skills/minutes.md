# /minutes — Meeting Notes

Captures structured meeting notes, stores them in the knowledge base, and supports appending updates to existing meetings.

## Usage

```text
/minutes
/minutes --update standup-2026-03-22
/minutes --list
```

**Trigger phrases:** "meeting notes", "capture meeting", "log meeting"

## Modes

### New Meeting (default)

Creates a new meeting entry with structured sections.

You'll be asked for:

- **Title** — meeting name
- **Attendees** — who was there
- **Discussion** — main topics discussed
- **Decisions** — what was decided
- **Action items** — who does what by when

The entry is stored with a generated `meeting_id` in the format `<slugified-title>-<YYYY-MM-DD>` (e.g., `sprint-planning-2026-03-22`).

### Update Existing (`--update <meeting_id>`)

Appends new content to an existing meeting entry. Updates are timestamped and the version is incremented. Previous content is never overwritten.

```text
/minutes --update sprint-planning-2026-03-22
```

Each update is appended under a `## Update — <timestamp>` heading.

### List Recent (`--list`)

Displays a compact table of recent meetings:

```text
| Meeting ID                    | Title            | Date       | Attendees     |
|-------------------------------|------------------|------------|---------------|
| sprint-planning-2026-03-22    | Sprint Planning  | 2026-03-22 | alice, bob    |
| design-review-2026-03-20      | Design Review    | 2026-03-20 | alice, charlie|
```

## Output Format

```markdown
# Meeting: Sprint Planning

**Date:** 2026-03-22
**Attendees:** alice, bob, charlie
**Meeting ID:** sprint-planning-2026-03-22

## Discussion
- Reviewed the authentication implementation timeline
- Discussed caching strategy for the billing module

## Decisions
- Use Redis with a 15-minute TTL for session cache
- Ship auth MVP by end of sprint

## Action Items
- [ ] alice: Set up Redis cluster by Wednesday
- [ ] bob: Write integration tests for OAuth flow

## Follow-ups
- Schedule a deep-dive on multi-team RBAC next week
```

Empty sections are omitted.

## Tips

- Updates always **append** — they never overwrite existing content
- Version starts at 1 and increments with each update
- Attendees are stored as a list in metadata, not comma-separated text
- Tags are auto-extracted: `project/{repo}/meetings`, `meeting/{slugified-title}`
