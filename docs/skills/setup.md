# /setup — Onboarding Wizard

Walks through first-time Distillery configuration: verifying MCP connectivity, detecting transport mode, and configuring scheduled tasks.

## Usage

```text
/setup
```

**Trigger phrases:** "setup", "configure distillery", "set up distillery"

## When to Use

- After installing the Distillery plugin for the first time
- When switching between local and hosted transport
- When you want to configure scheduled tasks for feed polling, rescoring, and maintenance
- When `/watch add` reports the poll schedule is unavailable

## What It Does

The wizard runs through up to 6 steps, showing a summary at the end regardless of how far it gets.

### Step 1: Check MCP Availability

Verifies the Distillery MCP server is reachable and displays server stats (total entries, embedding model, database size).

Three possible states:

| State | What happens |
|-------|-------------|
| **Connected** | Shows server stats, proceeds to Step 2 |
| **Needs authentication** | Prompts to complete GitHub OAuth flow |
| **Not configured** | Points to setup documentation |

### Step 2: Detect Transport Mode

Reads your MCP settings to determine how you're connected:

| Transport | Detection |
|-----------|-----------|
| **Local** | `localhost`, `127.0.0.1`, or stdio |
| **Hosted** | `distillery-mcp.fly.dev` |
| **Team HTTP** | Other HTTP URLs |

### Step 3: Check Feed Sources

Lists any configured feed sources from `/watch`.

### Step 4: Scheduled Tasks

Configures up to three tiers of recurring tasks via **Claude Code routines**:

| Schedule | Routine | Purpose |
|----------|---------|---------|
| **Hourly** | `distillery-feed-poll` | Fetch new items from all feed sources |
| **Daily** | `distillery-stale-check` | Identify entries needing refresh or archival |
| **Weekly** | `distillery-weekly-maintenance` | Collect metrics, stale entries, feed activity, digest |

Routines run automatically in the background when Claude Code is active. They work the same way for both local and hosted transport.

- If no feed sources exist, poll and stale check are skipped but weekly maintenance is still offered
- The wizard provides the routine name, schedule, and prompt for each tier

!!! note "Migration from CronCreate / Webhooks"
    Previous versions used `CronCreate` (local) or GitHub Actions webhook scheduling (hosted). Both approaches are now deprecated in favour of Claude Code routines. Existing jobs continue to work but should be migrated.

### Step 5: Configure Session Hooks

Configures session lifecycle hooks in the appropriate `settings.json` based on your plugin installation scope.

!!! note "Plugin Hooks Limitation"
    Plugin manifest hooks (`plugin.json`) support `SessionStart` and `Stop` events but **not** `UserPromptSubmit`. To enable the memory nudge and full session lifecycle hooks, they must be configured in `settings.json` via `/setup`.

The wizard:

1. **Detects plugin scope** — checks `enabledPlugins` in user (`~/.claude/settings.json`) or project (`.claude/settings.json`) settings
2. **Locates the dispatcher** — finds `scripts/hooks/distillery-hooks.sh` in the repo or plugin cache
3. **Checks existing hooks** — skips if both `UserPromptSubmit` and `SessionStart` already reference the dispatcher
4. **Installs hooks** — merges hook config into the scope-appropriate settings file

| Hook | Behaviour |
|------|-----------|
| **UserPromptSubmit** | Memory nudge every 30 prompts — reminds you to `/distill` |
| **SessionStart** | Injects a condensed briefing with recent entries and stale items |

### Step 6: Summary

Always displayed, even if the wizard exits early:

```text
## Distillery Setup Summary

| Setting | Value |
|---------|-------|
| MCP Status | Connected |
| Transport | Hosted (distillery-mcp.fly.dev) |
| Entries | 42 |
| Feed Sources | 3 |
| Hourly Poll | Active (routine) |
| Daily Stale Check | Active (routine) |
| Weekly Maintenance | Active (routine) |

### Available Skills
/distill, /recall, /pour, /bookmark, /minutes,
/classify, /watch, /radar, /tune, /digest,
/gh-sync, /investigate, /briefing
```

## Tips

- The wizard is **idempotent** — running it multiple times won't create duplicate jobs
- Scheduled tasks use off-peak cron minutes (not `:00` or `:30`) to spread load
- Weekly maintenance stores a digest entry for longitudinal KB health tracking
- You're asked once about enabling scheduled tasks, and the answer applies to all three tiers
- For hosted deployments, the webhook endpoints provide audit records in DuckDB (see `webhook_audit:*` metadata keys)
