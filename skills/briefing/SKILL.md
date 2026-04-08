---
name: briefing
description: "Produce a single-command team knowledge dashboard combining activity, metrics, interests, and feed intelligence"
allowed-tools:
  - "mcp__*__distillery_metrics"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_aggregate"
  - "mcp__*__distillery_interests"
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_stale"
  - "mcp__*__distillery_tag_tree"
context: fork
effort: high
---

<!-- Trigger phrases: briefing, /briefing, team briefing, knowledge dashboard, team overview, situational awareness, team status -->

# Briefing — Team Knowledge Dashboard

Briefing produces a single-command team overview: system health, recent team activity, trending interests, top feed signals, and suggested actions — all in one display.

## When to Use

- Starting a team meeting or standup (`/briefing`)
- Checking knowledge base health and team activity at a glance
- Getting situational awareness across internal activity and external feeds
- "team briefing", "knowledge dashboard", "team overview", "team status"
- Scoping activity to a project (`/briefing --project distillery`)
- Adjusting the lookback window (`/briefing --days 14`)

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

| Flag | Description |
|------|-------------|
| `--days N` | Look back N days for activity (default: 7) |
| `--project <name>` | Scope results to a specific project |

Compute `date_from` as today's date minus N days in ISO 8601 format (`YYYY-MM-DD`).

### Step 3: Gather Data

Execute all calls in sequence. Non-fatal calls are noted — continue if they fail.

**3a. System metrics (summary):**

```python
distillery_metrics(scope="summary")
```

Record: total entry count, DB size, embedding model, review queue count.

**3b. Audit metrics (non-fatal):**

```python
distillery_metrics(scope="audit", date_from=<date_from>)
```

Record: active users in period. If this call fails or returns no data, continue without it.

**3c. Recent internal activity:**

```python
distillery_list(
    entry_type=["session", "bookmark", "minutes"],
    limit=50,
    date_from=<date_from>,
    output_mode="full",
    # project=<name>  # only if --project specified
)
```

If `--project` was specified, pass `project=<name>`.

Record the `total_count` from the response. Report: `Found <len(entries)> of <total_count> internal entries from the last <N> days.`

**3d. Per-author activity counts:**

```python
distillery_aggregate(
    group_by="author",
    date_from=<date_from>,
    # project=<name>  # only if --project specified
)
```

**3e. Interest profile and source suggestions:**

```python
distillery_interests(recency_days=<days>, top_n=10, suggest_sources=true)
```

Record: top interest tags and suggested sources. If this call fails, omit the Top Interests section and the "suggested sources" action item from Suggested Actions, but still show other computable actions (review queue count, low activity warnings).

**3f. Top feed signals (non-fatal):**

Using the top interest tag from Step 3e (converted to a natural-language query), call:

```python
distillery_search(
    query=<top_interest_query>,
    entry_type="feed",
    limit=5,
    date_from=<date_from>,
)
```

Convert the top tag to a query by taking the leaf segment and replacing hyphens with spaces (e.g., `domain/vector-search` → `"vector search"`). If `distillery_interests` failed or returned no tags, skip this call. If the search fails, omit the Feed Highlights section.

### Step 4: Synthesize Briefing

You (the executing Claude instance) produce the synthesis. Do not dump raw entries.

**System Health:**

Report counts and sizing from `distillery_metrics(scope="summary")`. Flag conditions that need attention:
- Review queue count > 0: surface as an action item
- If audit data is available, note the number of active users in the period

**Team Activity:**

Using data from Steps 3c and 3d:
- For each author with entries in the period, summarize their contributions: how many of each type, notable topics from tag analysis
- Present per-author counts in a compact table

**Top Interests:**

Present the top interest tags as a ranked list (tag → relevance or frequency). Group by namespace if helpful (e.g., `domain/`, `project/`, `source/`).

**Feed Highlights:**

For each result from Step 3f:
- Title or content snippet
- Source URL if available in metadata
- Relevance to team interests

Omit this section entirely if no feed entries were found.

**Suggested Actions:**

Combine signals from all data into concrete next steps:
- If review queue count > 0: "Run /classify to clear <N> entries in the review queue"
- If `distillery_interests` returned suggested sources: list each with `/watch add <url>` command
- If no activity from an author in an unusually long time (computable from audit data): note it
- If fewer than 5 internal entries in the period: "Activity is low — encourage team to /distill, /minutes, or /bookmark"

Omit suggestions that do not apply.

### Step 5: Confirm

Display the full briefing. This skill is display-only — there is no `--store` flag.

## Output Format

```
# Team Briefing — <YYYY-MM-DD> (last <N> days)

---

## System Health

- **Total Entries:** <N>
- **DB Size:** <size>
- **Embedding Model:** <model>
- **Review Queue:** <N> entries pending classification
- **Active Users (last <N> days):** <N> (or "unavailable" if audit call failed)

---

## Team Activity

Found <M> of <total> internal entries from the last <N> days.

### By Author

| Author | Sessions | Minutes | Bookmarks | Total |
|--------|----------|---------|-----------|-------|
| <name> | <N>      | <N>     | <N>       | <N>   |

### Highlights

- **<Author>:** <1–2 sentence summary of key contributions and topics>
- **<Author>:** <1–2 sentence summary>

---

## Top Interests

| # | Topic | Tag Path |
|---|-------|----------|
| 1 | <topic> | <tag> |
| 2 | <topic> | <tag> |

---

## Feed Highlights

*Showing top signals matching team interests from the last <N> days.*

- **<title or snippet>** — <brief description> ([source](<url>))
- **<title or snippet>** — <brief description>

---

## Suggested Actions

- <action 1>
- <action 2>
```

## Rules

- Default lookback is 7 days — respect `--days` override
- Display-only — no `--store` flag, no storing of output
- Always call `distillery_metrics(scope="summary")` first; if it fails, stop (it is the MCP health check)
- `distillery_metrics(scope="audit")` failure is non-fatal — continue without audit data
- `distillery_interests` failure is non-fatal — omit Top Interests and Suggested Actions sections
- Feed Highlights failure is non-fatal — omit the section if search fails or returns nothing
- Only include `session`, `bookmark`, `minutes` in the internal activity list (not `feed`, `github`, `digest`)
- Omit empty sections — if no feed highlights, no top interests, no suggestions, omit those sections entirely
- Omit per-author rows with zero entries in the period
- Suggested Actions are concrete and actionable — include slash commands where applicable
- On MCP errors in fatal calls (summary metrics), see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
