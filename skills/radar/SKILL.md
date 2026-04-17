---
name: radar
description: "Generate an ambient intelligence digest from recent feed activity with source suggestions"
allowed-tools:
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_update"
  - "mcp__*__distillery_find_similar"
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
| `--project <name>` | Scope feed entries to a specific project |
| `--suggest` | Include source suggestions at end of digest |
| `--store` | Store digest as a knowledge entry (default: display-only) |

### Step 3: Retrieve Recent Feed Entries

Use tag-driven semantic search to surface the most relevant feed entries, not just the newest.

**3a. Get interest profile from curated entries:**

Call `distillery_list(group_by="tags")` to get the top tags across all entries. Filter out any groups whose value starts with `feed/` or whose tag namespace suggests feed-only content, and take the top 5 by count. Convert tag paths to natural language by taking the leaf segment and replacing hyphens with spaces (e.g., `domain/authentication` → query `"authentication"`).

**3b. Search by interests (primary path):**

For each of the top interest tags (up to 3 queries), call:

`distillery_search(query="<interest>", entry_type="feed", limit=<ceil(limit/N)>, date_from=<date>)`

Where N is the number of queries. If `--project` was specified, also pass `project=<name>`.

Deduplicate results across queries by entry ID, keeping the highest similarity score.

Report: `Retrieved <total> entries via interest-based search (<N> queries).`

**3c. Fallback (if interest tags unavailable):**

If `distillery_list(group_by="tags")` returns no tags or errors, fall back to:

`distillery_list(entry_type="feed", limit=<limit>, output_mode="summary", date_from=<date>)`

Report: `Retrieved <total> entries via recent listing (fallback).`

**3d. Empty results:**

If no feed entries are found by either path, display:

```
No feed entries found in the last <N> days.

Suggestions:
- Trigger feed polling via POST to /hooks/poll (or use /setup to configure scheduled polling)
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

When `--suggest` is specified, use the interest tags identified in Step 3a to suggest new sources. Based on the top interest topics, recommend 3–5 relevant RSS feeds or GitHub repos the user might want to add via `/watch add <url>`. Omit this section silently if Step 3a returned no tags or if `--suggest` was not specified.

### Step 6: Check for Duplicates (if --store specified)

If `--store` was specified, check for duplicate digests before storing.

Call `distillery_find_similar(content="<digest summary>", dedup_action=True)`. Handle by `action` field:

**`"create"`:** No similar entries. Proceed to Step 7.

**`"skip"`:** Near-exact duplicate. Show similarity table and offer: (1) Store anyway, (2) Skip.

**`"merge"`:** Very similar entry exists. Show similarity table and offer: (1) Store anyway, (2) Merge with existing, (3) Skip.

For merge: combine new digest with the most similar entry's content, call `distillery_update` with the entry ID and merged content, confirm and stop.

**`"link"`:** Related but distinct. Show similarity table, note new entry will be linked. Ask to proceed or skip. If proceeding, include `"related_entries": ["<id1>", ...]` in metadata at Step 7.

```
Similar entries found:

| Entry ID | Similarity | Preview |
|----------|-----------|---------|
| <id>     | <score%>  | <content_preview> |
```

On skip in any case: "Skipped. No new entry was stored." and stop.

### Step 7: Store Digest

If `--store` was specified, store the digest. Determine author & project per CONVENTIONS.md.

Call `distillery_store(content="<full digest markdown>", entry_type="digest", author="<author>", project="<project>", tags=["digest", "radar", "ambient"], metadata={"period_start": "<YYYY-MM-DD>", "period_end": "<YYYY-MM-DD>"})`. Record the returned `entry_id`.

On MCP errors, see CONVENTIONS.md error handling — display and stop.

### Step 8: Confirm

Display the digest. If `--store` was specified, append:

```
[digest] Stored: <entry_id>
Project: <project> | Author: <author>
Summary: <first 200 chars of digest>...
Tags: digest, radar, ambient
```

Omit the stored block if `--store` was not specified.

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

[digest] Stored: <entry_id>
Project: <project> | Author: <author>
Summary: <first 200 chars>...
Tags: digest, radar, ambient
```

## Rules

- NEVER use Bash, Python, or any tool not listed in allowed-tools
- If an MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.
- Default lookback is 7 days; default limit is 20 — respect overrides
- Group entries by source tag when available; fall back to topic grouping
- Display digest by default; store only with `--store` flag
- Always include `digest`, `radar`, `ambient` tags when storing
- Always use `entry_type="digest"` for store calls
- Metadata must include `period_start` and `period_end` as ISO 8601 dates
- Follow shared dedup pattern from CONVENTIONS.md (create/skip/merge/link outcomes)
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
- Omit Suggested Sources section entirely if no results or error
