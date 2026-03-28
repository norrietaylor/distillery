---
name: radar
description: "Generates an ambient intelligence digest from recent feed entries, suggests new sources, and stores the digest. Triggered by: 'radar', '/radar', 'what's new', 'show my digest', 'ambient digest', 'what have I missed', 'feed digest'."
---

# Radar -- Ambient Intelligence Digest

Radar surfaces recent feed entries from the knowledge base, synthesizes them into a digest, and suggests new sources to watch based on your interests.

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- When you want a digest of recent feed items (`/radar`)
- When you want to see what has been captured from monitored sources recently
- When you want new source suggestions aligned to your interests (`/radar --suggest`)
- When asked to "show my digest", "what's new from feeds", or "what have I missed"

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

### Step 2: Parse Arguments

Parse optional arguments from the invocation:

| Flag | Description |
|------|-------------|
| `--days N` | Look back N days for recent feed entries (default: 7) |
| `--limit N` | Maximum number of feed entries to include (default: 20) |
| `--suggest` | Include source suggestions at end of digest |
| `--no-store` | Display digest but do not store it as a knowledge entry |

If no arguments are provided, use the defaults.

### Step 3: Retrieve Recent Feed Entries

Call `distillery_list` filtered to entry type `feed`, ordered by recency:

```
distillery_list(
  entry_type="feed",
  limit=<limit, default 20>
)
```

If `--days N` was specified, also pass `date_from` as an ISO 8601 date N days before today (e.g., if today is 2026-03-27 and `--days 7`, pass `date_from="2026-03-20"`).

### Step 4: Synthesize Digest

Using the retrieved feed entries, synthesize a digest. You (the Claude instance executing this skill) are responsible for producing the synthesis.

**Grouping:** Group entries by their source tag if present (e.g., `source/github`, `source/rss`), or by topic if no source tag is available.

**For each group, produce:**

- A heading with the group name
- A 2-4 sentence summary of the key themes and items in that group
- A bullet list of the most notable items (title/snippet + source URL if available in metadata)

**Cross-group summary:** After all groups, write a 2-3 sentence overall summary highlighting the most important or interesting signals across all sources.

If no feed entries are found, display:

```
No feed entries found in the last <N> days.

Suggestions:
- Run distillery_poll to fetch new items from configured sources
- Add sources with /watch add <url>
- Check that feed sources are configured in distillery.yaml
```

Stop here (do not store or suggest) if no feed entries exist.

### Step 5: Suggest Sources (if --suggest flag or digest has entries)

Call `distillery_suggest_sources` to get source recommendations:

```
distillery_suggest_sources(
  max_suggestions=5
)
```

Include the suggestions section in the digest output (see Output Format).

If `distillery_suggest_sources` returns an error or empty suggestions, omit the suggestions section silently.

### Step 6: Store Digest

Unless `--no-store` was specified, store the digest as a knowledge entry.

First determine the author:
- Try `git config user.name`
- Try `DISTILLERY_AUTHOR` environment variable
- If neither is set, ask: "What is your name (for author attribution)?"

Call `distillery_store` with the full digest content:

```
distillery_store(
  content="<full digest markdown text>",
  entry_type="feed",
  author="<author>",
  tags=["digest", "radar", "ambient"]
)
```

Record the returned `entry_id` for the confirmation message.

### Step 7: Confirm

Display the digest output (see Output Format), followed by a confirmation:

```
Digest stored: <entry_id>
```

If `--no-store` was used, omit the "Digest stored" line.

## Output Format

```
# Radar Digest — <YYYY-MM-DD>

<N> feed entries from the last <days> days.

---

## <Group Name>

<2-4 sentence summary of the group>

- **<item title>** — <brief description> ([source](<url if available>))
- ...

---

## <Next Group Name>

...

---

## Overall Summary

<2-3 sentence cross-group synthesis>

---

## Suggested Sources

| # | URL | Type | Why |
|---|-----|------|-----|
| 1 | <url> | <type> | <rationale> |
| 2 | ... | ... | ... |

To add a source: /watch add <url> [--type rss|github]

---

Digest stored: <entry_id>
```

**When no feed entries are found:**

```
No feed entries found in the last <N> days.

Suggestions:
- Run distillery_poll to fetch new items from configured sources
- Add sources with /watch add <url>
- Check that feed sources are configured in distillery.yaml
```

## Rules

- Always call `distillery_status` first to verify MCP availability
- Default lookback window is 7 days; respect `--days` override if provided
- Default entry limit is 20; respect `--limit` override if provided
- You (the executing Claude instance) produce the synthesis -- do not show raw entry dumps
- Group entries by source tag when available; fall back to topic grouping
- Store the digest by default; skip storage only when `--no-store` is specified
- Always include `digest`, `radar`, and `ambient` tags when storing
- Include source suggestions when `--suggest` is specified; also include them when entries are found (to help the user discover new sources)
- If `distillery_list` returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "Database error" -> Ensure the database path is writable and the file exists
- If "Connection error" -> Verify the Distillery MCP server is running
```

- If `distillery_store` returns an error, display it clearly and inform the user the digest was not saved
- Do not enter infinite retry loops -- if a call fails, report the error and stop
- Omit the Suggested Sources section entirely if `distillery_suggest_sources` returns no results or an error
