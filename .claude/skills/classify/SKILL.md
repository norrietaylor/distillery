---
name: classify
description: "Classifies knowledge entries and manages the manual review queue. Triggered by: 'classify', 'classify entry', 'review queue', 'triage inbox', or '/classify [entry_id|--inbox|--review]'."
---

# Classify — Manual Classification & Review Queue

Classify runs the classification engine on knowledge entries and lets you triage the review queue for low-confidence predictions.

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- When you want to classify a specific entry by ID: `/classify <entry_id>`
- When you want to classify all unclassified inbox entries in batch: `/classify --inbox`
- When you want to triage entries awaiting human review: `/classify --review`
- When invoked with no arguments, the skill shows usage help

## Process

### Step 1: Check MCP Availability

Call `distillery_status` to confirm the Distillery MCP server is running.

If the tool is unavailable or returns an error, display:

```
Warning: Distillery MCP Server Not Available

The Distillery MCP server is not configured or not running.

To set up the server:
1. Ensure Distillery is installed: https://github.com/norrie-distillery/distillery
2. Configure the server in your Claude Code settings: see docs/mcp-setup.md
3. Restart Claude Code or reload MCP servers

For detailed setup instructions, see: docs/mcp-setup.md
```

Stop here if MCP is unavailable.

### Step 2: Dispatch to Mode

Parse the invocation arguments to determine the mode:

| Invocation | Mode |
|------------|------|
| `/classify <entry_id>` | Classify by ID |
| `/classify --inbox` | Batch inbox classification |
| `/classify --review` | Review queue triage |
| `/classify` (no args) | Show help |

---

## Mode A: Classify by ID

*Invoked as `/classify <entry_id>`*

### Step A1: Retrieve and Classify the Entry

Call `distillery_classify` with the provided entry ID. The skill does **not** run its own classification engine — it calls the MCP tool which applies the server-side classifier:

```
distillery_classify(
  entry_id="<provided entry_id>",
  entry_type="<predicted type>",
  confidence=<confidence score>,
  reasoning="<classification reasoning>",
  suggested_tags=["<tag1>", "<tag2>", ...]
)
```

**Note:** The MCP server's `distillery_classify` tool accepts a pre-computed classification. Before calling it, the skill must first retrieve the entry using `distillery_get` to inspect the content, then compute the classification. Use your own language-model understanding of the content to determine:
- `entry_type`: The most fitting type from: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`
- `confidence`: A score between 0.0 and 1.0 based on how clearly the content fits the type
- `reasoning`: A concise explanation of why this type was chosen
- `suggested_tags`: 2–5 relevant keywords extracted from the content

If `distillery_get` returns an error (entry not found), display:

```
Error: Entry "<entry_id>" was not found.

Check the entry ID and try again, or use /recall to search for entries by content.
```

### Step A2: Display Classification Result

Format the classification result. If the entry was previously classified, show the comparison.

**For a new classification:**

```
## Classification Result

Entry: <entry_id>
Type: <entry_type>
Confidence: <confidence%> (<high|medium|low>)
Status: <active|pending_review>

Reasoning: <reasoning text>

Suggested Tags: <tag1>, <tag2>, ...
```

**For a reclassification** (entry previously had a classification):

```
## Reclassification Result

Entry: <entry_id>

Previous Classification:
  Type: <old_type> | Confidence: <old_confidence%> (<level>)

New Classification:
  Type: <new_type> | Confidence: <new_confidence%> (<level>)

Reasoning: <reasoning text>

Suggested Tags: <tag1>, <tag2>, ...
```

**If the entry was sent to the review queue** (confidence below threshold):

Add a note after the result:

```
Note: Confidence is below the review threshold. This entry has been added to the
review queue for manual triage. Use `/classify --review` to process the queue.
```

---

## Mode B: Batch Inbox Classification

*Invoked as `/classify --inbox`*

### Step B1: List Inbox Entries

Call `distillery_list` filtered to `entry_type=inbox`:

```
distillery_list(
  filters={"entry_type": "inbox"},
  limit=50
)
```

If no entries are returned, display:

```
No inbox entries found to classify.

Inbox entries are created when content is stored without a specific type,
or when entries are waiting to be categorised. Use /distill to add new entries.
```

Stop here if no inbox entries are found.

### Step B2: Classify Each Entry

For each inbox entry, call `distillery_classify` with a classification computed from the entry's content. Process entries sequentially, up to a maximum of 50 per batch.

For each entry, determine:
- `entry_type`: best-fitting type based on content
- `confidence`: classification confidence (0.0–1.0)
- `reasoning`: brief explanation
- `suggested_tags`: 2–5 keywords

Track results in these counters:
- `classified_count` — entries assigned a type with confidence above threshold (status: active)
- `review_count` — entries below threshold sent to review queue (status: pending_review)
- `error_count` — entries that failed to classify (MCP error)

### Step B3: Display Batch Summary

Display a markdown table followed by totals:

```
## Batch Classification Complete

| Entry ID | Preview | Type | Confidence | Status |
|----------|---------|------|------------|--------|
| <id>     | <first 60 chars of content>... | <type> | <n%> (<level>) | <active|review|error> |

---
Total: <N> entries processed
- Classified (active): <classified_count>
- Sent to review queue: <review_count>
- Errors: <error_count>
```

If `review_count > 0`, add:

```
Use `/classify --review` to triage the <review_count> entries awaiting review.
```

---

## Mode C: Review Queue Triage

*Invoked as `/classify --review`*

### Step C1: Fetch the Review Queue

Call `distillery_review_queue` to retrieve all pending review entries:

```
distillery_review_queue(
  limit=20
)
```

If the queue is empty, display:

```
The review queue is empty. No entries are awaiting manual triage.
```

Stop here if the queue is empty.

### Step C2: Determine Reviewer Identity

Determine the reviewer identifier using this priority order:

1. Run `git config user.name` — use the result if non-empty
2. Check the `DISTILLERY_AUTHOR` environment variable — use it if set
3. Ask the user: "What is your name (for reviewer attribution)?"

Cache the reviewer name for the remainder of the session.

### Step C3: Display Queue and Triage Each Entry

For each entry in the queue, display:

```
---

## Review Entry <N> of <total>

ID: <entry_id>
Type: <entry_type> | Confidence: <confidence%> (<level>)
Author: <author> | Created: <created_at>
Reasoning: <classification_reasoning>

Content Preview:
> <content preview, up to 200 chars>

Action? Enter:
  a  — approve (keep this classification as active)
  r  — reclassify (assign a different type)
  x  — archive (remove from the knowledge base)
  s  — skip (leave in review queue for now)
>
```

**If the user enters `a` (approve):**

Call `distillery_resolve_review`:

```
distillery_resolve_review(
  entry_id="<entry_id>",
  action="approve",
  reviewer="<reviewer name>"
)
```

Confirm: `Approved. Entry <entry_id> is now active.`

**If the user enters `r` (reclassify):**

Prompt for the new type:

```
Enter new type (session, bookmark, minutes, meeting, reference, idea, inbox):
>
```

Validate the input against the list of valid types. If invalid, show the list and re-prompt once. Then call:

```
distillery_resolve_review(
  entry_id="<entry_id>",
  action="reclassify",
  new_entry_type="<chosen type>",
  reviewer="<reviewer name>"
)
```

Confirm: `Reclassified. Entry <entry_id> updated to type "<chosen_type>" and is now active.`

**If the user enters `x` (archive):**

Call `distillery_resolve_review`:

```
distillery_resolve_review(
  entry_id="<entry_id>",
  action="archive",
  reviewer="<reviewer name>"
)
```

Confirm: `Archived. Entry <entry_id> has been removed from the knowledge base.`

**If the user enters `s` (skip):**

Confirm: `Skipped. Entry <entry_id> remains in the review queue.`

Continue to the next entry.

### Step C4: Display Triage Summary

After all entries have been processed (or the user has worked through the queue), display:

```
## Review Queue Summary

Entries reviewed: <total processed>
- Approved: <approved_count>
- Reclassified: <reclassified_count>
- Archived: <archived_count>
- Skipped: <skipped_count>
```

---

## Mode D: Show Help (No Arguments)

*Invoked as `/classify` with no arguments*

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

## Output Format

### Confidence Formatting

Always display confidence as a percentage with a level label:

| Score Range | Percentage Display | Level Label |
|-------------|-------------------|-------------|
| 0.80 – 1.00 | e.g., `85%` | `high` |
| 0.50 – 0.79 | e.g., `65%` | `medium` |
| 0.00 – 0.49 | e.g., `45%` | `low` |

Format: `<n%> (<level>)` — for example, `85% (high)`, `65% (medium)`, `45% (low)`.

### Provenance Line

When displaying individual classified entries, always include a provenance line:

```
ID: <entry_id> | Author: <author> | Project: <project> | <created_at>
```

### Entry Type Values

Valid entry types are: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`.

---

## Rules

- Always check MCP availability before any other action — stop immediately if unavailable
- Show usage help when `/classify` is invoked with no arguments
- When classifying by ID, retrieve the entry first with `distillery_get` to read its content before calling `distillery_classify`
- Display confidence as a percentage with a high/medium/low level label in all output
- For reclassifications, always show the old classification alongside the new one
- Note when an entry is sent to the review queue due to low confidence
- In batch mode, process a maximum of 50 inbox entries per invocation to avoid timeouts
- In review mode, process entries one at a time with explicit user confirmation per entry
- Accept `s` to skip an entry in review mode — do not force the user to make a decision
- Validate reclassify type input — show valid types and re-prompt once if invalid
- Display a summary table and totals after batch classification
- Display a summary after completing review queue triage
- Never skip the triage summary after review mode — it confirms what was done
- If an MCP tool returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "Entry not found" → Check the entry ID and use /recall to search
- If "Invalid entry type" → Choose from: session, bookmark, minutes, meeting, reference, idea, inbox
- If "Database error" → Ensure the database path is writable and the file exists
- If "API key invalid" → Re-check the embedding provider API key in your config
```

- Do not enter infinite retry loops — if a tool fails after one retry, report the error and continue to the next entry
- Always use the reviewer name (from git config, env var, or user prompt) when calling `distillery_resolve_review`
