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

The wizard runs through up to 5 steps, showing a summary at the end regardless of how far it gets.

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

Configures up to three tiers of recurring jobs:

| Schedule | Task | Purpose |
|----------|------|---------|
| **Hourly** | Feed polling | Fetch new items from all feed sources |
| **Daily** | Feed rescoring | Re-score entries against updated interest profile |
| **Weekly** | KB maintenance | Collect metrics, quality, stale entries, interests, suggestions |

Scheduling depends on your transport:

- **Local transport** — creates cron jobs via `CronCreate` (a Claude Code platform primitive)
- **Hosted/team transport** — scheduling is managed by the GitHub Actions workflow at `.github/workflows/scheduler.yml`, which calls the webhook endpoints (`/api/poll`, `/api/rescore`, `/api/maintenance`). No local cron configuration needed.
- Checks for existing jobs before creating (no duplicates)
- If no feed sources exist, poll/rescore are skipped but weekly maintenance is still offered

### Step 5: Summary

Always displayed, even if the wizard exits early:

```text
## Distillery Setup Summary

| Setting | Value |
|---------|-------|
| MCP Status | Connected |
| Transport | Hosted (distillery-mcp.fly.dev) |
| Entries | 42 |
| Feed Sources | 3 |
| Hourly Poll | Managed by GitHub Actions |
| Daily Rescore | Managed by GitHub Actions |
| Weekly Maintenance | Managed by GitHub Actions |

### Available Skills
/distill, /recall, /pour, /bookmark, /minutes,
/classify, /watch, /radar, /tune
```

## Tips

- The wizard is **idempotent** — running it multiple times won't create duplicate jobs
- Scheduled tasks use off-peak cron minutes (not `:00` or `:30`) to spread load
- Weekly maintenance stores a digest entry for longitudinal KB health tracking
- You're asked once about enabling scheduled tasks, and the answer applies to all three tiers
- For hosted deployments, the webhook endpoints provide audit records in DuckDB (see `webhook_audit:*` metadata keys)
