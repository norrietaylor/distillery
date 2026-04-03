---
name: recall
description: "Search the knowledge base using natural language and return matching entries with provenance"
allowed-tools:
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_metrics"
effort: low
model: haiku
---

<!-- Trigger phrases: recall, search knowledge, what do we know about, find in knowledge base, /recall <query> -->

# Recall — Semantic Knowledge Search

Recall searches the Distillery knowledge base using natural language queries and returns ranked results with full provenance.

## When to Use

- Finding relevant knowledge entries on a topic
- Searching past decisions, discussions, or bookmarks
- Invoked via `/recall <query>` or phrases like "what do we know about X"
- Filtering by type, author, or project (e.g., `/recall caching --type session`)

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Prompt for Query if None Provided

If `/recall` was invoked with no arguments, ask: "What would you like to search for in the knowledge base?" Wait for the response.

### Step 3: Parse Arguments and Filters

Parse invocation arguments for optional filter flags (any order):

| Flag | Parameter | Description |
|------|-----------|-------------|
| `--type` | `<entry_type>` | Filter by entry type (e.g., `session`, `bookmark`, `minutes`) |
| `--author` | `<name>` | Filter by author identifier |
| `--project` | `<name>` | Filter by project name |
| `--limit` | `<n>` | Override default result limit (default: 10) |

Remaining text after removing flags is the query string.

**Example:** `/recall caching --type session --author Alice --limit 5` → query: `"caching"`, filters: type=session, author=Alice, limit: 5

Valid `entry_type` values: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`.

### Step 4: Search the Knowledge Base

Call `distillery_search` with the parsed query, limit, and any filters. Only include filter parameters that were explicitly provided — do not pass empty or null values.

### Step 5: Display Results

If results are returned, display each using the Output Format below.

If no results found, display: `No results found for "<query>".` followed by suggestions to broaden terms, remove filters, or check that entries exist on the topic.

## Output Format

**Multiple results** — show a header first:

```
Found <count> result(s) for "<query>"<filter_summary>:
```

Where `<filter_summary>` summarises active filters (e.g., ` (type: session, author: Alice)`), omitted if none.

**Each result** (ordered by similarity, highest first):

```
## <similarity_score>% — [<entry_type>]

<full content of the entry>

ID: <entry_id> | Author: <author> | Project: <project> | <created_at>
Tags: <tag1>, <tag2>, ...
```

- **Similarity score** — percentage, rounded to nearest whole number
- **Entry type badge** — in square brackets (e.g., `[session]`)
- **Full content** — complete, never truncated
- **Provenance line** — always present: `ID: <id> | Author: <author> | Project: <project> | <created_at>`
- **Tags** — only if the entry has tags; omit the line entirely otherwise

Separate results with `---`.

## Rules

- Always show provenance (ID, author, project, created_at) for every result
- Default limit is 10; respect `--limit` override
- Parse filter flags before treating remaining text as the query
- Do not include unused filter parameters in the `distillery_search` call
- Show full entry content — do not truncate
- Omit the Tags line for entries with no tags; do not show `Tags: (none)`
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — if search fails, report and stop (per CONVENTIONS.md)
- If `--type` is given an invalid value, list valid types before calling the API
