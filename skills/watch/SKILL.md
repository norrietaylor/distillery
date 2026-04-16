---
name: watch
description: "Add, remove, or list monitored feed sources (RSS and GitHub)"
allowed-tools:
  - "mcp__*__distillery_watch"
  - "CronCreate"
  - "CronList"
  - "CronDelete"
  - "RemoteTrigger"
disable-model-invocation: true
effort: medium
---

<!-- Trigger phrases: watch, /watch list, /watch add <url>, /watch remove <url>, show my sources, add feed source, remove feed source -->

# Watch — Feed Source Registry

Lists, adds, and removes feed sources that Distillery monitors for ambient intelligence. Changes are persisted to the database and survive server restarts. Sources defined in `distillery.yaml` are seeded into the database on first startup.

## When to Use

- See registered feed sources (`/watch list`)
- Add a new feed source (`/watch add <url>`)
- Remove a feed source (`/watch remove <url>`)
- Natural language: "list my sources", "add a feed", "stop watching X", "remove source"

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

| Invocation pattern | Action | Extra args |
|--------------------|--------|------------|
| `/watch` or `/watch list` | `list` | none |
| `/watch add <url> [--type TYPE] [--label LABEL]` | `add` | url, optional source_type, label |
| `/watch remove <url> [--purge]` | `remove` | url, optional purge |

Default to `list` if no subcommand is recognizable.

For `add`, parse:
- **First non-flag argument**: source URL (required)
- **`--type TYPE`**: adapter type (default: `rss`). Valid: `rss`, `github`, `hackernews`, `webhook`
- **`--label LABEL`**: human-readable label (optional)
- **`--interval N`**: poll interval in minutes (default: 60)
- **`--trust N`**: trust weight in [0.0, 1.0] (default: 1.0)

If `add` is requested without a URL, ask the user before proceeding.

### Step 3: Execute Action

Call `distillery_watch` with the parsed arguments:

- **list**: `distillery_watch(action="list")`
- **add**: `distillery_watch(action="add", url=..., source_type=..., label=..., poll_interval_minutes=..., trust_weight=...)`
- **remove**: `distillery_watch(action="remove", url="<url>")` or `distillery_watch(action="remove", url="<url>", purge=true)` to also archive all historic entries from the source

- On MCP errors, see CONVENTIONS.md error handling — display and stop

### Step 4: Auto-Poll Schedule (after `add` only)

After a successful `add`, ensure automatic polling is configured. Never create duplicate poll jobs.

**4a. Determine scheduling mechanism:** Read `.mcp.json` in the project root:
- URL contains `localhost`, `127.0.0.1`, or transport is `stdio` → **local** → use `CronCreate`
- Remote host (e.g., `distillery-mcp.fly.dev`) → **deployed** → scheduling is handled by the GitHub Actions workflow at `.github/workflows/scheduler.yml`. Display: "Auto-poll managed by GitHub Actions (hourly at :23 UTC)." and skip to Step 5.

**4b. Local schedule check:**

Check `CronList` for a poll job whose prompt includes both:
- `distillery_watch(action='list')`
- `distillery_list(entry_type='feed'`
If found, skip to Step 5.

If no scheduled task exists, display:

```text
No auto-poll schedule found. Run /setup to configure scheduled tasks.
```

**4c. Cleanup on `remove`:** After a successful `remove`, if no sources remain, delete/pause the auto-poll schedule via `CronDelete` (local only). Display: "Auto-poll paused: no feed sources remaining."

### Step 5: Confirm

**Source table format (used for list and after add/remove):**

```text
Feed Sources (N configured)

| # | URL | Type | Label | Poll (min) | Trust |
|---|-----|------|-------|-----------|-------|
| 1 | https://example.com/rss | rss | Example | 60 | 1.0 |
```

If no sources: show "No feed sources configured." with usage hint.

- **After `add`**: show added source details, updated table, and auto-poll status
- **After `remove`**: confirm removal, show updated table. If `--purge` was used, also report the number of archived entries
- **After `remove --purge`**: "Removed source and archived N historic entries."

Changes are persisted to the database automatically — no manual YAML editing required.

## Rules

- Default subcommand is `list` when no arguments are provided
- Validate `source_type` is one of: `rss`, `github`, `hackernews`, `webhook`
- Do not proceed with `add` without a URL
- Always show the updated source table after `add` or `remove`
- After `add` on local transport, always check `CronList` before creating a schedule — no duplicates
- After `remove` that leaves zero sources on local transport, pause/delete the auto-poll schedule
- For hosted/team transport, scheduling is managed by GitHub Actions — do not create local cron jobs
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- Trust weight: 0.0–1.0 (default 1.0); poll interval: positive integer minutes (default 60)
