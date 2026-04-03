# /classify — Reference: Help Text and Confidence Levels

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

## Confidence Levels

| Score Range | Display | Level |
|-------------|---------|-------|
| 0.80–1.00 | e.g. `85%` | `high` |
| 0.50–0.79 | e.g. `65%` | `medium` |
| 0.00–0.49 | e.g. `45%` | `low` |

Format: `<n%> (<level>)`.

Valid entry types: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`.
