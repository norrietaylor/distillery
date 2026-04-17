---
name: classify
description: "Classify knowledge entries by type and manage the manual review queue"
allowed-tools:
  - "mcp__*__distillery_classify"
  - "mcp__*__distillery_resolve_review"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_metrics"
effort: medium
---

<!-- Trigger phrases: classify, classify entry, review queue, triage inbox, /classify [entry_id|--inbox|--batch|--review] -->

# Classify — Manual Classification & Review Queue

Classify runs the classification engine on knowledge entries and lets you triage the review queue for low-confidence predictions.

## When to Use

- `/classify <entry_id>` — classify a specific entry by ID
- `/classify --inbox` — classify all unclassified inbox entries in batch (alias for `--batch --entry-type inbox`)
- `/classify --batch <filters>` — classify entries matching composable filters in batch
- `/classify --review` — triage entries awaiting human review
- `/classify` (no args) — show usage help

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Dispatch to Mode

| Invocation | Mode |
|------------|------|
| `/classify <entry_id>` | Classify by ID |
| `/classify --inbox` | Batch inbox classification (alias for `--batch --entry-type inbox`) |
| `/classify --batch <filters>` | Batch classification with composable filters |
| `/classify --review` | Review queue triage |
| `/classify` (no args) | Show help |

**Optional flags (all modes):**

| Flag | Parameter | Description |
|------|-----------|-------------|
| `--project` | `<name>` | Filter by project name |

**Batch filter flags (`--batch` mode only):**

| Flag | Parameter | Description |
|------|-----------|-------------|
| `--source` | `<source>` | Filter by entry source (e.g. `claude-code`, `manual`, `import`, `inference`, `external`) |
| `--entry-type` | `<type>` | Filter by entry type (e.g. `inbox`, `github`, `feed`, `session`, etc.) |
| `--author` | `<name>` | Filter by author name |
| `--tag-prefix` | `<prefix>` | Filter by tag namespace prefix (e.g. `project/billing`) |
| `--project` | `<name>` | Filter by project name |
| `--unclassified` | *(none)* | Filter to entries with no tags and verification=unverified |

Filters are composable with AND semantics. At least one filter is required when using `--batch` (reject bare `--batch` with no filters).

---

## Mode A: Classify by ID

### Step A1: Retrieve and Classify

1. Call `distillery_get` to retrieve the entry. If not found, tell the user to check the ID or use `/recall`.
2. Analyse the content and determine:
   - `entry_type`: best fit from `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`
   - `confidence`: 0.0–1.0 based on how clearly the content fits
   - `reasoning`: concise explanation
   - `suggested_tags`: 2–5 keywords
3. Call `distillery_classify` with those values.

- On MCP errors, see CONVENTIONS.md error handling — display and stop.

### Step A2: Display Result

Show entry ID, type, confidence (as `<n%> (<level>)`), status, reasoning, and suggested tags. For reclassifications, show old and new classification side-by-side. If confidence is below threshold, note the entry was sent to the review queue.

---

## Mode B: Batch Inbox Classification

`--inbox` is a convenience alias for `--batch --entry-type inbox`. It follows the same process as Mode B2 below with `entry_type="inbox"` pre-set.

### Step B1: List Inbox Entries

Call `distillery_list(entry_type="inbox", limit=50, output_mode="full", content_max_length=300)`. If `--project` was specified, also pass `project=<name>`. If empty, tell the user and stop.

### Step B2: Classify Each Entry

For each entry (max 50), compute classification as in Mode A and call `distillery_classify`. Track counts: `classified` (active), `review` (pending_review), `errors`.

### Step B3: Display Batch Summary

```
## Batch Classification Complete

| Entry ID | Preview | Type | Confidence | Status |
|----------|---------|------|------------|--------|
| <id>     | <first 60 chars>... | <type> | <n%> (<level>) | <active|review|error> |

Total: <N> processed — <classified> active, <review> review, <errors> errors
```

If any sent to review, suggest `/classify --review`.

---

## Mode B2: Batch Classification with Filters

### Step B2-1: Validate Filters

1. At least one filter flag must be present. If the user passed bare `--batch` with no filters, display an error: "At least one filter is required for --batch mode. See `/classify` for available filters." and stop.
2. Build the `distillery_list` arguments from the provided filters:

| Flag | `distillery_list` parameter |
|------|----------------------------|
| `--source` | `source=<value>` |
| `--entry-type` | `entry_type=<value>` |
| `--author` | `author=<value>` |
| `--tag-prefix` | `tag_prefix=<value>` |
| `--project` | `project=<value>` |
| `--unclassified` | `verification="unverified"` (the empty-tags constraint is checked post-fetch in Step B2-2) |

### Step B2-2: List Matching Entries

Call `distillery_list` with the composed filters, plus `limit=50, output_mode="full", content_max_length=300`. If empty, tell the user no entries matched the filters and stop.

If `--unclassified` was specified, additionally filter the returned entries to only those with `tags=[]` (empty tags list). This is a post-fetch filter since the store does not support empty-tag queries directly.

### Step B2-3: Classify Each Entry

For each entry (max 50), compute classification as in Mode A and call `distillery_classify`. Track counts: `classified` (active), `review` (pending_review), `errors`.

### Step B2-4: Display Batch Summary

Use the same summary table format as Mode B Step B3.

---

## Mode C: Review Queue Triage

### Step C1: Fetch the Review Queue

Call `distillery_list(status="pending_review", output_mode="review", limit=20)`. If `--project` was specified, also pass `project=<name>`. If empty, tell the user and stop.

### Step C2: Determine Reviewer

Determine reviewer per CONVENTIONS.md author resolution.

### Step C3: Triage Each Entry

For each entry, display: ID, type, confidence, author, date, reasoning, and a 200-char content preview. Prompt for action:

| Key | Action | MCP Call |
|-----|--------|----------|
| `a` | Approve — keep classification, set active | `distillery_resolve_review(action="approve")` |
| `r` | Reclassify — prompt for new type, validate against valid types (re-prompt once if invalid) | `distillery_resolve_review(action="reclassify", new_entry_type=...)` |
| `x` | Archive — remove from knowledge base | `distillery_resolve_review(action="archive")` |
| `s` | Skip — leave in queue | No MCP call |

Always pass the reviewer name when calling `distillery_resolve_review`.

### Step C4: Display Triage Summary

```
## Review Queue Summary

Entries reviewed: <total>
- Approved: <n>  |  Reclassified: <n>  |  Archived: <n>  |  Skipped: <n>
```

---

## Mode D: Show Help (No Arguments)

Read `references/modes.md` for the help text to display.

---

## Rules

- Always check MCP availability first — stop if unavailable
- Show help when invoked with no arguments
- Retrieve the entry with `distillery_get` before classifying by ID
- Display confidence as percentage with level label in all output (see `references/modes.md` for level thresholds)
- For reclassifications, show old and new classification together
- Batch mode: max 50 entries per invocation
- Review mode: one entry at a time, accept `s` to skip
- Validate reclassify type input; re-prompt once if invalid
- Always show a summary after batch or review operations
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — if a tool fails, report and continue to the next entry
