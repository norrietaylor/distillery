# /distill — Session Knowledge Capture

Captures decisions, architectural insights, and action items from a working session and stores them as knowledge entries.

## Usage

```text
/distill
/distill "We decided to use DuckDB for local storage"
```

**Trigger phrases:** "capture this", "save knowledge", "log learnings", "distill this session"

## When to Use

- At the end of a productive working session
- When you've made a significant decision worth preserving
- When a user explicitly asks to capture or save knowledge

## How It Works

1. **Gathers content** from the current conversation — decisions, insights, action items
2. **Constructs a distilled summary** (not a raw dump of the conversation)
3. **Checks for duplicates** using semantic similarity:
    - **Skip** (>= 95% similar) — near-duplicate exists, don't store
    - **Merge** (>= 80%) — combine with existing entry
    - **Link** (>= 60%) — store with cross-reference to related entry
    - **Create** (< 60%) — store as new entry
4. **Shows a preview** and asks for confirmation before storing
5. **Extracts tags** automatically from the content (2-5 keywords)
6. **Stores** the entry and confirms with the entry ID

## Options

| Option | Description |
|--------|-------------|
| Content as argument | Provide the knowledge to capture directly |
| `#tag` | Add explicit tags (merged with auto-extracted tags) |

## Output

### Preview (before storing)

A markdown preview of the distilled entry including title, content summary, tags, and deduplication results. You're asked to confirm before storing.

### Confirmation (after storing)

```text
Stored: <entry-id>
Summary: <first line of content>
Tags: domain/caching, project/distillery/decisions
```

## Tips

- Don't use `/distill` to dump raw conversation — it produces a **distilled summary** of the key insights
- Each invocation generates a unique session ID for traceability
- If a near-duplicate is found, you choose whether to skip, merge, or create a new entry
