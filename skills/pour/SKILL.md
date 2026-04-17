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

## When to Use

- Comprehensive understanding of a topic across multiple entries
- Synthesizing decisions, discussions, and context from multiple sources
- When asked to "synthesize", "what's the full picture on", or "deep dive into" a topic
- `/pour <topic or question>` optionally with `--project <name>`

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Parse Arguments

If no arguments provided, ask:

> What topic would you like to synthesize? (e.g., "authentication architecture", "decisions made about caching")

Extract from arguments:
- **Topic**: main query string (everything except flags)
- **--project**: if present, scope all searches to that project

### Step 3: Multi-Pass Retrieval

**Pass 1a -- Curated Content Search:**

Search for high-value curated entries first to ensure they aren't drowned out by feed volume:

`distillery_search(query="<topic>", limit=10, entry_type=["session", "bookmark", "minutes", "reference", "idea", "digest"], project="<project if specified>")`

**Pass 1b -- Broad Search:**

`distillery_search(query="<topic>", limit=20, project="<project if specified>")`

Deduplicate Pass 1a and 1b results by entry ID, keeping the higher similarity score. Record all entries and scores.

**Pass 2 -- Follow-up Searches (up to 3) + Tag Expansion (up to 3):**

Analyze Pass 1 for related concepts, people, sub-topics, or terms not directly covered by the original query. For each significant one:

`distillery_search(query="<related concept>", limit=10, project="<project if specified>")`

**Tag-based expansion:** Extract tags from Pass 1 results and identify their namespace prefixes (e.g., tags like `domain/authentication`, `domain/oauth` → namespace prefix `domain`). Call `distillery_list(group_by="tags", project="<project if specified>", limit=200)` to get tag frequencies across the knowledge base. From the returned tag groups, filter to those matching the namespace prefixes and rank by count. Convert the top-ranked tag segments to search queries by taking the leaf segment and replacing hyphens with spaces (e.g., `domain/oauth` → `"oauth"`, `domain/session-management` → `"session management"`). Run up to 3 `distillery_search` calls from these ranked tag-derived queries, skipping any that duplicate an existing Pass 2 concept query.

Report: `Tag expansion: discovered <N> related topics from tag vocabulary.` (Omit this line entirely if no tags are found in Pass 1 results — Pass 2 proceeds with concept-based queries only.)

**Pass 3 -- Gap-filling (up to 2):**

If earlier passes reveal references to specific projects, decisions, or events not yet returned:

`distillery_search(query="<targeted gap query>", limit=10, project="<project if specified>")`

**Deduplication:** By entry ID across all passes. Each entry counted once; track which pass discovered it.

Report: `Retrieved X unique entries across Y search passes.`

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

### Step 7: Interactive Refinement

Ask: `Would you like to go deeper on any sub-topic, or is this sufficient?`

If the user identifies a sub-topic: run a focused search (limit=10), deduplicate against cited entries, produce a `## Refinement: <Sub-topic>` addendum with synthesis and an Additional Sources table, then ask again. Maximum 5 refinement rounds.

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
- Fewer than 2 entries: show full provenance (ID, type badge, author, date, similarity, content)
- Single author: note potential single-perspective bias
- Deduplication is by entry ID across all passes
