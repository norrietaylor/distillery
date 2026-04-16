---
name: setup
description: "Onboarding wizard — verify MCP connectivity, detect transport, and configure scheduled tasks via Claude Code routines"
allowed-tools:
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_watch"
  - "mcp__*__distillery_configure"
  - "Bash(test:*)"
  - "Bash(cat:*)"
  - "Bash(find:*)"
  - "Bash(ls:*)"
  - "Bash(jq:*)"
  - "Bash(mkdir:*)"
  - "Bash(cp:*)"
  - "Bash(chmod:*)"
effort: low
---

<!-- Trigger phrases: setup, /setup, configure distillery, set up distillery -->

# Setup — Distillery Onboarding

Setup walks you through first-time Distillery configuration: verifying MCP connectivity, detecting your transport mode, and configuring scheduled tasks (hourly feed polling, daily relevance rescoring, weekly KB maintenance).

Run this once after installing the plugin. It is safe to run again at any time to verify or update your configuration.

## When to Use

- After installing the Distillery plugin for the first time
- When switching between local and hosted MCP transports
- When you want to configure scheduled tasks for feed polling, rescoring, and maintenance
- When invoked via `/setup` or "configure distillery"

## Process

### Step 1: Check MCP Availability

This step determines the MCP server state: **connected**, **needs authentication**, or **not configured**.

Read `references/transport-detection.md` for server detection logic and the "Needs Authentication" auth flow instructions.

Use `ToolSearch` to check whether any `distillery` MCP tools are available. Also read the plugin manifest (`.claude-plugin/plugin.json` in the plugin directory) and any `.mcp.json` or `~/.claude/settings.json` entries to determine if a Distillery MCP server is configured.

**1b. Attempt connection:**

Call `distillery_list(limit=1)` to confirm the Distillery MCP server is running and authenticated.

**1c. Determine state and respond:**

Evaluate the result based on what was found in 1a and 1b:

---

**State: Connected** — `distillery_list(limit=1)` returned successfully.

Display:

```text
MCP server connected.
  Entries:  <total_count from distillery_list>
```

Proceed to Step 2.

**State: Needs Authentication** — Server entry found but `distillery_list(limit=1)` is unavailable or fails (including auth-related failures). See `references/transport-detection.md` for display instructions. Skip to Step 6 with `MCP Server: needs authentication`.

---

**State: Not Configured** — No Distillery MCP server entry was found anywhere.

Display:

```text
Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

Quickest setup — add to ~/.claude/settings.json:

  {
    "mcpServers": {
      "distillery": {
        "command": "uvx",
        "args": ["distillery-mcp"],
        "env": {
          "JINA_API_KEY": "<your-jina-api-key>"
        }
      }
    }
  }

Get a free Jina API key at https://jina.ai
Then restart Claude Code and run /setup again.

Full guide: https://norrietaylor.github.io/distillery/getting-started/local-setup/
```

Skip to Step 6 with `MCP Server: not connected`.

### Step 2: Detect Transport Mode

Read `references/transport-detection.md` for the transport classification table and display format.

### Step 3: Check Feed Sources

Call `distillery_watch(action="list")` to see if any feed sources are configured.

```text
Feed sources: <N> configured
```

If sources exist, list them briefly (URL + label).

### Step 4: Scheduled Tasks Configuration

Distillery uses three tiers of scheduled tasks, all configured as **Claude Code routines**:

| Tier | Frequency | Purpose |
|------|-----------|---------|
| Feed polling | Hourly | Fetch new items from feed sources |
| Stale entry check | Daily | Identify entries needing refresh or archival |
| KB maintenance | Weekly | Stats, stale entries, feed activity, digest |

Read `references/routine-payloads.md` for the full routine definitions and display instructions for Steps 4a, 4b, and 4c.

**If no feed sources are configured (from Step 3):**

```text
Scheduled tasks: skipped (no feed sources configured)
  Add sources with /watch add <url> — then run /setup again to configure routines.
```

Skip to Step 5.

**If feed sources are configured, ask the user once — their answer applies to all three tiers:**

```text
Enable scheduled tasks via Claude Code routines? This creates:
  • Feed polling routine — every hour
  • Stale entry check routine — daily
  • KB maintenance routine — weekly (stats, stale entries, digest)

Routines run automatically in the background when Claude Code is active.
(yes / no)
```

If yes, display the routine configuration instructions from `references/routine-payloads.md`.

If no:

```text
Scheduled tasks: skipped
  Enable later by running /setup again.
```

### Step 5: Configure Session Hooks

Plugin manifest hooks do not support `UserPromptSubmit` events. Manifest hooks support `SessionStart` and `Stop`, so `UserPromptSubmit` must be configured in `settings.json`. To enable the memory nudge (every 30 prompts) and full session lifecycle hooks via the dispatcher, the script must be configured in the appropriate settings.json based on plugin installation scope.

**5a. Detect plugin installation scope:**

Check which settings file contains the Distillery plugin in `enabledPlugins`:

1. `~/.claude/settings.json` → **user scope** (hooks apply to all projects)
2. `.claude/settings.json` → **project scope** (hooks apply to this project only)
3. `.claude/settings.local.json` → **local scope** (treat as project scope)

If the plugin isn't found in any file (e.g., running from the Distillery repo itself), default to **project scope**.

Set `SCOPE_FILE` to the matching settings file and `SCOPE_LABEL` to "user" or "project".

**5b. Locate the hook scripts:**

The hook scripts ship with the plugin under `scripts/hooks/`. Determine the absolute path:

1. If `scripts/hooks/distillery-hooks.sh` exists relative to cwd → use that path
2. Otherwise, check `~/.claude/plugins/cache/` for a `distillery-*/scripts/hooks/` directory

Required files:
- `distillery-hooks.sh` — main dispatcher (routes events to handlers)
- `session-start-briefing.sh` — SessionStart briefing handler (called by dispatcher)

If the scripts cannot be found, display:

```text
Session hooks: skipped (hook scripts not found)
  Run /setup from inside the Distillery repo to install hooks.
```

Skip to Step 6.

**5c. Check existing hooks:**

Read `SCOPE_FILE` and check whether **both** `hooks.UserPromptSubmit` and `hooks.SessionStart` reference `distillery-hooks.sh` (same dispatcher path).

If both are already configured:

```text
Session hooks: active (<SCOPE_LABEL> scope)
  Memory nudge:  every 30 prompts
  Session start: briefing context injection
```

Skip to Step 6.

**5d. Install hooks:**

Ask the user:

```text
Enable session hooks? This configures hooks in <SCOPE_FILE> (<SCOPE_LABEL> scope).
  • Memory nudge — reminder to /distill every 30 prompts
  • Session start — briefing context injection
(yes / no)
```

If yes, merge the following hooks into `SCOPE_FILE` (do not overwrite other settings). Use the absolute path to the dispatcher script found in 5b:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash <absolute-path-to>/scripts/hooks/distillery-hooks.sh"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash <absolute-path-to>/scripts/hooks/distillery-hooks.sh"
          }
        ]
      }
    ]
  }
}
```

Display:

```text
Session hooks installed:
  Config:        <SCOPE_FILE> (<SCOPE_LABEL> scope)
  Dispatcher:    <absolute-path-to>/scripts/hooks/distillery-hooks.sh
  Memory nudge:  every 30 prompts
  Session start: briefing context injection
```

If no:

```text
Session hooks: skipped
  Enable later by running /setup again.
```

### Step 6: Summary

Always display the configuration summary, regardless of which steps were completed or skipped.

```text
Distillery Setup Complete

  MCP Server:    <connected | needs authentication | not connected>
  Transport:     <Local | Hosted | Team HTTP | unknown>
  Entries:       <total_entries | N/A>
  Feed Sources:  <N> configured

  Scheduled Routines:
    Feed poll:     <active (hourly routine) | inactive>
    Stale check:   <active (daily routine) | inactive>
    KB maintenance:<active (weekly routine) | inactive>

  Session Hooks:   <SCOPE_LABEL> scope
    Memory nudge:  <active (every 30 prompts) | inactive | skipped>
    Session start: <active | inactive | skipped>

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

- Always start by checking MCP availability — distinguish between "not configured", "needs authentication", and "connected"
- When an MCP server entry exists but tools are unavailable, treat this as "needs authentication" — guide the user through the OAuth flow
- Always show the Step 6 summary — even on early exits (MCP unavailable, auth needed)
- Session hooks are installed to the same scope as the plugin (user or project) — detect via `enabledPlugins`
- Merge hook config into the scope-appropriate settings file — never overwrite other settings
- If hook scripts can't be found (not in repo or plugin cache), skip gracefully
- The dispatcher uses `BASH_SOURCE[0]` to find sibling scripts — both files must be in the same directory
- Use absolute paths to the dispatcher script in hook commands
- Scheduling uses Claude Code routines for all transport modes (local and hosted)
- If the user has no feed sources, skip feed poll and stale check but still offer weekly maintenance
- This skill is idempotent — running it multiple times should not create duplicate routines
- Use `distillery_list(limit=1)` for the MCP health check
- Routine prompts use MCP tool calls — routines execute in Claude Code context with direct MCP access
- The weekly maintenance routine stores its output as a digest entry — this creates a longitudinal record of KB health
- Ask the user once about enabling scheduled tasks; their answer applies to all three tiers
- Legacy CronCreate and webhook-based scheduling are deprecated — guide users to routines instead