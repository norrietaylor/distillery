---
name: setup
description: "Onboarding wizard — verify MCP connectivity, detect transport, and configure scheduled tasks"
allowed-tools:
  - "mcp__*__distillery_metrics"
  - "CronCreate"
  - "RemoteTrigger"
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

Call `distillery_metrics(scope="summary")` to confirm the Distillery MCP server is running and authenticated.

**1c. Determine state and respond:**

Evaluate the result based on what was found in 1a and 1b:

---

**State: Connected** — `distillery_metrics(scope="summary")` returned successfully.

Display using the actual fields from `distillery_metrics(scope="summary")`:


```text
MCP server connected.
  Entries:  <total_entries>
  Model:    <embedding_model>
  DB Size:  <database_size_bytes / 1048576> MB
```

Proceed to Step 2.

**State: Needs Authentication** — Server entry found but `distillery_metrics(scope="summary")` is unavailable or fails (including auth-related failures). See `references/transport-detection.md` for display instructions. Skip to Step 6 with `MCP Server: needs authentication`.

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

Distillery uses three tiers of scheduled tasks: hourly feed polling, daily feed rescoring, and weekly knowledge base maintenance.

**Note for hosted/team transport:** Scheduling is managed by GitHub Actions at `.github/workflows/scheduler.yml`. No local cron configuration is needed. Skip to Step 5.

Read `references/cron-payloads.md` for the full cron payloads and display instructions for Steps 4a, 4b, and 4c.

If transport is local, use `CronCreate` for local auto-polling.

Check `CronList` for any existing poll jobs first — do not create duplicates.

**If a poll job already exists:**

```text
Auto-poll: active (cron job <job_id>, every hour at :<minute>)
```

**If no poll job exists and feed sources are configured (from Step 3):**

Ask the user once about enabling scheduled tasks — their answer applies to all three tiers.

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
1. Call distillery_metrics(scope="summary", period_days=7) — note entry growth, search volume, storage usage.
2. Call distillery_metrics(scope="search_quality") — note positive feedback rate and avg result count.
3. Call distillery_stale(days=30, limit=10) — note count and oldest entries.
4. Call distillery_interests(recency_days=30, top_n=10) — note top tags and domains.
5. Call distillery_interests(suggest_sources=True, max_suggestions=3) — note any new recommendations.
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

  Scheduled Tasks:
    Feed poll:     <active (hourly) | inactive | managed by GitHub Actions>
    Feed rescore:  <active (daily 06:XX UTC) | inactive | managed by GitHub Actions>
    KB maintenance:<active (weekly Mon 07:XX UTC) | inactive | managed by GitHub Actions>

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
- For hosted/team transport, skip local cron creation — scheduling is handled by GitHub Actions
- Never create duplicate cron jobs — always check `CronList` first for each job type (poll, rescore, maintenance)
- Pick an off-peak cron minute (not :00 or :30) for all schedules; use different random minutes for each job
- If the user has no feed sources, skip feed poll and rescore but still offer weekly maintenance
- This skill is idempotent — running it multiple times should not create duplicates
- Use actual field names from `distillery_metrics(scope="summary")` response (`total_entries`, `embedding_model`, `database_size_bytes`)
- The weekly maintenance job stores its output as a digest entry — this creates a longitudinal record of KB health
- Ask the user once about enabling scheduled tasks; their answer applies to all three tiers (poll, rescore, maintenance)
