---
name: watch
description: "Manages monitored feed sources in the Distillery source registry. Triggered by: 'watch', '/watch list', '/watch add <url>', '/watch remove <url>', 'show my sources', 'add feed source', 'remove feed source'."
---

# Watch — Feed Source Registry

Watch lists, adds, and removes the feed sources that Distillery monitors for ambient intelligence. Changes are applied to the in-memory source registry for the current session; to persist them, update the `feeds.sources` section of `distillery.yaml`.

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

### Step 4: Confirm

Display results based on the action performed.

**For `list`:** Display the source table (see Output Format).

**For `add`:** Display a confirmation with the newly added source details, then show the updated source table.

**For `remove`:** Confirm whether the source was found and removed, then show the updated source table.

Always include the persistence reminder when changes are made:

```
Note: Changes are applied to the current session only.
To persist across restarts, update the feeds.sources section of distillery.yaml.
```

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

Note: Changes are applied to the current session only.
To persist across restarts, update the feeds.sources section of distillery.yaml.
```

**After `remove` (found):**

```
Removed: <url>

Note: Changes are applied to the current session only.
To persist across restarts, update the feeds.sources section of distillery.yaml.
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
- Always include the persistence reminder when changes are made
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
