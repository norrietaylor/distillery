# /watch — Feed Source Management

Manages the feed sources that Distillery monitors for ambient intelligence. Sources are polled periodically and scored for relevance.

## Usage

```text
/watch                                          # List all sources
/watch list                                     # List all sources
/watch add https://github.com/duckdb/duckdb     # Add a GitHub source
/watch add https://blog.example.com/feed.xml --type rss --label "Tech Blog"
/watch remove https://github.com/duckdb/duckdb  # Remove a source
```

**Trigger phrases:** "show my sources", "add feed source", "remove feed source"

## Actions

### List (default)

Displays all configured feed sources:

```text
## Feed Sources (3 configured)

| # | URL | Type | Label | Poll (min) | Trust |
|---|-----|------|-------|------------|-------|
| 1 | github.com/duckdb/duckdb | github | DuckDB | 60 | 1.0 |
| 2 | blog.example.com/feed.xml | rss | Tech Blog | 120 | 0.8 |
| 3 | github.com/anthropics/claude-code | github | Claude Code | 60 | 1.0 |
```

### Add

Adds a new feed source and optionally configures auto-poll scheduling.

| Option | Description | Default |
|--------|-------------|---------|
| URL (required) | The feed URL to monitor | — |
| `--type <type>` | Source type: `rss`, `github` | Auto-detected |
| `--label <name>` | Human-readable label | URL-derived |
| `--interval <minutes>` | Poll interval in minutes | 60 |
| `--trust <weight>` | Trust weight 0.0-1.0 | 1.0 |

After adding a source, the skill configures auto-poll scheduling:

- **Local transport** — creates a recurring cron job via `CronCreate` (a Claude Code platform primitive)
- **Hosted/team transport** — scheduling is handled by the GitHub Actions workflow (`.github/workflows/scheduler.yml`) which calls the `/api/poll` webhook endpoint hourly. No local cron needed.

### Remove

Removes a source by URL. If no sources remain after removal and transport is local, the auto-poll cron schedule is paused.

## Source Types

| Type | What it monitors |
|------|-----------------|
| `github` | Repository events via GitHub REST API |
| `rss` | RSS/Atom feed entries |

## Tips

- Use `/watch` regularly to review your monitored sources
- Trust weight affects how relevance scores are weighted in the digest
- Auto-poll checks for existing schedules before creating duplicates
- Removing the last source automatically pauses the local poll schedule
