---
name: classify
description: "Classify knowledge entries by type and manage the manual review queue"
allowed-tools:
  - "mcp__*__distillery_classify"
  - "mcp__*__distillery_review_queue"
  - "mcp__*__distillery_resolve_review"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_status"
effort: medium
---

<!-- Trigger phrases: classify, classify entry, review queue, triage inbox, /classify [entry_id|--inbox|--review] -->

# Classify — Manual Classification & Review Queue

Classify runs the classification engine on knowledge entries and lets you triage the review queue for low-confidence predictions.

## When to Use

- `/classify <entry_id>` — classify a specific entry by ID
- `/classify --inbox` — classify all unclassified inbox entries in batch
- `/classify --review` — triage entries awaiting human review
- `/classify` (no args) — show usage help

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Dispatch to Mode

| Invocation | Mode |
|------------|------|
| `/classify <entry_id>` | Classify by ID |
| `/classify --inbox` | Batch inbox classification |
| `/classify --review` | Review queue triage |
| `/classify` (no args) | Show help |

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

### Step B1: List Inbox Entries

Call `distillery_list(entry_type="inbox", limit=50, output_mode="full", content_max_length=300)`. If empty, tell the user and stop.

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

## Mode C: Review Queue Triage

### Step C1: Fetch the Review Queue

Call `distillery_review_queue(limit=20)`. If empty, tell the user and stop.

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

Display:

```
## /classify — Classification & Review Queue

Usage:
  /classify <entry_id>    Classify a specific entry by its ID
  /classify --inbox       Classify all unclassified inbox entries in batch
  /classify --review      Triage the manual review queue

Examples:
  /classify 550e8400-e29b-41d4-a716-446655440000
  /classify --inbox
  /classify --review

Confidence Levels:
  high    >= 80%   Entry is classified automatically as active
  medium  50–79%   Entry may require review depending on threshold settings
  low     < 50%    Entry is sent to the review queue for manual triage
```

---

## Confidence Levels

| Score Range | Display | Level |
|-------------|---------|-------|
| 0.80–1.00 | e.g. `85%` | `high` |
| 0.50–0.79 | e.g. `65%` | `medium` |
| 0.00–0.49 | e.g. `45%` | `low` |

Format: `<n%> (<level>)`.

Valid entry types: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`.

---

## Rules

- Always check MCP availability first — stop if unavailable
- Show help when invoked with no arguments
- Retrieve the entry with `distillery_get` before classifying by ID
- Display confidence as percentage with level label in all output
- For reclassifications, show old and new classification together
- Batch mode: max 50 entries per invocation
- Review mode: one entry at a time, accept `s` to skip
- Validate reclassify type input; re-prompt once if invalid
- Always show a summary after batch or review operations
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — if a tool fails, report and continue to the next entry
