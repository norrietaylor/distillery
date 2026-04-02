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

## 4b. Daily — Feed Rescoring

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

## 4c. Weekly — Knowledge Base Maintenance

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
