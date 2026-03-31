# /watch — Feed Source Management

Manages the feed sources that Distillery monitors for ambient intelligence. Sources are polled periodically and scored for relevance.

## Usage

```
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

```
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

After adding a source, the skill offers to configure auto-poll scheduling:

- **Local transport** — creates a recurring cron job via `CronCreate` (a Claude Code platform primitive)
- **Hosted/team transport** — creates a remote trigger via `RemoteTrigger` (a Claude Code platform primitive)

### Remove

Removes a source by URL. If no sources remain after removal, the auto-poll schedule is paused.

## Source Types

| Type | What it monitors |
|------|-----------------|
| `github` | Repository events via GitHub REST API |
| `rss` | RSS/Atom feed entries |

## Tips

- Use `/watch` regularly to review your monitored sources
- Trust weight affects how relevance scores are weighted in the digest
- Auto-poll checks for existing schedules before creating duplicates
- Removing the last source automatically pauses the poll schedule
