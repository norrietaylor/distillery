---
name: setup
description: "Onboarding wizard for Distillery plugin — verifies MCP connectivity, detects transport, prompts for MCP connector registration, and configures auto-poll. Triggered by: 'setup', '/setup', 'configure distillery', 'set up distillery'."
---

# Setup — Distillery Onboarding

Setup walks you through first-time Distillery configuration: verifying MCP connectivity, detecting your transport mode, registering the MCP connector for remote polling, and optionally enabling auto-poll.

Run this once after installing the plugin. It is safe to run again at any time to verify or update your configuration.

## When to Use

- After installing the Distillery plugin for the first time
- When switching between local and hosted MCP transports
- When you want to enable remote auto-polling via scheduled triggers
- When `/watch add` reports "Remote trigger unavailable"
- When invoked via `/setup` or "configure distillery"

## Process

### Step 1: Check MCP Availability

Call `distillery_status` to confirm the Distillery MCP server is running.

If the tool is unavailable or returns an error, display:

```
Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrietaylor/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

Stop here if MCP is unavailable.

If connected, display:

```
MCP server connected.
  Database: <database_path>
  Entries:  <total_entries>
  Model:    <embedding_model> (<embedding_dimensions>d)
```

### Step 2: Detect Transport Mode

Read the `.mcp.json` file in the project root (or `~/.claude/settings.json` if `.mcp.json` does not exist) to determine the Distillery MCP server configuration.

Classify the transport:

| URL Pattern | Transport | Mode |
|-------------|-----------|------|
| `localhost`, `127.0.0.1`, or `type: "stdio"` | Local | `local` |
| `*.fastmcp.app/*` | Hosted demo | `hosted` |
| Any other remote domain | Team HTTP | `team` |

Display:

```
Transport: <Local | Hosted | Team HTTP>
URL: <server URL or "stdio">
```

### Step 3: Check Feed Sources

Call `distillery_watch(action="list")` to see if any feed sources are configured.

Display:

```
Feed sources: <N> configured
```

If sources exist, list them briefly (URL + label).

### Step 4: MCP Connector Registration (hosted/team only)

**Skip this step if transport is `local`.**

For hosted or team HTTP transports, the user needs an MCP connector registered at claude.ai to enable remote auto-polling via scheduled triggers. Check if one is already set up:

Call `RemoteTrigger(action="list")` to see if any triggers with MCP connections to the Distillery server already exist.

**If a matching trigger exists:**

```
Remote polling: configured
  Trigger: <trigger_name> (<trigger_id>)
  Schedule: <cron_expression>
  Status: <enabled|disabled>
```

Skip to Step 6.

**If no matching trigger exists, prompt the user:**

```
Remote Auto-Poll Setup

To enable automatic feed polling when you're not in Claude Code,
you need to register the Distillery MCP server as a connector:

1. Open: https://claude.ai/settings/connectors
2. Click "Add connector"
3. Enter URL: <server URL from Step 2>
4. Name it: distillery
5. Save

Once saved, run /setup again and I'll create the scheduled trigger.

Skip this step? Auto-poll will fall back to local cron (only runs
while Claude Code is active). (yes / no)
```

If the user says yes (skip), note the limitation and continue to Step 5.

If the user says no (they'll register), stop here with:

```
After registering the connector at claude.ai, run /setup again to complete configuration.
```

### Step 5: Auto-Poll Configuration

Check `CronList` for any existing poll jobs.

**If a poll job exists:**

```
Auto-poll: active (cron job <job_id>, every hour at :<minute>)
```

**If no poll job exists and feed sources are configured (from Step 3):**

Ask the user:

```
Enable auto-poll? Feeds will be polled every hour while Claude Code is active.
(yes / no)
```

If yes, create the cron job:

```
CronCreate(
  cron="<random off-peak minute> * * * *",
  prompt="Use distillery_poll to poll all configured feed sources. Report a one-line summary of items fetched and stored.",
  recurring=true,
  durable=true
)
```

Display:

```
Auto-poll enabled: every hour at :<minute> (cron job <job_id>)
```

**If no feed sources are configured:**

```
Auto-poll: skipped (no feed sources configured)
  Add sources with /watch add <url> — auto-poll will be set up automatically.
```

### Step 6: Create Remote Trigger (hosted/team with connector)

**Only reach this step if:**
- Transport is hosted or team HTTP
- User has registered the MCP connector (from Step 4)
- No existing trigger found

Call `RemoteTrigger(action="list")` to check for the distillery connector UUID. If a connector is available, create the trigger:

```
RemoteTrigger(
  action="create",
  body={
    "name": "distillery-feed-poll",
    "cron_expression": "23 * * * *",
    "enabled": true,
    "job_config": {
      "ccr": {
        "environment_id": "<environment_id from available environments>",
        "session_context": {
          "model": "claude-sonnet-4-6",
          "sources": [
            {"git_repository": {"url": "https://github.com/norrietaylor/distillery"}}
          ],
          "allowed_tools": ["Bash", "Read", "Glob", "Grep"]
        },
        "events": [
          {"data": {
            "uuid": "<generate fresh v4 UUID>",
            "session_id": "",
            "type": "user",
            "parent_tool_use_id": null,
            "message": {
              "content": "Use distillery_poll to poll all configured feed sources. Report a one-line summary of items fetched and stored.",
              "role": "user"
            }
          }}
        ]
      }
    },
    "mcp_connections": [
      {
        "connector_uuid": "<uuid from claude.ai>",
        "name": "distillery",
        "url": "<server URL>"
      }
    ]
  }
)
```

Display:

```
Remote trigger created: distillery-feed-poll
  Schedule: every hour at :23 (UTC)
  Trigger ID: <trigger_id>
  Manage at: https://claude.ai/code/scheduled/<trigger_id>
```

### Step 7: Summary

Display the full configuration summary:

```
Distillery Setup Complete

  MCP Server:    <connected>
  Transport:     <Local | Hosted | Team HTTP>
  Database:      <database_path>
  Entries:       <total_entries>
  Feed Sources:  <N> configured
  Auto-Poll:     <active (cron) | active (remote trigger) | inactive>

Available skills:
  /distill   — capture knowledge      /recall   — search knowledge
  /bookmark  — save URLs              /pour     — synthesize topics
  /minutes   — meeting notes          /classify — triage entries
  /watch     — manage feed sources    /radar    — feed digest
  /tune      — adjust thresholds

Run /watch add <url> to start monitoring feeds.
```

## Output Format

The setup wizard uses a sequential, conversational format. Each step prints its result before proceeding to the next. The final summary is always shown.

## Rules

- Always start by checking MCP availability — stop immediately if unavailable
- Never create duplicate cron jobs — always check `CronList` first
- Never create duplicate remote triggers — always check `RemoteTrigger(action="list")` first
- For remote trigger creation, use the exact `job_config` schema documented in Step 6
- Pick an off-peak cron minute (not :00 or :30) for auto-poll schedules
- If the user has no feed sources, skip auto-poll setup but explain how to enable it later
- If `RemoteTrigger` calls fail, fall back gracefully and explain the limitation
- This skill is idempotent — running it multiple times should not create duplicates
- Always show the final summary regardless of which steps were skipped
