# /classify — Entry Classification

Runs the classification engine on knowledge entries and lets you triage the review queue for low-confidence predictions.

## Usage

```text
/classify <entry-id>       # Classify a specific entry
/classify --inbox          # Batch classify all inbox entries
/classify --review         # Triage the review queue
/classify                  # Show help
```

**Trigger phrases:** "classify", "classify entry", "review queue", "triage inbox"

## Modes

### Classify by ID

Classifies a specific entry and displays the result:

```text
Entry: a1b2c3d4
Type: session
Confidence: 92% (high)
Reasoning: Contains decisions and action items from a working session
Suggested tags: domain/caching, project/billing/decisions
```

### Batch Inbox (`--inbox`)

Classifies all entries with type `inbox` (up to 50 at a time). Results are displayed as a summary table:

| Entry ID | Preview | Type | Confidence | Status |
|----------|---------|------|------------|--------|
| a1b2c3d4 | "We decided to use..." | session | 92% (high) | classified |
| e5f6g7h8 | "Meeting with the..." | minutes | 45% (low) | needs review |

Entries with confidence below the `confidence_threshold` (default: 60%) are sent to the review queue.

### Review Queue (`--review`)

Interactive triage of entries pending manual review (up to 20 at a time). For each entry you see:

- Entry ID, suggested type, confidence, author, date
- Reasoning from the classifier
- First 200 characters of content

**Actions:**

| Key | Action | Description |
|-----|--------|-------------|
| `a` | Approve | Accept the suggested classification |
| `r` | Reclassify | Assign a different type (validates against valid types) |
| `x` | Archive | Archive the entry |
| `s` | Skip | Move to the next entry |

After triage, a summary shows counts: approved, reclassified, archived, skipped.

## Confidence Levels

| Level | Range | Meaning |
|-------|-------|---------|
| High | >= 80% | Confident classification, auto-applied |
| Medium | 60-79% | Reasonable guess, auto-applied |
| Low | < 60% | Below `confidence_threshold` (default), sent to review queue |

## Valid Entry Types

`session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`, `person`, `project`, `digest`, `github`, `feed`

## Tips

- Run `/classify --inbox` periodically to process unclassified entries
- The review queue shows one entry at a time for focused triage
- If you reclassify an entry with an invalid type, you're prompted once to correct it
