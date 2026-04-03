---
name: setup
description: "Onboarding wizard — verify MCP connectivity, detect transport, and configure scheduled tasks"
allowed-tools:
  - "mcp__*__distillery_status"
  - "CronCreate"
  - "RemoteTrigger"
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

Call `distillery_status` to confirm the MCP server is running and authenticated.

**State: Connected** — `distillery_status` returned successfully.

```text
MCP server connected.
  Entries:  <total_entries>
  Model:    <embedding_model>
  DB Size:  <database_size_bytes / 1048576> MB
```

Proceed to Step 2.

**State: Needs Authentication** — Server entry found but `distillery_status` unavailable or returns auth error. See `references/transport-detection.md` for display instructions. Skip to Step 5 with `MCP Server: needs authentication`.

**State: Not Configured** — No server entry found anywhere.

```text
Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrietaylor/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

Skip to Step 5 with `MCP Server: not connected`.

### Step 2: Detect Transport Mode

Read `references/transport-detection.md` for the transport classification table and display format.

### Step 3: Check Feed Sources

Call `distillery_watch(action="list")` to see if any feed sources are configured.

```text
Feed sources: <N> configured
```

If sources exist, list them briefly (URL + label).

### Step 4: Scheduled Tasks Configuration

Distillery uses three tiers of scheduled tasks: hourly feed polling, daily feed rescoring, and weekly knowledge base maintenance.

**Note for hosted/team transport:** Scheduling is managed by GitHub Actions at `.github/workflows/scheduler.yml`. No local cron configuration is needed. Skip to Step 5.

Read `references/cron-payloads.md` for the full cron payloads and display instructions for Steps 4a, 4b, and 4c.

Ask the user once about enabling scheduled tasks — their answer applies to all three tiers.

### Step 5: Summary

Always display the configuration summary, regardless of which steps were completed or skipped.

```text
Distillery Setup Complete

  MCP Server:    <connected | needs authentication | not connected>
  Transport:     <Local | Hosted | Team HTTP | unknown>
  Entries:       <total_entries | N/A>
  Feed Sources:  <N> configured

  Scheduled Tasks:
    Feed poll:     <active (hourly) | inactive | managed by GitHub Actions>
    Feed rescore:  <active (daily 06:XX UTC) | inactive | managed by GitHub Actions>
    KB maintenance:<active (weekly Mon 07:XX UTC) | inactive | managed by GitHub Actions>

Available skills:
  /distill   — capture knowledge      /recall   — search knowledge
  /bookmark  — save URLs              /pour     — synthesize topics
  /minutes   — meeting notes          /classify — triage entries
  /watch     — manage feed sources    /radar    — feed digest
  /tune      — adjust thresholds

Run /watch add <url> to start monitoring feeds.
```

## Output Format

The setup wizard uses a sequential, conversational format. Each step prints its result before proceeding to the next. The summary in Step 5 is always shown — even when MCP is unavailable or steps are skipped.

## Rules

- Always start by checking MCP availability — distinguish between "not configured", "needs authentication", and "connected"
- When an MCP server entry exists but tools are unavailable, treat this as "needs authentication" — guide the user through the OAuth flow
- Always show the Step 5 summary — even on early exits (MCP unavailable, auth needed)
- For hosted/team transport, skip local cron creation — scheduling is handled by GitHub Actions
- Never create duplicate cron jobs — always check `CronList` first for each job type (poll, rescore, maintenance)
- Pick an off-peak cron minute (not :00 or :30) for all schedules; use different random minutes for each job
- If the user has no feed sources, skip feed poll and rescore but still offer weekly maintenance
- This skill is idempotent — running it multiple times should not create duplicates
- Use actual field names from `distillery_status` response (`total_entries`, `embedding_model`, `database_size_bytes`)
- The weekly maintenance job stores its output as a digest entry — this creates a longitudinal record of KB health
- Ask the user once about enabling scheduled tasks; their answer applies to all three tiers (poll, rescore, maintenance)
