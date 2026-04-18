# Routine Payloads — Distillery Scheduled Tasks

Reference payloads for the three tiers of scheduled tasks configured in Step 4 of `/setup`.

All routines use Claude Code's built-in routine system. Routine prompts execute in Claude Code context which has direct MCP access — no HTTP webhooks or CronCreate needed.

> **Migration note:** This replaces the previous `cron-payloads.md` reference. CronCreate-based scheduling and webhook-based scheduling (GitHub Actions + `/hooks/*` endpoints) are deprecated. Existing CronCreate jobs and webhook schedules continue to work but should be migrated to routines.

## 4a. Hourly — Feed Health Check (status only)

> **Important — this routine does NOT fetch new items.**
> The consolidated MCP surface does not expose a `distillery_poll` tool
> directly. Polling (fetching new feed items) is driven by the
> `POST /hooks/poll` webhook, which runs on the hosted/team deployment's
> GitHub Actions schedule. This routine only inspects the state of already-
> stored entries and reports whether the webhook poller appears healthy.
> To set up actual polling, configure the webhook schedule in the
> `distill_ops` deployment repo (see the MCP Deployment guide).

Guide the user to create a Claude Code routine with these parameters:

**Routine name:** `distillery-feed-health-check`
**Schedule:** Every hour
**Prompt:**

```text
This is a health-check routine only — it does NOT fetch new feed items.
Call distillery_watch(action='list') to list configured feed sources.
Call distillery_list(entry_type='feed', limit=5) to check recent feed entries.
Report: number of configured sources and age of the newest feed entry.
If the newest feed entry is more than 2× the expected poll interval old,
warn that the POST /hooks/poll webhook poller may be unhealthy — no new items
are being fetched. Direct the user to check the distill_ops GitHub Actions
schedule to verify the webhook cron job is running.
```

Display after configuration:

```text
Feed health-check routine: configured (hourly)
  Create this routine in Claude Code Settings > Routines with the prompt above.
  IMPORTANT: this routine checks feed health only. It does NOT fetch new items.
  Actual polling runs via POST /hooks/poll (GitHub Actions schedule in distill_ops).
```

## 4b. Daily — Stale Entry Check

Skip this step if the user declined scheduled tasks or if no feed sources are configured.

**Routine name:** `distillery-stale-check`
**Schedule:** Daily
**Prompt:**

```text
Call distillery_list(stale_days=30, limit=10) to find entries not accessed in 30+ days. Report: count of stale entries and the oldest one's title/age.
```

Display after configuration:

```text
Stale check routine: configured (daily)
  Create this routine in Claude Code Settings > Routines with the prompt above.
```

## 4c. Weekly — Knowledge Base Maintenance

Skip this step if the user declined scheduled tasks.

> **Note on the maintenance pipeline:** The orchestrated poll → rescore →
> classify-batch flow is driven by the `POST /api/maintenance` webhook (bearer
> auth). This MCP-only routine is therefore a reporting complement — it
> summarises state after the webhook pipeline has run. Hosted deployments
> configure the maintenance schedule in the `distill_ops` repo (GitHub
> Actions); the routine below then surfaces the resulting state to the user.

**Routine name:** `distillery-weekly-maintenance-report`
**Schedule:** Weekly
**Prompt:**

```text
Weekly Distillery maintenance report:
1. Call distillery_status() to read server health, tool count, store stats
   and last maintenance run timestamp.
2. Call distillery_list(output='stats') for entry counts by type/status and
   storage size.
3. Call distillery_list(stale_days=30, limit=10) for stale entry count.
4. Call distillery_list(entry_type='feed', limit=5) for recent feed activity.
5. Store a digest: distillery_store(content=<one-paragraph summary of
   findings>, entry_type='digest', author='distillery-maintenance',
   tags=['digest', 'weekly', 'maintenance']).
6. If distillery_status reports no maintenance run in the last 8 days, warn
   that the POST /api/maintenance webhook may be unhealthy and point at the
   distill_ops GitHub Actions schedule.
Report: entry counts, stale entry count, feed activity, storage size,
last maintenance run age.
```

Display after configuration:

```text
Maintenance report routine: configured (weekly)
  Checks: server status, entry stats, stale entries, feed activity
  Stores: weekly digest entry for tracking trends
  Note: the poll → rescore → classify-batch pipeline itself runs via
  POST /api/maintenance (GitHub Actions schedule, configured in distill_ops).
  This routine reports state only.
  Create this routine in Claude Code Settings > Routines with the prompt above.
```
