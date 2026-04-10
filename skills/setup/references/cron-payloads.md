# Cron Payloads — Distillery Scheduled Tasks

Reference payloads for the three tiers of scheduled tasks configured in Step 4 of `/setup`.

## 4a. Hourly — Feed Polling

Check `CronList` for any existing poll job before creating — do not create duplicates.

**If a poll job already exists:**

```text
Auto-poll: active (cron job <job_id>, every hour at :<minute>)
```

**If no poll job exists and feed sources are configured:**

Ask the user:

```text
Enable scheduled tasks? This includes:
  • Feed polling — every hour
  • Feed rescoring — daily (re-evaluates relevance after new knowledge)
  • KB maintenance — weekly (poll, rescore, classify inbox)
(yes / no)
```

If yes, create the cron job:

```python
CronCreate(
  cron="<random off-peak minute> * * * *",
  prompt="POST /hooks/poll to poll all configured feed sources. Report a one-line summary of items fetched and stored.",
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

## 4b. Daily — Feed Rescoring

After new knowledge entries are added, previously-scored feed items may have stale relevance scores. A daily rescore pass re-evaluates them against the current interest profile.

Skip this step if the user declined scheduled tasks or if no feed sources are configured.

Check `CronList` for an existing rescore job. If none exists, create one:

```python
CronCreate(
  cron="<random minute> 6 * * *",
  prompt="POST /hooks/rescore?limit=200 to re-score feed entries against the current knowledge base. Report: rescored, upgraded, downgraded, archived counts.",
  recurring=True,
  durable=True
)
```

Display:

```text
Daily rescore enabled: 06:<minute> UTC (cron job <job_id>)
```

## 4c. Weekly — Knowledge Base Maintenance

A weekly maintenance pass runs the full pipeline: poll feeds, rescore entries, and classify inbox items. This is handled by a single `/api/maintenance` webhook call.

Skip this step if the user declined scheduled tasks.

Check `CronList` for an existing maintenance job. If none exists, create one:

```python
CronCreate(
  cron="<random minute> 7 * * 1",
  prompt="POST /api/maintenance to run weekly Distillery maintenance (poll → rescore → classify-batch). Report the combined results: items polled, rescored, and classified.",
  recurring=True,
  durable=True
)
```

Display:

```text
Weekly maintenance enabled: Mondays at 07:<minute> UTC (cron job <job_id>)
  Runs: poll → rescore → classify-batch pipeline
```
