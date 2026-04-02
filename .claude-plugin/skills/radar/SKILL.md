---
name: radar
description: "Generate an ambient intelligence digest from recent feed activity with source suggestions"
allowed-tools:
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_interests"
  - "mcp__*__distillery_suggest_sources"
  - "mcp__*__distillery_status"
context: fork
effort: high
---

<!-- Trigger phrases: radar, /radar, what's new, show my digest, ambient digest, what have I missed, feed digest -->

# Radar — Ambient Intelligence Digest

Radar surfaces recent feed entries, synthesizes them into a grouped digest, and suggests new sources to watch.

## When to Use

- Digest of recent feed items (`/radar`)
- See what has been captured from monitored sources recently
- New source suggestions (`/radar --suggest`)
- "show my digest", "what's new from feeds", "what have I missed"

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

| Flag | Description |
|------|-------------|
| `--days N` | Look back N days for recent feed entries (default: 7) |
| `--limit N` | Maximum number of feed entries to include (default: 20) |
| `--suggest` | Include source suggestions at end of digest |
| `--no-store` | Display digest but do not store it as a knowledge entry |

### Step 3: Retrieve Recent Feed Entries

Call `distillery_list(entry_type="feed", limit=<limit>, output_mode="summary")`. If `--days N` was specified, also pass `date_from` as ISO 8601 date N days before today.

If no feed entries are found, display:

```
No feed entries found in the last <N> days.

Suggestions:
- Run distillery_poll to fetch new items from configured sources
- Add sources with /watch add <url>
- Check that feed sources are configured in distillery.yaml
```

Stop here if no entries exist.

### Step 4: Synthesize Digest

You (the executing Claude instance) produce the synthesis — do not dump raw entries.

**Grouping:** Group entries by source tag if present (e.g., `source/github`, `source/rss`), or by topic otherwise.

**Per group:**
- Heading with the group name
- 2-4 sentence summary of key themes
- Bullet list of notable items (title/snippet + source URL if available)

**Cross-group summary:** 2-3 sentences highlighting the most important signals across all sources.

### Step 5: Suggest Sources

Call `distillery_suggest_sources(max_suggestions=5)`. Include suggestions when `--suggest` is specified or when entries were found. Omit silently if the call returns an error or empty results.

### Step 6: Store Digest

Unless `--no-store` was specified, store the digest. Determine author & project per CONVENTIONS.md.

Call `distillery_store(content="<full digest markdown>", entry_type="digest", author="<author>", tags=["digest", "radar", "ambient"])`. Record the returned `entry_id`.

### Step 7: Confirm

Display the digest, then `Digest stored: <entry_id>`. Omit the stored line if `--no-store` was used.

## Output Format

```
# Radar Digest — <YYYY-MM-DD>

<N> feed entries from the last <days> days.

---

## <Group Name>
<2-4 sentence summary>
- **<item title>** — <brief description> ([source](<url>))

---

## Overall Summary
<2-3 sentence cross-group synthesis>

---

## Suggested Sources

| # | URL | Type | Why |
|---|-----|------|-----|
| 1 | <url> | <type> | <rationale> |

To add a source: /watch add <url> [--type rss|github]

---

Digest stored: <entry_id>
```

## Rules

- Default lookback is 7 days; default limit is 20 — respect overrides
- Group entries by source tag when available; fall back to topic grouping
- Store the digest by default; skip only with `--no-store`
- Always include `digest`, `radar`, `ambient` tags when storing
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
- Omit Suggested Sources section entirely if no results or error
