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

If the tool is unavailable or returns an error, display the error message and the setup summary (Step 6) with `MCP Server: not connected`. Do not proceed with Steps 2-5.

```text
Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrietaylor/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

Then skip to Step 6 (Summary) with `MCP Server: not connected`.

If connected, display using the actual fields from `distillery_status`:

```text
MCP server connected.
  Entries:  <total_entries>
  Model:    <embedding_model>
  DB Size:  <database_size_bytes / 1048576> MB
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

```text
Transport: <Local | Hosted | Team HTTP>
URL: <server URL or "stdio">
```

### Step 3: Check Feed Sources

Call `distillery_watch(action="list")` to see if any feed sources are configured.

Display:

```text
Feed sources: <N> configured
```

If sources exist, list them briefly (URL + label).

### Step 4: MCP Connector Registration (hosted/team only)

**Skip this step if transport is `local`.** Proceed directly to Step 5.

For hosted or team HTTP transports, the user needs an MCP connector registered at claude.ai to enable remote auto-polling via scheduled triggers.

**4a. Check for existing trigger:**

Call `RemoteTrigger(action="list")` to see if any triggers with MCP connections to the Distillery server already exist.

**If a matching trigger exists:**

```text
Remote polling: configured
  Trigger: <trigger_name> (<trigger_id>)
  Schedule: <cron_expression>
  Status: <enabled|disabled>
```

Skip to Step 6 (Summary) — remote polling is already set up.

**If no matching trigger exists, check connector availability:**

The connector UUID is needed to create a remote trigger. Since connectors must be registered via the claude.ai web UI, prompt the user:

```text
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

If the user says no (they'll register), display the summary (Step 6) noting remote polling is pending, then stop:

```text
After registering the connector at claude.ai, run /setup again to complete configuration.
```

### Step 5: Auto-Poll Configuration

**5a. Remote trigger creation (hosted/team with connector):**

If transport is hosted or team HTTP, and the user has registered the MCP connector (confirmed via `RemoteTrigger(action="list")` returning a connector UUID), and no existing trigger was found in Step 4a, create the remote trigger:

```json
{
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
        "allowed_tools": ["Bash", "Read", "Glob", "Grep", "mcp__distillery__distillery_poll"]
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
```

Display:

```text
Remote trigger created: distillery-feed-poll
  Schedule: every hour at :23 (UTC)
  Trigger ID: <trigger_id>
  Manage at: https://claude.ai/code/scheduled/<trigger_id>
```

**5b. Local cron fallback:**

If transport is local, or if RemoteTrigger creation failed, use `CronCreate` for local auto-polling.

Check `CronList` for any existing poll jobs first — do not create duplicates.

**If a poll job already exists:**

```text
Auto-poll: active (cron job <job_id>, every hour at :<minute>)
```

**If no poll job exists and feed sources are configured (from Step 3):**

Ask the user:

```text
Enable auto-poll? Feeds will be polled every hour while Claude Code is active.
(yes / no)
```

If yes, create the cron job:

```python
CronCreate(
  cron="<random off-peak minute> * * * *",
  prompt="Use distillery_poll to poll all configured feed sources. Report a one-line summary of items fetched and stored.",
  recurring=True,
  durable=True
)
```

Display:

```text
Auto-poll enabled: every hour at :<minute> (cron job <job_id>)
```

**If no feed sources are configured:**

```text
Auto-poll: skipped (no feed sources configured)
  Add sources with /watch add <url> — auto-poll will be set up automatically.
```

### Step 6: Summary

Always display the configuration summary, regardless of which steps were completed or skipped. Use "not connected" or "N/A" for fields that could not be determined.

```text
Distillery Setup Complete

  MCP Server:    <connected | not connected>
  Transport:     <Local | Hosted | Team HTTP | unknown>
  Entries:       <total_entries | N/A>
  Feed Sources:  <N> configured
  Auto-Poll:     <active (cron) | active (remote trigger) | inactive | pending connector>

Available skills:
  /distill   — capture knowledge      /recall   — search knowledge
  /bookmark  — save URLs              /pour     — synthesize topics
  /minutes   — meeting notes          /classify — triage entries
  /watch     — manage feed sources    /radar    — feed digest
  /tune      — adjust thresholds

Run /watch add <url> to start monitoring feeds.
```

## Output Format

The setup wizard uses a sequential, conversational format. Each step prints its result before proceeding to the next. The summary in Step 6 is always shown — even when MCP is unavailable or steps are skipped.

## Rules

- Always start by checking MCP availability
- Always show the Step 6 summary — even on early exits (MCP unavailable, user defers connector registration)
- Never create duplicate cron jobs — always check `CronList` first
- Never create duplicate remote triggers — always check `RemoteTrigger(action="list")` first
- For remote trigger creation, include `mcp__distillery__distillery_poll` in `allowed_tools`
- Pick an off-peak cron minute (not :00 or :30) for auto-poll schedules
- If the user has no feed sources, skip auto-poll setup but explain how to enable it later
- If `RemoteTrigger` calls fail, fall back to `CronCreate` gracefully and explain the limitation
- This skill is idempotent — running it multiple times should not create duplicates
- Use actual field names from `distillery_status` response (`total_entries`, `embedding_model`, `database_size_bytes`)
