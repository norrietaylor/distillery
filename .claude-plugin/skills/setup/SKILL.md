---
name: setup
description: "Onboarding wizard for Distillery plugin — verifies MCP connectivity, detects transport, and configures scheduled tasks (hourly poll, daily rescore, weekly maintenance). Triggered by: 'setup', '/setup', 'configure distillery', 'set up distillery'."
---

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

This step determines the MCP server state, which can be one of three outcomes: **connected**, **needs authentication**, or **not configured**.

**1a. Detect server presence:**

Use `ToolSearch` to check whether any `distillery` MCP tools are available. Also read the plugin manifest (`.claude-plugin/plugin.json` in the plugin directory) and any `.mcp.json` or `~/.claude/settings.json` entries to determine if a Distillery MCP server is configured.

**1b. Attempt connection:**

Call `distillery_status` to confirm the Distillery MCP server is running and authenticated.

**1c. Determine state and respond:**

Evaluate the result based on what was found in 1a and 1b:

---

**State: Connected** — `distillery_status` returned successfully.

Display using the actual fields from `distillery_status`:

```text
MCP server connected.
  Entries:  <total_entries>
  Model:    <embedding_model>
  DB Size:  <database_size_bytes / 1048576> MB
```

Proceed to Step 2.

---

**State: Needs Authentication** — A Distillery MCP server entry exists (in `plugin.json`, `.mcp.json`, or `settings.json`) but `distillery_status` is unavailable or returns an auth error. This typically means the server is configured with HTTP transport and GitHub OAuth, but the user has not completed the OAuth flow yet.

Display:

```text
Distillery MCP Server — Authentication Required

The MCP server is configured but needs authentication.
  Server: <URL from config>

To authenticate:
1. Press Ctrl+. (or Cmd+.) to open the MCP server menu
2. Select the Distillery server (it will show "needs authentication")
3. Press Enter — your browser will open for GitHub OAuth
4. Authorize the app in your browser
5. Return here and run /distillery:setup again

Alternatively, you can type: ! claude mcp authenticate distillery
```

Then skip to Step 5 (Summary) with `MCP Server: needs authentication`.

---

**State: Not Configured** — No Distillery MCP server entry was found anywhere.

Display:

```text
Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrietaylor/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

Then skip to Step 5 (Summary) with `MCP Server: not connected`.

### Step 2: Detect Transport Mode

Read the `.mcp.json` file in the project root (or `~/.claude/settings.json` if `.mcp.json` does not exist) to determine the Distillery MCP server configuration.

Classify the transport:

| URL Pattern | Transport | Mode |
|-------------|-----------|------|
| `localhost`, `127.0.0.1`, or `type: "stdio"` | Local | `local` |
| `distillery-mcp.fly.dev/*` | Hosted | `hosted` |
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

### Step 4: Scheduled Tasks Configuration

Distillery uses three tiers of scheduled tasks: hourly feed polling, daily feed rescoring, and weekly knowledge base maintenance. Each tier is configured independently — check for existing jobs before creating to maintain idempotency.

**Note for hosted/team transport:** Scheduled tasks for hosted deployments are managed by the GitHub Actions workflow at `.github/workflows/scheduler.yml`. No local cron configuration is needed. Skip to Step 5 (Summary).

**4a. Hourly — Feed Polling**

If transport is local, use `CronCreate` for local auto-polling.

Check `CronList` for any existing poll jobs first — do not create duplicates.

**If a poll job already exists:**

```text
Auto-poll: active (cron job <job_id>, every hour at :<minute>)
```

**If no poll job exists and feed sources are configured (from Step 3):**

Ask the user:

```text
Enable scheduled tasks? This includes:
  • Feed polling — every hour
  • Feed rescoring — daily (re-evaluates relevance after new knowledge)
  • KB maintenance — weekly (metrics, quality, stale entries, source suggestions)
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

**4b. Daily — Feed Rescoring**

After new knowledge entries are added, previously-scored feed items may have stale relevance scores. A daily rescore pass re-evaluates them against the current interest profile.

Skip this step if the user declined scheduled tasks or if no feed sources are configured.

Check `CronList` for an existing rescore job. If none exists, create one:

```python
CronCreate(
  cron="<random minute> 6 * * *",
  prompt="Use distillery_rescore(limit=200) to re-score feed entries against the current knowledge base. Report: rescored, upgraded, downgraded, archived counts.",
  recurring=True,
  durable=True
)
```

Display:

```text
Daily rescore enabled: 06:<minute> UTC (cron job <job_id>)
```

**4c. Weekly — Knowledge Base Maintenance**

A weekly maintenance pass collects metrics, checks search quality, identifies stale entries, and refreshes source suggestions. Results are stored as a digest entry for longitudinal tracking.

Skip this step if the user declined scheduled tasks.

Check `CronList` for an existing maintenance job. If none exists, create one:

```python
CronCreate(
  cron="<random minute> 7 * * 1",
  prompt="""Run weekly Distillery maintenance:
1. Call distillery_metrics(period_days=7) — note entry growth, search volume, storage usage.
2. Call distillery_quality() — note positive feedback rate and avg result count.
3. Call distillery_stale(days=30, limit=10) — note count and oldest entries.
4. Call distillery_interests(recency_days=30, top_n=10) — note top tags and domains.
5. Call distillery_suggest_sources(max_suggestions=3) — note any new recommendations.
6. Store a digest: distillery_store(content=<one-paragraph summary of findings>, entry_type="session", author="distillery-maintenance", tags=["digest", "weekly", "maintenance"], metadata={"period_start": "<7 days ago ISO>", "period_end": "<today ISO>"}).
Report: entry counts, search quality trend, stale entry count, top interests, suggested sources.""",
  recurring=True,
  durable=True
)
```

Display:

```text
Weekly maintenance enabled: Mondays at 07:<minute> UTC (cron job <job_id>)
  Collects: metrics, search quality, stale entries, interests, source suggestions
  Stores: weekly digest entry for tracking trends
```

### Step 5: Summary

Always display the configuration summary, regardless of which steps were completed or skipped. Use "not connected" or "N/A" for fields that could not be determined.

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
- When an MCP server entry exists but tools are unavailable, treat this as "needs authentication" rather than "not configured" — guide the user through the OAuth flow
- Always show the Step 5 summary — even on early exits (MCP unavailable, auth needed)
- For hosted/team transport, skip local cron creation — scheduling is handled by GitHub Actions at `.github/workflows/scheduler.yml`
- Never create duplicate cron jobs — always check `CronList` first for each job type (poll, rescore, maintenance)
- Pick an off-peak cron minute (not :00 or :30) for all schedules; use different random minutes for each job
- If the user has no feed sources, skip feed poll and rescore but still offer weekly maintenance
- This skill is idempotent — running it multiple times should not create duplicates
- Use actual field names from `distillery_status` response (`total_entries`, `embedding_model`, `database_size_bytes`)
- The weekly maintenance job stores its output as a digest entry — this creates a longitudinal record of KB health
- Ask the user once about enabling scheduled tasks; their answer applies to all three tiers (poll, rescore, maintenance)
