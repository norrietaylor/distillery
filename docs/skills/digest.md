# /digest — Team Activity Summaries

Generates structured summaries of internal team knowledge activity over a configurable time window. Unlike `/radar` (which surfaces external feed signals), Digest focuses on what the team itself has captured — sessions, bookmarks, meeting notes, ideas, and references.

## Usage

```text
/digest
/digest --days 14
/digest --project distillery
/digest --store
```

**Trigger phrases:** "team digest", "activity summary", "what did the team capture", "weekly digest"

## When to Use

- Weekly or periodic team activity reviews
- Tracking knowledge growth across the team
- Scoping activity to a specific project
- Storing the summary as a knowledge entry for longitudinal tracking

## What It Does

1. **Retrieves entries** from the configured time window (default: 7 days)
2. **Groups by author and type** to show who captured what
3. **Identifies themes** across the activity using tag and content analysis
4. **Generates a structured summary** with sections for each author and cross-cutting themes
5. **Optionally stores** the digest as a `digest` entry for future reference

## Output Format

```text
Team Activity Digest (7 days)
Project: distillery

Authors: 3 active
  norrie: 12 entries (sessions, bookmarks)
  alex: 5 entries (minutes, references)
  sam: 3 entries (ideas, sessions)

Themes: DuckDB migration, auth refactor, feed scoring
New entries: 20 | Updated: 4

[Full narrative summary with per-author highlights]
```

## Options

| Flag | Description |
|------|-------------|
| `--days N` | Time window in days (default: 7) |
| `--project NAME` | Scope to a specific project |
| `--store` | Save the digest as a knowledge entry |

## Tips

- Combine with `/briefing` for a complete picture — `/briefing` shows current state, `/digest` shows recent activity
- Stored digests create a longitudinal record of team knowledge growth
- Use `--days 1` for a daily standup summary
