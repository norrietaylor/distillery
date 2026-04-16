---
name: investigate
description: "Compile deep context on a topic by combining semantic search with relationship traversal across 4 retrieval phases"
allowed-tools:
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_relations"
  - "mcp__*__distillery_list"
context: fork
effort: high
---

<!-- Trigger phrases: investigate, /investigate, deep context, what do we know about, trace connections, follow relationships, /investigate <topic>, /investigate --entry <id> -->

# Investigate — Deep Context Builder

Investigate compiles comprehensive context on a topic by executing a 4-phase retrieval: seed search, relationship expansion, tag expansion, and gap filling. It combines semantic search with explicit relationship traversal to surface context that keyword search alone misses.

## When to Use

- Deep research on a topic spanning multiple entries and relationships (`/investigate <topic>`)
- Starting from a specific entry and following its connections (`/investigate --entry <uuid>`)
- "What do we know about X", "trace connections for X", "deep context on X"
- Understanding how entries relate to each other across sessions, issues, and meeting notes
- Discovering knowledge gaps on a topic before a decision or discussion

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Determine Author & Project

Determine author and project per CONVENTIONS.md (Author & Project Resolution). Although `/investigate` is display-only and does not store entries, project is needed to scope searches via `--project`, and author is used for project resolution context.

- **Author**: `git config user.name` → `DISTILLERY_AUTHOR` env var → ask user. Cache for the conversation.
- **Project**: `--project` flag if provided → `basename $(git rev-parse --show-toplevel)` → ask user. Cache for the conversation.

If already resolved earlier in the conversation, reuse the cached values.

### Step 3: Parse Arguments

If no arguments provided, ask:

> What topic would you like to investigate? (e.g., "authentication architecture", "caching decisions") Or provide a specific entry ID with `--entry <uuid>`.

Extract from arguments:
- **Topic**: main query string (everything except flags)
- **--entry `<uuid>`**: if present, start Phase 1 from this specific entry instead of a search
- **--project `<name>`**: if present, scope Phase 1 and Phase 4 searches to that project

### Step 4: 4-Phase Retrieval

Track a **result set** keyed by entry ID throughout all phases. Each entry is counted once — the phase that first discovered it is recorded. Track relationship edges separately.

---

**Phase 1 — Seed:**

If `--entry <uuid>` was provided:

```python
distillery_get(entry_id="<uuid>")
```

Add the returned entry to the result set. This is the seed entry.

If no `--entry` was provided:

```python
distillery_search(query="<topic>", limit=20, project="<project if specified>")
```

Add all returned entries to the result set. These are the seed entries.

Report: `Phase 1 (Seed): <N> entries retrieved.`

If Phase 1 returns zero entries, display:

```text
No entries found for "<topic>".

Suggestions:
- Capture relevant knowledge with /distill
- Sync GitHub issues with /gh-sync
- Save references with /bookmark
```

Stop here if Phase 1 returns zero entries.

---

**Phase 2 — Expand Relationships:**

For each seed entry from Phase 1 (do not recurse into entries added during Phase 2), call:

```python
distillery_relations(action="get", entry_id="<id>")
```

Collect all related entry IDs from the response (both `from_id` and `to_id` fields, in all directions). Record each unique relation edge as `<entry_a> —[<relation_type>]→ <entry_b>`.

For each related entry ID not already in the result set, fetch it:

```python
distillery_get(entry_id="<related_id>")
```

Add fetched entries to the result set, tagged as discovered in Phase 2.

Report: `Phase 2 (Relationships): <N> new entries via <K> relation edges.`

If no relations exist for any seed entry, note this in the Phase 2 report and continue.

---

**Phase 3 — Tag Expansion:**

Extract all tags from entries currently in the result set. Identify unique namespace prefixes (e.g., tags like `domain/authentication`, `domain/oauth` → prefix `domain`). For each relevant namespace, call:

```python
distillery_list(group_by="tags")
```

From the returned tag groups, rank tags by count. Filter to those matching the namespace prefixes extracted from the result set. Convert top-ranked tag segments to search queries (replace hyphens with spaces: `domain/oauth` → `"oauth"`). Run up to 3 `distillery_search` calls from these ranked tag-derived queries:

```python
distillery_search(query="<tag-derived query>", limit=10, project="<project if specified>")
```

Add any entries not already in the result set to it, tagged as discovered in Phase 3.

Report: `Phase 3 (Tags): <N> new entries from tag expansion across <M> namespaces.`

If no tags are found in the result set, skip Phase 3 searches and note: `Phase 3 (Tags): No tags found in seed results — skipped.`

---

**Phase 4 — Gap Fill:**

Analyze the content of all entries currently in the result set. Identify:
- People mentioned by name but not yet represented as `person` entries
- Projects or repositories referenced but not yet in the result set
- Key topics, decisions, or concepts mentioned but sparsely represented (fewer than 2 entries)

For each identified gap (up to 3), run a targeted search:

```python
distillery_search(query="<gap query>", limit=10, project="<project if specified>")
```

Add any entries not already in the result set, tagged as discovered in Phase 4.

Report: `Phase 4 (Gap Fill): <N> new entries from <G> targeted gap searches.`

---

**Summary line:**

```text
Investigated "<topic>": <total_N> entries across <phases_with_results> phases, <K> relationship edges traversed.
```

### Step 5: Synthesize Output

You (the executing Claude instance) produce the synthesis. Do not dump raw entries.

**a. Context Summary (always include):**

A 2–4 paragraph narrative weaving findings together. Use `[Entry <short-id>]` inline citations (short-id = first 8 chars of UUID). Describe what the knowledge base knows about the topic, how entries connect, and what the overall picture reveals.

Example: `The team evaluated DuckDB as the storage backend in early 2026 [Entry 550e8400], driven by requirements for embedded analytical queries [Entry 7c9e6679]. A sync with GitHub issues confirms the decision was tracked formally [Entry a1b2c3d4].`

**b. Relationship Map (omit if no relations found):**

Text-based representation of connections between entries:

```text
Entry 550e8400 [session] "DuckDB evaluation"
  —[citation]→ Entry 7c9e6679 [reference] "Analytical query requirements"
  —[link]→ Entry a1b2c3d4 [github] "Issue #42: storage backend decision"

Entry 7c9e6679 [reference] "Analytical query requirements"
  —[citation]→ Entry 550e8400 [session] "DuckDB evaluation"
```

List each entry that has at least one relation. Show relation type and a short label (first 40 chars of content or `title` metadata field if present). Omit entries with no relations from this section.

**c. Timeline (omit if all entries same day or fewer than 3 entries):**

Chronological list of entries, ordered by `created_at`:

| Date | Short ID | Type | Author | Summary |
|------|----------|------|--------|---------|
| 2026-01-15 | 550e8400 | [session] | Alice | DuckDB evaluation and benchmark results |
| 2026-01-20 | 7c9e6679 | [reference] | Bob | Analytical query requirements doc |

**d. Key People (omit if all entries have the same single author):**

Authors and mentioned people:
- For each unique author in the result set: name, number of entries, entry types
- People mentioned in content by name but not as authors: note they appear in content but may not have captured knowledge directly

**e. Knowledge Gaps (omit if none identified):**

From Phase 4 gap analysis:
- Topics referenced but with sparse coverage (fewer than 2 entries)
- People mentioned but without dedicated `person` entries
- Decisions mentioned but without corresponding `minutes` or `session` entries

Suggest follow-up actions using appropriate skills (e.g., `/distill`, `/gh-sync`, `/minutes`).

### Step 6: Source Attribution

Table of all entries in the result set:

| Phase | Short ID | Type | Author | Date | Relation Edges | Preview |
|-------|----------|------|--------|------|---------------|---------|
| 1 | 550e8400 | [session] | Alice Smith | 2026-01-15 | 2 | We decided to use DuckDB for... |
| 2 | 7c9e6679 | [reference] | Bob Jones | 2026-01-20 | 1 | Analytical query requirements... |
| 3 | a1b2c3d4 | [github] | — | 2026-01-22 | 1 | Issue #42: storage backend deci... |

- **Phase**: discovery phase number (1–4)
- **Short ID**: first 8 chars of UUID
- **Relation Edges**: number of relation edges this entry participates in
- **Preview**: first 40 chars of content, or `title` metadata field if present

## Output Format

Heading `# Investigate: <Topic>`, then the summary line, then sections: Context Summary, Relationship Map, Timeline, Key People, Knowledge Gaps, Sources — each as described above. Omit empty sections.

```text
# Investigate: <topic or "Entry <short-id>">

Investigated "<topic>": <N> entries across <phases> phases, <K> relationship edges traversed.

---

## Context Summary

<2–4 paragraph narrative with [Entry <short-id>] citations>

---

## Relationship Map

<text-based relationship graph — omit if no relations>

---

## Timeline

<chronological table — omit if all same day or fewer than 3 entries>

---

## Key People

<author and mention list — omit if single author>

---

## Knowledge Gaps

<gap analysis with suggestions — omit if none>

---

## Sources

| Phase | Short ID | Type | Author | Date | Relation Edges | Preview |
|-------|----------|------|--------|------|---------------|---------|
| ...   | ...      | ...  | ...    | ...  | ...           | ...     |
```

## Rules

- NEVER use Bash, Python, or any tool not listed in allowed-tools
- If an MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.
- Always use `[Entry <short-id>]` citation format (short-id = first 8 chars of UUID)
- Deduplicate the result set by entry ID across all phases — each entry counted once
- Record which phase first discovered each entry
- Phase 2 relationship traversal is single-hop only (v1 — `--depth` flag is a future enhancement)
- Loop limits: up to 3 `distillery_search` calls in Phase 3, up to 3 targeted searches in Phase 4
- Track relation edges separately from the result set entry count
- Omit sections with no content — never display empty sections
- If `--entry <uuid>` is provided and `distillery_get` returns not found, report the error and stop
- Apply `--project` filter to all `distillery_search` calls in Phase 1 and Phase 4 when provided
- `distillery_relations` returning empty for an entry is not an error — record 0 edges and continue
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
- Display-only — this skill never stores output
