---
name: pour
description: "Synthesizes knowledge from multiple entries into a cohesive narrative with citations. Triggered by: 'pour', 'synthesize', 'what's the full picture on', 'deep dive into', or '/pour <topic>'."
---

# Pour -- Multi-Entry Knowledge Synthesis

Pour performs multi-pass retrieval across the Distillery knowledge base and synthesizes findings into a structured narrative with inline citations, contradiction flags, and knowledge gap analysis.

## Prerequisites

- The Distillery MCP server must be configured in your Claude Code settings
- See docs/mcp-setup.md for setup instructions

If the server is not available, the skill will display a setup message with next steps.

## When to Use

- When you need a comprehensive understanding of a topic across multiple knowledge entries
- When synthesizing decisions, discussions, and context from multiple sources
- When asked to "synthesize", "what's the full picture on", or "deep dive into" a topic
- When `/pour <topic or question>` is invoked, optionally with `--project <name>`

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

If no arguments are provided, ask the user:

```
What topic would you like to synthesize? For example:
- "authentication architecture"
- "deployment strategy for project alpha"
- "decisions made about caching"
```

If arguments are provided, extract:
- **Topic**: The main query string (everything except flags)
- **--project flag**: If present, scope all searches to that project

Example: `/pour deployment strategy --project alpha` sets topic to "deployment strategy" and project filter to "alpha".

### Step 3: Multi-Pass Retrieval

Perform up to three passes of retrieval to gather comprehensive results.

**Pass 1 -- Broad Search:**

Call `distillery_search` with the topic and limit 20:

```
distillery_search(query="<topic>", limit=20, project="<project if specified>")
```

Record all returned entries and their similarity scores.

**Pass 2 -- Follow-up Searches:**

Analyze Pass 1 results for related concepts, people, sub-topics, or terms that appear in the content but were not directly covered by the original query. For each significant related concept (up to 3 follow-up searches), call:

```
distillery_search(query="<related concept>", limit=10, project="<project if specified>")
```

Examples of follow-up queries:
- If entries mention a person by name who made key decisions, search for that person
- If entries reference a specific technology or component, search for it
- If entries mention a related project or initiative, search for it

**Pass 3 -- Gap-filling:**

If Pass 1 and Pass 2 results reveal references to specific projects, decisions, or events that were not returned in earlier passes, run up to 2 targeted searches:

```
distillery_search(query="<targeted gap query>", limit=10, project="<project if specified>")
```

**Deduplication:**

Deduplicate across all passes by entry ID. Each unique entry is counted once, even if returned by multiple searches. Track which pass each entry was first discovered in.

**Report retrieval stats:**

```
Retrieved X unique entries across Y search passes.
```

### Step 4: Edge Case Check

**Fewer than 2 entries found:**

If fewer than 2 unique entries were found across all passes, fall back to recall-style display. For each entry, show:

```
---
ID: <full UUID> | Type: [<entry_type>] | Author: <author> | <created date> | Similarity: <score>%

<full entry content>
---
```

Then display:

```
Only <N> entry found for this topic. Showing results directly instead of synthesizing.
Tip: Use /distill to capture more knowledge about this topic.
```

Stop here -- do not attempt synthesis with fewer than 2 entries.

**Single author check:**

If all entries come from a single author, include a note at the end of the synthesis:

```
Note: All entries are from a single author (<author name>). This synthesis may reflect a single perspective. Consider capturing knowledge from other team members with /distill.
```

### Step 5: Structured Synthesis

Produce a synthesis with the following sections. Omit any section that has no relevant content.

**a. Summary (always include)**

Write 2-3 paragraphs providing a cohesive narrative that weaves together findings from multiple entries. Use inline citations in the format `[Entry <short-id>]` where short-id is the first 8 characters of the entry UUID.

Example:
```
The team adopted DuckDB as the local storage engine after evaluating SQLite and PostgreSQL [Entry 550e8400]. This decision was driven by the need for embedded analytical queries without a separate server process [Entry 7c9e6679].
```

**b. Timeline (omit if all entries are from the same day)**

Present the chronological evolution of the topic:

```
## Timeline

- **2026-03-15** -- Initial decision to evaluate storage options [Entry 550e8400]
- **2026-03-18** -- Benchmarked DuckDB vs SQLite for vector search [Entry 7c9e6679]
- **2026-03-20** -- Finalized DuckDB with VSS extension [Entry a1b2c3d4]
```

**c. Key Decisions (omit if none found)**

Bullet list of decisions with who made them and when:

```
## Key Decisions

- **Use DuckDB for local storage** -- decided by Alice Smith on 2026-03-18, rationale: embedded analytics without server overhead [Entry 7c9e6679]
- **Adopt cosine similarity for search ranking** -- decided by Bob Jones on 2026-03-20 [Entry a1b2c3d4]
```

**d. Contradictions (omit if none found)**

Flag conflicting information between entries, presenting both sides:

```
## Contradictions

- **Authentication method**: Entry 550e8400 states "We use JWT tokens" (Alice, 2026-03-15) while Entry 7c9e6679 states "We switched to session cookies" (Bob, 2026-03-18). The later entry may supersede the earlier one.
```

**e. Knowledge Gaps (omit if none identified)**

Identify thin areas and suggest what to capture next:

```
## Knowledge Gaps

- No entries cover the **deployment pipeline** for this component
- **Performance benchmarks** are mentioned but no detailed results were captured
- Consider running `/distill` to capture knowledge about these areas
```

### Step 6: Source Attribution

After the synthesis, list all cited entries:

```
## Sources

| # | Short ID | Type | Author | Date | Preview | Similarity |
|---|----------|------|--------|------|---------|------------|
| 1 | 550e8400 | [session] | Alice Smith | 2026-03-15 | We decided to use DuckDB for... | 92% |
| 2 | 7c9e6679 | [bookmark] | Bob Jones | 2026-03-18 | Benchmark results comparing... | 87% |
| 3 | a1b2c3d4 | [session] | Alice Smith | 2026-03-20 | Finalized the storage layer... | 81% |
```

- **Short ID**: First 8 characters of the entry UUID
- **Type**: Entry type in brackets (e.g., `[session]`, `[bookmark]`, `[minutes]`)
- **Author**: Author name from the entry
- **Date**: Created date in YYYY-MM-DD format
- **Preview**: First 40 characters of the entry content
- **Similarity**: Highest similarity score from any search pass, as a percentage

### Step 7: Interactive Refinement

After presenting the synthesis, ask the user:

```
Would you like to go deeper on any sub-topic, or is this sufficient?
```

**If the user identifies a sub-topic:**

1. Run a focused retrieval pass: `distillery_search(query="<sub-topic>", limit=10, project="<project if specified>")`
2. Deduplicate against already-cited entries
3. Produce an addendum section:

```
## Refinement: <Sub-topic>

<Additional synthesis focusing on the sub-topic, with inline citations>

### Additional Sources

| # | Short ID | Type | Author | Date | Preview | Similarity |
|---|----------|------|--------|------|---------|------------|
| ... |
```

4. Ask again: "Would you like to go deeper on another sub-topic, or is this sufficient?"

**Loop until the user is satisfied** (maximum 5 refinement rounds to prevent infinite loops).

**If the user is satisfied:**

```
Synthesis complete. X entries cited across Y sections.
```

## Output Format

**Retrieval stats:**
```
Retrieved X unique entries across Y search passes.
```

**Synthesis body:**
```
# Pour: <Topic>

## Summary
<2-3 paragraph narrative with [Entry <short-id>] citations>

## Timeline
<chronological list, omit if same day>

## Key Decisions
<bullet list, omit if none>

## Contradictions
<conflicting entries, omit if none>

## Knowledge Gaps
<thin areas and suggestions, omit if none>

## Sources
<table of cited entries>
```

**Refinement addendum (if requested):**
```
## Refinement: <Sub-topic>
<focused synthesis with citations>

### Additional Sources
<table of new entries>
```

**Fallback (fewer than 2 entries):**
```
Only <N> entry found for this topic. Showing results directly instead of synthesizing.
Tip: Use /distill to capture more knowledge about this topic.
```

## Rules

- Always use `[Entry <short-id>]` citation format for inline references, where short-id is the first 8 characters of the entry UUID
- Never synthesize without citing sources -- every factual claim must trace to an entry
- Omit sections that have no content (do not include empty Timeline, Decisions, etc.)
- Follow shared conventions from `.claude/skills/conventions.md` for MCP checks and error handling
- If an MCP tool returns an error, display it clearly:

```
Error: <error message from MCP tool>

Suggested Action:
- If "API key invalid" -> Re-check the embedding provider API key in your config
- If "Database error" -> Ensure the database path is writable and the file exists
- If "Search failed" -> Try rephrasing the query or broadening the topic
```

- Do not enter infinite loops -- maximum 3 follow-up searches in Pass 2, maximum 2 gap-filling searches in Pass 3, maximum 5 refinement rounds in Step 7
- Short-id is always the first 8 characters of the entry UUID
- If the `--project` flag is provided, apply it as a filter to every `distillery_search` call
- When falling back to recall behavior (fewer than 2 entries), include full provenance: entry ID, type badge, author, date, similarity score, and content
- If all entries are from a single author, note the potential single-perspective bias
- Deduplication is by entry ID -- the same entry returned across multiple passes is counted once
