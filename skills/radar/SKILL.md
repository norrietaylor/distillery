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
| `--days N` | Look back N days for recent feed entries (overrides `feeds.digest.window_days`, default 7) |
| `--limit N` | Maximum number of feed entries to include (default: 20) |
| `--project <name>` | Scope feed entries to a specific project |
| `--topic <query>` | Use the literal string as a semantic-search query instead of mining tags. Repeatable; each `--topic` is one query. When set, Step 3a is skipped. |
| `--suggest` | Include source suggestions at end of digest |
| `--store` | Store digest as a knowledge entry (default: display-only) |
| `--include-evergreen` | Include older / first-poll backfill items in the candidate set (default: excluded) |

**`--topic` examples:**

```
/radar --topic "build hermeticity"
/radar --topic agentic-eval --days 14
/radar --topic "build hermeticity" --topic "wheels caching"
```

Multiple `--topic` flags may be passed; each becomes a separate
`distillery_search` query. Deduplicate the literal query strings (case- and
whitespace-insensitive) before issuing.

The look-back window is bounded by `metadata.published_at` (the feed item's
publication timestamp), not `created_at`. Items with no `published_at` are
included unless they are flagged `metadata.backfill = true` (first-poll
backfill batches), in which case they are hidden by default. Pass
`--include-evergreen` to override and surface them.

### Step 3: Retrieve Recent Feed Entries

Use tag-driven semantic search to surface the most relevant feed entries, not just the newest.

**3a. Determine the query set:**

Two paths — explicit override or auto-derived from interests.

*Path 1 — `--topic` override (skip tag mining):*

If one or more `--topic <query>` flags were supplied, use the supplied
strings directly as the query set. Deduplicate (case-insensitive, trim
whitespace), preserving the user's order. Skip the rest of Step 3a and
proceed to 3b. Report: `Using <N> user-supplied topic(s): <comma-separated>.`

*Path 2 — Namespace-diverse interest profile (default):*

Build an interest profile that excludes feed-ingested content. Make separate
`distillery_list(group_by="tags", entry_type=<type>)` calls for curated
types: `session`, `reference`, `bookmark`, `idea`, `note`, and `minutes`.
Merge the group counts across all responses to obtain a combined count map.

Then select **3 namespace-diverse tags**, *not* the raw top-3 by count. A
tag's namespace is its hierarchical path with the leaf segment removed,
capped at two segments (e.g., `domain/build/hermeticity` → namespace
`domain/build`; `tech/duckdb` → namespace `tech`; single-segment `release`
namespaces to itself). The selection rule:

1. Group all tags by namespace.
2. Pick the highest-count tag in each namespace (alphabetical tie-break) —
   the *namespace leader*.
3. Rank namespace leaders by their count and take the top 3 leaders.

This guarantees the query set spans up to three distinct conceptual
clusters. The reference implementation lives in
`distillery.feeds.radar_selection.select_namespace_diverse_tags` — call it
mentally as `select_namespace_diverse_tags(merged_counts, top_n=3)`.

Convert each chosen tag path to a natural-language query by taking the leaf
segment and replacing hyphens with spaces (e.g.,
`domain/build/hermeticity` → query `"hermeticity"`).

**3b. Search by interests (primary path):**

Compute `published_after = (now - <days>).isoformat()` where `<days>` is the
`--days` flag if provided, otherwise the configured `feeds.digest.window_days`
(default 7). For each query in the query set from 3a (whether `--topic`-supplied
or namespace-derived), call:

`distillery_search(query="<query>", entry_type="feed", limit=<ceil(limit/N)>, published_after=<iso>, include_evergreen=<bool>)`

Where N is the number of queries. Pass `include_evergreen=true` only when the
user supplied `--include-evergreen`. If `--project` was specified, also pass
`project=<name>`.

Deduplicate results across queries by entry ID, keeping the highest similarity score.

Report: `Retrieved <total> entries via interest-based search (<N> queries, window=<days>d).`

**3c. Fallback (if interest tags unavailable):**

This fallback applies only to Path 2 (auto-derived interest profile). If
`--topic` was supplied, Step 3b always has at least one query and 3c is
skipped.

If none of the curated-type `group_by="tags"` calls return any tags, fall back to:

`distillery_list(entry_type="feed", limit=<limit>, output_mode="summary", published_after=<iso>, include_evergreen=<bool>)`

Report: `Retrieved <total> entries via recent listing (fallback, window=<days>d).`

If the curated-type `group_by="tags"` calls themselves error, treat that as an MCP error per the Rules section below — report and stop.

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

When `--suggest` is specified, use the query set from Step 3a — namespace-diverse interest tags from Path 2, or the user-supplied `--topic` strings from Path 1 — to suggest new sources. Based on those topics, recommend 3–5 relevant RSS feeds or GitHub repos the user might want to add via `/watch add <url>`. Omit this section silently if Step 3a produced no queries or if `--suggest` was not specified.

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
- Default lookback is `feeds.digest.window_days` (7 days); default limit is 20 — respect overrides
- Filter on `published_after` (publication time), not `date_from` (ingest time) — older items polled today are not new intelligence
- First-poll backfill items (`metadata.backfill = true`) are excluded by default; surface them with `--include-evergreen`
- Group entries by source tag when available; fall back to topic grouping
- Display digest by default; store only with `--store` flag
- Always include `digest`, `radar`, `ambient` tags when storing
- Always use `entry_type="digest"` for store calls
- Metadata must include `period_start` and `period_end` as ISO 8601 dates
- Follow shared dedup pattern from CONVENTIONS.md (create/skip/merge/link outcomes)
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
- Omit Suggested Sources section entirely if no results or error
