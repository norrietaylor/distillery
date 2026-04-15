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
  prompt="Call distillery_watch(action='list') to check configured feed sources and report their status. Then call distillery_list(limit=5, output_mode='summary') to check for recent additions. Report a one-line summary of feed source count and recent entry count.",
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
  prompt="Call distillery_list(limit=10, output_mode='summary') and distillery_list(group_by='entry_type') to assess knowledge base freshness. Report entry counts by type and flag any staleness concerns.",
  recurring=True,
  durable=True
)
```

Display:

```text
Daily rescore enabled: 06:<minute> UTC (cron job <job_id>)
```

## 4c. Weekly — Knowledge Base Maintenance

A weekly maintenance pass classifies pending entries, checks for stale knowledge, and stores a digest summary. All operations use MCP tools.

Skip this step if the user declined scheduled tasks.

Check `CronList` for an existing maintenance job. If none exists, create one:

```python
CronCreate(
  cron="<random minute> 7 * * 1",
  prompt="""Run weekly Distillery maintenance:
1. Call distillery_list(status="pending_review", limit=20, output_mode="summary") to find entries needing classification. For each pending entry, call distillery_classify to triage it.
2. Call distillery_list(stale_days=30, limit=10, output_mode="summary") — note count and oldest entries.
3. Call distillery_list(group_by="tags") — note top tags and domains.
4. Store a digest: distillery_store(content=<one-paragraph summary of findings>, entry_type="digest", author="distillery-maintenance", tags=["digest", "weekly", "maintenance"], metadata={"period_start": "<7 days ago ISO>", "period_end": "<today ISO>"}).
Report: stale entry count, top tags, classify summary.""",
  recurring=True,
  durable=True
)
```

Display:

```text
Weekly maintenance enabled: Mondays at 07:<minute> UTC (cron job <job_id>)
  Runs: classify inbox → stale check → tag summary → digest
```
