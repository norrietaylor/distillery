---
name: recall
description: "Performs semantic search over the Distillery knowledge base. Triggered by: 'recall', 'search knowledge', 'what do we know about', 'find in knowledge base', or '/recall <query>'."
---

# Recall — Semantic Knowledge Search

Recall searches the Distillery knowledge base using natural language queries and returns ranked results with full provenance.

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- When you need to find relevant knowledge entries on a topic
- When searching for past decisions, discussions, or bookmarks
- When invoked via `/recall <query>` or phrases like "what do we know about X", "find in knowledge base"
- When filtering by type, author, or project is needed (e.g., `/recall caching --type session`)

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

### Step 2: Prompt for Query if None Provided

If `/recall` was invoked with no arguments, ask the user:

```
What would you like to search for in the knowledge base?
```

Wait for the user's response and use it as the query.

### Step 3: Parse Arguments and Filters

Parse the invocation arguments for optional filter flags. Flags may appear in any order:

| Flag | Parameter | Description |
|------|-----------|-------------|
| `--type` | `<entry_type>` | Filter by entry type (e.g., `session`, `bookmark`, `minutes`) |
| `--author` | `<name>` | Filter by author identifier |
| `--project` | `<name>` | Filter by project name |
| `--limit` | `<n>` | Override the default result limit (default: 10) |

The remaining text after removing all flags and their values is the query string.

**Example parsing:**

```
/recall caching --type session --author Alice --limit 5
  → query: "caching"
  → filters: type=session, author=Alice
  → limit: 5
```

Valid `entry_type` values: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`.

### Step 4: Search the Knowledge Base

Call `distillery_search` with the parsed query, limit, and any filters:

```
distillery_search(
  query="<parsed query text>",
  limit=<limit, default 10>,
  entry_type="<type filter if provided>",
  author="<author filter if provided>",
  project="<project filter if provided>"
)
```

Only include filter parameters that were explicitly provided. Do not pass empty or null values for unused filters.

### Step 5: Display Results

If results are returned, display each result using the Output Format below.

If no results are found, display:

```
No results found for "<query>".

Suggestions:
- Try broader or different search terms
- Remove filters (--type, --author, --project) to widen the search
- Check that the Distillery knowledge base contains entries on this topic
```

## Output Format

For each result (ordered by similarity score, highest first):

```
## <similarity_score>% — [<entry_type>]

<full content of the entry>

ID: <entry_id> | Author: <author> | Project: <project> | <created_at>
Tags: <tag1>, <tag2>, ...
```

**Field details:**

- **Similarity score** — Displayed as a percentage (e.g., `87%`). Round to the nearest whole number.
- **Entry type badge** — Displayed in square brackets (e.g., `[session]`, `[bookmark]`, `[minutes]`).
- **Full content** — The complete content of the entry, not truncated.
- **Provenance line** — Always on its own line immediately after the content:
  `ID: <id> | Author: <author> | Project: <project> | <created_at>`
- **Tags** — Display only if the entry has tags. Omit the Tags line entirely if no tags are present.

**Example result:**

```
## 92% — [session]

We decided to use DuckDB for local storage because it requires no separate server process,
supports SQL queries, and has excellent Python bindings. SQLite was considered but lacks
the columnar storage benefits needed for our embedding queries.

ID: 550e8400-e29b-41d4-a716-446655440000 | Author: Alice Smith | Project: distillery | 2026-03-22
Tags: storage-decision, duckdb, architecture
```

**When multiple results are found:**

Display a header showing the total count and query before listing results:

```
Found <count> result(s) for "<query>"<filter_summary>:

---

## 92% — [session]
...

---

## 87% — [bookmark]
...
```

Where `<filter_summary>` summarises active filters, e.g., ` (type: session, author: Alice)`, or is omitted if no filters were applied.

**When no results are found:**

```
No results found for "<query>".

Suggestions:
- Try broader or different search terms
- Remove filters to widen the search
- Check that the Distillery knowledge base contains entries on this topic
```

## Rules

- Always show provenance for every result — ID, author, project, and created_at are mandatory
- Default limit is 10; respect the `--limit` override if provided
- Parse filter flags before treating remaining text as the query string
- Do not include unused filter parameters in the `distillery_search` call
- Display results in order of similarity score (highest first, as returned by the API)
- Show the full entry content — do not truncate
- Omit the Tags line for entries with no tags; do not show `Tags: (none)`
- If MCP is unavailable, display the setup message and stop immediately
- If `distillery_search` returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "API key invalid" → Re-check the embedding provider API key in your config
- If "Database error" → Ensure the database path is writable and the file exists
- If "Search failed" → Try a simpler query or check the MCP server logs
```

- Do not enter infinite retry loops — if search fails after one retry, report the error and stop
- Valid entry types for `--type` filter: `session`, `bookmark`, `minutes`, `meeting`, `reference`, `idea`, `inbox`
- If `--type` is given an invalid value, display a helpful message listing valid types before calling the API
