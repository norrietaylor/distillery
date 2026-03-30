---
name: watch
description: "Manages monitored feed sources in the Distillery source registry. Triggered by: 'watch', '/watch list', '/watch add <url>', '/watch remove <url>', 'show my sources', 'add feed source', 'remove feed source'."
---

# Watch — Feed Source Registry

Watch lists, adds, and removes the feed sources that Distillery monitors for ambient intelligence. Changes are persisted to the database and survive server restarts. Sources defined in `distillery.yaml` are seeded into the database on first startup.

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- When you want to see which feed sources are currently registered (`/watch list`)
- When you want to add a new feed source to monitor (`/watch add <url>`)
- When you want to remove a feed source (`/watch remove <url>`)
- When asked to "list my sources", "add a feed", "stop watching X", or "remove source"

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

### Step 2: Parse Arguments

Determine the subcommand and its arguments from the invocation:

| Invocation pattern | Action | Extra args |
|--------------------|--------|------------|
| `/watch` or `/watch list` | `list` | none |
| `/watch add <url> [--type TYPE] [--label LABEL]` | `add` | url, optional source_type, label |
| `/watch remove <url>` | `remove` | url |

If no subcommand is recognizable, default to `list`.

For the `add` subcommand, parse:
- **First non-flag argument**: the source URL (required)
- **`--type TYPE`** or `source_type=TYPE`: the adapter type (default: `rss`)
- **`--label LABEL`**: a human-readable label (optional)
- **`--interval N`**: poll interval in minutes (default: 60)
- **`--trust N`**: trust weight in [0.0, 1.0] (default: 1.0)

Valid source types are: `rss`, `github`, `hackernews`, `webhook`.

If the `add` action is requested but no URL is provided, ask the user:

```
Please provide the URL of the feed source to add:
>
```

Do not proceed without a URL.

### Step 3: Execute Action

Call `distillery_watch` with the parsed arguments.

**For `list`:**

```
distillery_watch(action="list")
```

**For `add`:**

```
distillery_watch(
  action="add",
  url="<url>",
  source_type="<type>",
  label="<label>",
  poll_interval_minutes=<N>,
  trust_weight=<W>
)
```

**For `remove`:**

```
distillery_watch(action="remove", url="<url>")
```

If the tool returns an error, display it clearly (see Rules below).

### Step 4: Ensure Auto-Poll Schedule (after `add` only)

After a successful `add` action, set up automatic polling so the user doesn't have to manually trigger `distillery_poll`. Only create the schedule if one doesn't already exist.

**4a. Check for existing schedule:**

Use `CronList` to check if a poll cron job already exists in this session. Look for any job whose prompt contains `distillery_poll`. If one already exists, skip to Step 5 — do not create a duplicate.

**4b. Determine scheduling mechanism:**

Read the `.mcp.json` file in the project root to determine the Distillery MCP server URL:

- If the URL contains `localhost`, `127.0.0.1`, or the transport is `stdio` → **local server** → use `CronCreate`
- If the URL is a remote host (e.g., `*.fastmcp.app`, any non-localhost domain) → **deployed server** → use `RemoteTrigger`

**4c. Create the schedule:**

**For local servers (CronCreate):**

```
CronCreate(
  cron="23 * * * *",
  prompt="Use distillery_poll to poll all configured feed sources. Report a one-line summary of items fetched and stored.",
  recurring=true,
  durable=true
)
```

- Pick an off-peak minute (not :00 or :30) to avoid fleet congestion
- Use `durable: true` so the job survives Claude Code restarts
- Note: durable cron jobs auto-expire after 7 days

Display:

```
Auto-poll scheduled: feeds will be polled every hour while Claude Code is active.
(Durable cron job — survives restarts, expires after 7 days.)
```

**For deployed servers (RemoteTrigger):**

```
RemoteTrigger(
  action="create",
  body={
    "name": "distillery-feed-poll",
    "description": "Poll all Distillery feed sources for new items",
    "schedule": "23 * * * *",
    "prompt": "Use distillery_poll to poll all configured feed sources. Report a one-line summary of items fetched and stored.",
    "max_turns": 3
  }
)
```

Display:

```
Auto-poll scheduled: feeds will be polled every hour via remote trigger.
Trigger ID: <trigger_id>
```

If `RemoteTrigger` fails (e.g., not authenticated), fall back to `CronCreate` and note the limitation:

```
Remote trigger unavailable — falling back to local cron.
Auto-poll scheduled: feeds will be polled every hour while Claude Code is active.
```

**4d. On `remove` — clean up schedule if no sources remain:**

After a successful `remove`, check the updated sources list. If it is now empty (no sources configured), delete the auto-poll schedule:

- For CronCreate: use `CronDelete` with the stored job ID
- For RemoteTrigger: use `RemoteTrigger(action="list")` to find the `distillery-feed-poll` trigger, then `RemoteTrigger(action="update", trigger_id=..., body={"paused": true})`

Display:

```
Auto-poll paused: no feed sources remaining.
```

### Step 5: Confirm

Display results based on the action performed.

**For `list`:** Display the source table (see Output Format).

**For `add`:** Display a confirmation with the newly added source details, then show the updated source table, then the auto-poll status from Step 4.

**For `remove`:** Confirm whether the source was found and removed, then show the updated source table.

Changes are persisted to the database automatically — no manual YAML editing required.

## Output Format

**Source table (list and after add/remove):**

```
Feed Sources (N configured)

| # | URL | Type | Label | Poll (min) | Trust |
|---|-----|------|-------|-----------|-------|
| 1 | https://news.ycombinator.com/rss | rss | Hacker News RSS | 60 | 1.0 |
| 2 | openai/openai-python | github | OpenAI Python SDK | 120 | 0.8 |
```

If there are no sources configured:

```
No feed sources configured.

Add a source with: /watch add <url> [--type rss|github|hackernews|webhook]
```

**After `add`:**

```
Added: <url>
  Type:     <source_type>
  Label:    <label or "(none)">
  Interval: <N> minutes
  Trust:    <weight>
```

**After `remove` (found):**

```
Removed: <url>
```

**After `remove` (not found):**

```
No source with URL "<url>" was found in the registry.
```

## Rules

- Always call `distillery_status` first to verify MCP availability
- Default subcommand is `list` when no arguments are provided
- When adding a source, validate `source_type` is one of: `rss`, `github`, `hackernews`, `webhook`
- Do not proceed with `add` without a URL; prompt the user if missing
- Always show the updated source table after `add` or `remove`
- **Auto-poll scheduling**: After a successful `add`, always check `CronList` before creating a new schedule — never create duplicate poll jobs
- **Schedule cleanup**: After a successful `remove` that leaves zero sources, pause or delete the auto-poll schedule
- **Scheduling fallback**: If `RemoteTrigger` fails for a deployed server, fall back to `CronCreate` gracefully
- If `distillery_watch` returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "INVALID_SOURCE_TYPE" -> Use one of: rss, github, hackernews, webhook
- If "MISSING_FIELD" -> Provide the required field (url or source_type)
- If "Connection error" -> Verify the Distillery MCP server is running
```

- Do not enter infinite retry loops — if a call fails, report the error and stop
- Trust weight must be between 0.0 and 1.0; default is 1.0
- Poll interval must be a positive integer (minutes); default is 60
