# Routine Payloads — Distillery Scheduled Tasks

Reference payloads for the three tiers of scheduled tasks configured in Step 4 of `/setup`.

All routines use Claude Code's built-in routine system. Routine prompts execute in Claude Code context which has direct MCP access — no HTTP webhooks or CronCreate needed.

> **Migration note:** This replaces the previous `cron-payloads.md` reference. CronCreate-based scheduling and webhook-based scheduling (GitHub Actions + `/hooks/*` endpoints) are deprecated. Existing CronCreate jobs and webhook schedules continue to work but should be migrated to routines.

## 4a. Hourly — Feed Status Check

Guide the user to create a Claude Code routine with these parameters:

**Routine name:** `distillery-feed-poll`
**Schedule:** Every hour
**Prompt:**

```text
Call distillery_watch(action='list') to check configured feed sources, then call distillery_list(entry_type='feed', limit=5) to verify recent feed activity. Report a one-line summary: source count and latest feed entry age.
```

Display after configuration:

```text
Feed poll routine: configured (hourly)
  Create this routine in Claude Code Settings > Routines with the prompt above.
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

**Routine name:** `distillery-weekly-maintenance`
**Schedule:** Weekly
**Prompt:**

```text
Run weekly Distillery maintenance:
1. Call distillery_list(output='stats') for entry counts by type/status and storage size.
2. Call distillery_list(stale_days=30, limit=10) for stale entry count.
3. Call distillery_list(entry_type='feed', limit=5) for recent feed activity.
4. Store a digest: distillery_store(content=<one-paragraph summary of findings>, entry_type='session', author='distillery-maintenance', tags=['digest', 'weekly', 'maintenance']).
Report: entry counts, stale entry count, feed activity, storage size.
```

Display after configuration:

```text
Maintenance routine: configured (weekly)
  Checks: entry stats, stale entries, feed activity
  Stores: weekly digest entry for tracking trends
  Create this routine in Claude Code Settings > Routines with the prompt above.
```
