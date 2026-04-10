---
name: digest
description: "Generate a structured summary of internal team activity over a time window"
allowed-tools:
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_find_similar"
  - "mcp__*__distillery_update"
context: fork
effort: high
---

<!-- Trigger phrases: digest, /digest, team digest, activity summary, what did the team capture, weekly digest, team activity -->

# Digest — Team Activity Summaries

Digest generates structured summaries of internal team knowledge activity — sessions, bookmarks, meeting notes, ideas, and references — over a configurable time window. Unlike `/radar`, which surfaces external feed signals, Digest focuses on what the team itself has captured.

## When to Use

- Weekly or periodic team activity reviews (`/digest`)
- Tracking knowledge growth across the team (`/digest --days 14`)
- Scoping activity to a specific project (`/digest --project distillery`)
- Storing the summary as a knowledge entry (`/digest --store`)
- "What did the team capture this week", "team digest", "activity summary"

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

| Flag | Description |
|------|-------------|
| `--days N` | Look back N days for activity (default: 7) |
| `--project <name>` | Scope results to a specific project |
| `--store` | Store the digest as a knowledge entry (default: display-only) |

Compute `date_from` as today's date minus N days in ISO 8601 format (`YYYY-MM-DD`).

### Step 3: Retrieve Internal Entries

Retrieve internal team entries, explicitly excluding feed, github, and digest types.

**3a. Fetch entries:**

```python
distillery_list(
    entry_type=["session", "bookmark", "minutes", "idea", "reference"],
    limit=100,
    date_from=<date_from>,
    output_mode="full",
    # project=<name>  # only if --project specified
)
```

If `--project` was specified, pass `project=<name>` to scope results.

Note the `total_count` field from the response. Report: `Summarizing <len(entries)> of <total_count> entries from the last <N> days.`

If no entries found, display:

```
No internal entries found in the last <N> days.

Suggestions:
- Capture session knowledge with /distill
- Record a meeting with /minutes
- Save a bookmark with /bookmark
```

Stop here if no entries exist.

**3b. Fetch per-author activity counts:**

```python
distillery_list(
    group_by="author",
    date_from=<date_from>,
    # project=<name>  # only if --project specified
)
```

**3c. Fetch entry type distribution:**

```python
distillery_list(
    group_by="entry_type",
    date_from=<date_from>,
    # project=<name>  # only if --project specified
)
```

### Step 4: Synthesize Digest

You (the executing Claude instance) produce the synthesis. Do not dump raw entries.

**Per-Author Activity:**

For each author with entries, summarize their contributions: how many of each type, notable topics from tag analysis, and any decisions or action items surfaced from their `minutes` or `session` entries.

**Top Topics:**

Aggregate tags across all entries. Identify the top 5–10 tags by frequency. Present as a ranked list with entry count per topic.

**Key Decisions:**

Scan `minutes` and `session` entries for decision-related keywords: "decided", "decision", "agreed", "resolved", "chosen", "approved", "will use", "going with". Extract and list the most significant decisions with their source entry type and author.

**Entry Counts:**

Tabulate entries by type using the `distillery_list(group_by=...)` responses from Steps 3b and 3c. Show counts per type and per author in compact tables.

### Step 5: Check for Duplicates (if --store specified)

If `--store` was not specified, skip to Step 7.

Call `distillery_find_similar(content="<digest summary text>", dedup_action=True)`. Handle by `action` field per CONVENTIONS.md:

**`"create"`:** No similar entries. Proceed to Step 6.

**`"skip"`:** Near-exact duplicate. Show similarity table and offer: (1) Store anyway, (2) Skip.

**`"merge"`:** Very similar entry exists. Show similarity table and offer: (1) Store anyway, (2) Merge with existing, (3) Skip.

For merge: combine new digest with the most similar entry's content, call `distillery_update` with the entry ID and merged content, confirm and stop.

**`"link"`:** Related but distinct. Show similarity table, note new entry will be linked. Ask to proceed or skip. If proceeding, include `"related_entries": ["<id1>", ...]` in metadata at Step 6.

```
Similar entries found:

| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| <id>     | <score%>  | <content_preview> |
```

On skip in any case: "Skipped. No new entry was stored." and stop.

### Step 6: Store Digest (if --store specified)

Determine author & project per CONVENTIONS.md. Compute `period_start` and `period_end` as ISO 8601 dates.

```python
distillery_store(
    content="<full digest markdown>",
    entry_type="digest",
    author="<author>",
    project="<project>",
    tags=["digest", "team-activity", "internal"],
    metadata={
        "period_start": "<YYYY-MM-DD>",
        "period_end": "<YYYY-MM-DD>",
        "entry_count": <N>,
        "authors": ["<author1>", ...],
        "sources": ["session", "bookmark", "minutes", "idea", "reference"]
    }
)
```

On MCP errors, see CONVENTIONS.md error handling — display and stop.

### Step 7: Confirm

Display the digest. If `--store` was specified, append the standard confirmation:

```
[digest] Stored: <entry_id>
Project: <project> | Author: <author>
Summary: <first 200 chars of digest>...
Tags: digest, team-activity, internal
```

Omit the stored block if `--store` was not specified.

## Output Format

```
# Team Digest — <YYYY-MM-DD> (last <N> days)

Summarizing <M> of <total> entries from the last <N> days.

---

## Per-Author Activity

### <Author Name> — <N> entries

- **Sessions (<N>):** <brief summary of themes>
- **Minutes (<N>):** <topics covered>
- **Bookmarks (<N>):** <subject areas>

---

## Top Topics

| # | Tag | Entries |
|---|-----|---------|
| 1 | <tag> | <N> |
| 2 | <tag> | <N> |

---

## Key Decisions

- **<Decision summary>** — <author>, <entry_type>, <date>
- **<Decision summary>** — <author>, <entry_type>, <date>

---

## Entry Counts

### By Type

| Type | Count |
|------|-------|
| session | <N> |
| minutes | <N> |
| bookmark | <N> |
| idea | <N> |
| reference | <N> |

### By Author

| Author | Count |
|--------|-------|
| <name> | <N> |

---

[digest] Stored: <entry_id>
Project: <project> | Author: <author>
Summary: <first 200 chars>...
Tags: digest, team-activity, internal
```

## Rules

- Default lookback is 7 days — respect `--days` override
- Only include `session`, `bookmark`, `minutes`, `idea`, `reference` entry types — never `feed`, `github`, or `digest`
- Display digest by default; store only with `--store` flag
- Always include `digest`, `team-activity`, `internal` tags when storing
- Always use `entry_type="digest"` for store calls
- Metadata must include `period_start` and `period_end` as ISO 8601 dates
- Report "Summarizing N of M entries" using `total_count` from `distillery_list`
- Key Decisions section: only include entries with explicit decision language; omit section if none found
- Omit empty per-author sections (authors with zero entries in window)
- Follow shared dedup pattern from CONVENTIONS.md (create/skip/merge/link outcomes) when `--store` is specified
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
- `distillery_list(group_by=...)` failures are non-fatal — omit the affected breakdown section and continue
