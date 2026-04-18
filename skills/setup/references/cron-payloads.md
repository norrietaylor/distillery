# Cron Payloads — Distillery Scheduled Tasks (DEPRECATED)

> **DEPRECATED:** CronCreate-based scheduling is deprecated in favour of Claude Code routines.
> See `routine-payloads.md` for the replacement. This file is retained for reference during
> migration. Existing CronCreate jobs continue to work but should be replaced with routines.

Reference payloads for the three tiers of scheduled tasks configured in Step 4 of `/setup`.

All prompts use MCP tool calls — local/stdio transport has no HTTP server, so webhook endpoints are unreachable. CronCreate prompts execute in Claude Code context which has direct MCP access.

## 4a. Hourly — Feed Status Check

Check `CronList` for any existing poll job before creating — do not create duplicates.

**If a poll job already exists:**

```text
Feed status check: active (cron job <job_id>, every hour at :<minute>)
```

**If no poll job exists and feed sources are configured:**

Ask the user:

```text
Enable scheduled tasks? This includes:
  • Feed status check — every hour (no ingestion; watch/list + recent activity)
  • Stale entry check — daily
  • KB maintenance — weekly (stats, stale entries, digest)
(yes / no)
```

If yes, create the cron job:

```python
CronCreate(
  cron="<random off-peak minute> * * * *",
  prompt="Call distillery_watch(action='list') to check configured feed sources, then call distillery_list(entry_type='feed', limit=5) to verify recent feed activity. Report a one-line summary: source count and latest feed entry age.",
  recurring=True,
  durable=True
)
```

Display:

```text
Feed status check enabled: every hour at :<minute> (cron job <job_id>)
```

**If no feed sources are configured:**

```text
Feed status check: skipped (no feed sources configured)
  Add sources with /watch add <url> — the status check will be set up automatically.
```

## 4b. Daily — Stale Entry Check

Skip this step if the user declined scheduled tasks or if no feed sources are configured.

Check `CronList` for an existing daily job. If none exists, create one:

```python
CronCreate(
  cron="<random minute> 6 * * *",
  prompt="Call distillery_list(stale_days=30, limit=10) to find entries not accessed in 30+ days. Report: count of stale entries and the oldest one's title/age.",
  recurring=True,
  durable=True
)
```

Display:

```text
Daily stale check enabled: 06:<minute> UTC (cron job <job_id>)
```

## 4c. Weekly — Knowledge Base Maintenance

Skip this step if the user declined scheduled tasks.

Check `CronList` for an existing maintenance job. If none exists, create one:

```python
CronCreate(
  cron="<random minute> 7 * * 1",
  prompt="""Run weekly Distillery maintenance:
1. Call distillery_list(output='stats') for entry counts by type/status and storage size.
2. Call distillery_list(stale_days=30, limit=10) for stale entry count.
3. Call distillery_list(entry_type='feed', limit=5) for recent feed activity.
4. Store a digest: distillery_store(content=<one-paragraph summary of findings>, entry_type='digest', author='distillery-maintenance', tags=['digest', 'weekly', 'maintenance']).
Report: entry counts, stale entry count, feed activity, storage size.""",
  recurring=True,
  durable=True
)
```

Display:

```text
Weekly maintenance enabled: Mondays at 07:<minute> UTC (cron job <job_id>)
  Checks: entry stats, stale entries, feed activity
  Stores: weekly digest entry for tracking trends
```
