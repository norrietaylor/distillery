# /classify — Reference: Help Text and Confidence Levels

## Mode D: Show Help (No Arguments)

Display:

```
## /classify — Classification & Review Queue

Usage:
  /classify <entry_id>          Classify a specific entry by its ID
  /classify --inbox             Classify all unclassified inbox entries in batch
  /classify --batch <filters>   Classify entries matching composable filters
  /classify --review            Triage the manual review queue

Batch Filters (--batch mode, AND semantics, at least one required):
  --source <source>       Filter by entry source (claude-code, manual, import, etc.)
  --entry-type <type>     Filter by entry type (inbox, github, feed, session, etc.)
  --author <name>         Filter by author name
  --tag-prefix <prefix>   Filter by tag namespace prefix
  --project <name>        Filter by project name
  --unclassified          Filter to entries with no tags and unverified status

Global Flags:
  --project <name>        Filter by project (available in all modes)

Examples:
  /classify 550e8400-e29b-41d4-a716-446655440000
  /classify --inbox
  /classify --batch --entry-type github
  /classify --batch --source external --unclassified
  /classify --batch --entry-type feed --project my-project
  /classify --review

Confidence Levels:
  high    >= 80%   Entry is classified automatically as active
  medium  50–79%   Entry may require review depending on threshold settings
  low     < 50%    Entry is sent to the review queue for manual triage
```

## Confidence Levels

| Score Range | Display | Level |
|-------------|---------|-------|
| 0.80–1.00 | e.g. `85%` | `high` |
| 0.50–0.79 | e.g. `65%` | `medium` |
| 0.00–0.49 | e.g. `45%` | `low` |

Format: `<n%> (<level>)`.

Valid entry types: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`, `person`, `project`, `digest`, `github`, `feed`.
