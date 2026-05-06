---
name: pour
description: "Synthesize multiple knowledge entries into a cohesive narrative with citations"
allowed-tools:
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_store"
  - "mcp__*__distillery_list"
context: fork
effort: high
---

<!-- Trigger phrases: pour, synthesize, what's the full picture on, deep dive into, /pour <topic> -->

# Pour -- Multi-Entry Knowledge Synthesis

Pour performs multi-pass retrieval across the Distillery knowledge base and synthesizes findings into a structured narrative with inline citations, contradiction flags, and knowledge gap analysis.

**Recent changes:** New `--graph` flag (off by default) opts into graph-expanded retrieval — after each semantic search, BFS pulls in 1-hop structural neighbours via `entry_relations`, and synthesis distinguishes search-matched entries from structurally-related ones.

## When to Use

- Comprehensive understanding of a topic across multiple entries
- Synthesizing decisions, discussions, and context from multiple sources
- When asked to "synthesize", "what's the full picture on", or "deep dive into" a topic
- `/pour <topic or question>` optionally with `--project <name>` and/or `--graph`

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

If no arguments provided, ask:

> What topic would you like to synthesize? (e.g., "authentication architecture", "decisions made about caching")

Extract from arguments:
- **Topic**: main query string (everything except flags)
- **--project**: if present, scope all searches to that project
- **--graph**: if present (off by default), enable graph-expanded retrieval — every `distillery_search` call below is invoked with `expand_graph=true, expand_hops=1` so the seed semantic-search results are augmented with 1-hop structural neighbours from `entry_relations`. Score discount is 0.5 per hop. Each result carries `provenance: "search" | "graph"`, `depth`, and `parent_id`. The envelope adds `graph_expansion: {seed_count, expanded_count}`. Never expand without explicit user opt-in via this flag.

### Step 3: Multi-Pass Retrieval

When `--graph` is set, every `distillery_search` call in this step takes the additional arguments `expand_graph=true, expand_hops=1`. When `--graph` is absent, all calls run unchanged (no graph arguments).

**Pass 1a -- Curated Content Search:**

Search for high-value curated entries first to ensure they aren't drowned out by feed volume:

`distillery_search(query="<topic>", limit=10, entry_type=["session", "bookmark", "minutes", "reference", "idea", "digest"], project="<project if specified>")`

With `--graph`: `distillery_search(query="<topic>", limit=10, entry_type=[...], project="<project if specified>", expand_graph=true, expand_hops=1)`

**Pass 1b -- Broad Search:**

`distillery_search(query="<topic>", limit=20, project="<project if specified>")`

With `--graph`: `distillery_search(query="<topic>", limit=20, project="<project if specified>", expand_graph=true, expand_hops=1)`

Deduplicate Pass 1a and 1b results by entry ID, keeping the higher similarity score. Record all entries and scores. When `--graph` is set, also record each entry's `provenance` (`search` or `graph`), `depth`, and `parent_id`; if the same entry appears via both provenances across passes, prefer `provenance="search"` (the stronger signal).

**Pass 2 -- Follow-up Searches (up to 3) + Tag Expansion (up to 3):**

Analyze Pass 1 for related concepts, people, sub-topics, or terms not directly covered by the original query. For each significant one:

`distillery_search(query="<related concept>", limit=10, project="<project if specified>")` (add `expand_graph=true, expand_hops=1` when `--graph` is set)

**Tag-based expansion:** Extract tags from Pass 1 results and identify their namespace prefixes (e.g., tags like `domain/authentication`, `domain/oauth` → namespace prefix `domain`). Call `distillery_list(group_by="tags", project="<project if specified>", limit=200)` to get tag frequencies across the knowledge base. From the returned tag groups, filter to those matching the namespace prefixes and rank by count. Convert the top-ranked tag segments to search queries by taking the leaf segment and replacing hyphens with spaces (e.g., `domain/oauth` → `"oauth"`, `domain/session-management` → `"session management"`). Run up to 3 `distillery_search` calls from these ranked tag-derived queries, skipping any that duplicate an existing Pass 2 concept query. (Add `expand_graph=true, expand_hops=1` when `--graph` is set.)

Report: `Tag expansion: discovered <N> related topics from tag vocabulary.` (Omit this line entirely if no tags are found in Pass 1 results — Pass 2 proceeds with concept-based queries only.)

**Pass 3 -- Gap-filling (up to 2):**

If earlier passes reveal references to specific projects, decisions, or events not yet returned:

`distillery_search(query="<targeted gap query>", limit=10, project="<project if specified>")` (add `expand_graph=true, expand_hops=1` when `--graph` is set)

**Deduplication:** By entry ID across all passes. Each entry counted once; track which pass discovered it. When `--graph` is set, also track per entry the final `provenance` (search vs graph) for use in Step 5 synthesis.

Report: `Retrieved X unique entries across Y search passes.` When `--graph` is set, append `(graph expansion: <seed_count> seed → <expanded_count> after 1-hop neighbours)` using totals summed from the `graph_expansion` envelope across all calls.

### Step 4: Edge Case Check

**Fewer than 2 entries:** Fall back to recall-style display showing full provenance (ID, type badge, author, date, similarity, content) per entry, then:

```text
Only <N> entry found for this topic. Showing results directly instead of synthesizing.
Tip: Use /distill to capture more knowledge about this topic.
```

Stop here -- do not synthesize with fewer than 2 entries.

**Single author:** Append a note that all entries are from one author and the synthesis may reflect a single perspective.

### Step 5: Structured Synthesis

Produce these sections, omitting any with no relevant content:

**a. Summary (always include)** -- 2-3 paragraph narrative weaving findings together with inline `[Entry <short-id>]` citations (short-id = first 8 chars of UUID).

Example: `The team adopted DuckDB after evaluating SQLite and PostgreSQL [Entry 550e8400]. This was driven by the need for embedded analytical queries [Entry 7c9e6679].`

**Provenance distinction (when `--graph` is set):** Entries with `provenance="search"` matched the query semantically; entries with `provenance="graph"` did not match the query directly but were pulled in as 1-hop structural neighbours of a search-matched entry. In the prose, label graph-only entries as "structurally related" (e.g., `[Entry abc12345, structurally related]`) and call out *why* they appear — e.g., "linked to [Entry 550e8400] via `entry_relations`". Treat search-matched entries as primary signal; graph-only entries provide supporting context (downstream impacts, prior decisions a search-matched entry references, etc.). The synthesis should make this distinction visible to the user so they understand why each entry appears.

**b. Timeline (omit if all entries same day)** -- Chronological evolution with dates, descriptions, and citations.

**c. Key Decisions (omit if none)** -- Bullet list: what was decided, by whom, when, rationale, citation.

**d. Contradictions (omit if none)** -- Conflicting information between entries, presenting both sides with dates. Note which may supersede.

**e. Knowledge Gaps (omit if none)** -- Thin areas and suggestions for what to capture next via `/distill`.

### Step 6: Source Attribution

Table of all cited entries:

| # | Short ID | Type | Author | Date | Preview | Similarity |
|---|----------|------|--------|------|---------|------------|
| 1 | 550e8400 | [session] | Alice Smith | 2026-03-15 | We decided to use DuckDB for... | 92% |

- **Short ID**: first 8 chars of UUID
- **Preview**: first 40 chars of content
- **Similarity**: highest score from any pass, as percentage

When `--graph` is set, add a **Provenance** column showing `search` or `graph` (and for graph entries, append the `parent_id` short-id, e.g., `graph (via 550e8400)`), so the audit trail makes the retrieval path explicit.

### Step 7: Interactive Refinement

Ask: `Would you like to go deeper on any sub-topic, or is this sufficient?`

If the user identifies a sub-topic: run a focused search (limit=10) — passing `expand_graph=true, expand_hops=1` if `--graph` is set — deduplicate against cited entries, produce a `## Refinement: <Sub-topic>` addendum with synthesis and an Additional Sources table (with Provenance column when `--graph` is set), then ask again. Maximum 5 refinement rounds.

When satisfied: `Synthesis complete. X entries cited across Y sections.`

## Output Format

Heading `# Pour: <Topic>`, then sections Summary, Timeline, Key Decisions, Contradictions, Knowledge Gaps, Sources as described above. Refinement addendums appended if requested. Fewer than 2 entries triggers the fallback display instead.

## Rules

- NEVER use Bash, Python, or any tool not listed in allowed-tools
- If an MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.
- Always use `[Entry <short-id>]` citation format (short-id = first 8 chars of UUID)
- Every factual claim must trace to an entry -- never synthesize without citing
- Omit sections with no content
- On MCP errors, see CONVENTIONS.md error handling -- display and stop
- Loop limits: 3 follow-up searches (Pass 2), 2 gap-filling searches (Pass 3), 5 refinement rounds (Step 7)
- Apply `--project` filter to every `distillery_search` call when provided
- `--graph` defaults OFF — never pass `expand_graph=true` without explicit user opt-in via the flag; without `--graph`, all `distillery_search` calls and synthesis behavior remain unchanged (no provenance column, no "structurally related" labels, no graph_expansion totals)
- When `--graph` is set, apply `expand_graph=true, expand_hops=1` to every `distillery_search` call (Pass 1a, 1b, Pass 2 concept and tag-derived, Pass 3, and any Step 7 refinement search)
- When `--graph` is set, label graph-only entries (`provenance="graph"`) as "structurally related" in the prose and explain why they appear (parent entry, relation path)
- Fewer than 2 entries: show full provenance (ID, type badge, author, date, similarity, content)
- Single author: note potential single-perspective bias
- Deduplication is by entry ID across all passes
