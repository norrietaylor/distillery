---
name: compass
description: "Contrast internal implementation knowledge against ambient intelligence, find where they meet, and emit a directional assessment (ahead / exposed / decide / confirm)"
allowed-tools:
  - "mcp__*__distillery_status"
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_get"
  - "mcp__*__distillery_find_similar"
  - "mcp__*__distillery_store"
context: fork
effort: high
---

<!-- Trigger phrases: compass, /compass, where do we stand vs the field, ahead or behind, what should we do about, /compass <topic> -->

# Compass — Internal vs Ambient Directional Assessment

Compass contrasts **internal implementation** knowledge (sessions, github, minutes, reference, idea) against **ambient intelligence** (feeds + bookmarks), locates where the two corpora connect, and emits a **directional assessment** — Ahead / Exposed / Decide / Confirm — *first*, before the supporting detail.

It pairs with the existing skills: `radar` senses the surroundings, `investigate` maps the internal terrain — `compass` puts the two together and points somewhere. The assessment is the product; the corpora sections are the evidence.

<!-- Design note (#652): /compass is NON-GRAPH (radar-style) — plain semantic search only, no expand_graph / no distillery_relations. Rationale: the knowledge graph is sparse (a live KB showed orphan_rate 0.9977; global `bridges` returned almost nothing), so graph expansion adds latency without signal. Seams are found by CROSS-VOCABULARY search — not graph edges and not embedding similarity: `find_similar` from an internal seed returns only MORE internal entries (implementation-language like "gvproxy, vsock" and product-language like "egress-proxy creds, microVM" occupy different embedding neighborhoods). The seam step extracts concrete entities/patterns/product-terms from one cluster and queries the other corpus; a disjoint result is itself a finding. -->

## When to Use

- "Where do we stand on X vs. the field, and what should we do?" (`/compass <topic>`)
- Comparing internal progress against external/ambient signal to surface gaps and risks
- "ahead or behind on X", "what should we do about X", "where do we stand vs the field"
- Pre-decision check: is the field discussing something we have no captured position on?
- Starting from a specific entry and orienting it against ambient signal (`/compass --entry <uuid>`)

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Determine Project

Determine project per CONVENTIONS.md (Author & Project Resolution). Although `/compass` is display-only unless `--store` is passed, project is needed to scope both corpus searches via `--project`.

- **Project**: `--project` flag if provided → `basename $(git rev-parse --show-toplevel)` → ask user. Cache for the conversation.

**Soft scope + auto-widen.** When `--project` is **explicitly supplied**, honor it strictly on every search (no widening). When the project is only inferred from the cwd repo (no `--project`), treat it as a *soft preference*: run the searches scoped to it, but if the Internal Position search (Step 4) returns **no entries**, retry the searches **unscoped** (drop the project filter) — the topic often lives in another project than the cwd — and note `Re-scoped to all projects (cwd project '<name>' had no coverage).` in the report.

If already resolved earlier in the conversation, reuse the cached value. Resolve **author** only inside Step 9, and only when `--store` is passed — display-only runs never need it.

### Step 3: Parse Arguments

If no topic is provided (and no `--entry`), ask:

> What topic would you like to orient on? (e.g., "sandbox networking", "agent eval harnesses") — `/compass <topic>`.

Extract from arguments. Every flag is borrowed verbatim from `radar`/`investigate`, so nothing new must be learned:

| Flag | Description |
|------|-------------|
| `--days N` | Ambient window — look back N days for feed/bookmark signal (default 30), applied via `published_after` |
| `--project <name>` | Scope every search (internal and ambient) to this project |
| `--entry <uuid>` | Seed the Internal Position from this specific entry instead of a topic search |
| `--store` | Store the assessment as a knowledge entry (default: display-only) |
| `--include-evergreen` | Include older / first-poll backfill items in the ambient candidate set (default: excluded) |
| `--sources` | Append the full per-entry Sources table (default: off; sources are otherwise cited inline) |

Compute `published_after = (now - <days>).isoformat()` where `<days>` is `--days` if provided, otherwise 30. Bare invocation (`/compass <topic>`) runs the whole flow with defaults.

### Step 4: Internal Position (non-graph search)

Map the internal terrain with ONE plain semantic search scoped to the implementation corpora — **no graph expansion**. The knowledge graph is sparse (orphan-heavy), so a graph walk adds latency without signal; this mirrors radar's pure-search approach. `entry_type` is a list, so a single OR-matched call covers all implementation types:

```python
distillery_search(
    query="<topic>",
    entry_type=["session", "github", "minutes", "reference", "idea"],
    limit=15,
    output_mode="summary",
    project="<project if specified>",
)
```

Keep the **internal result set** keyed by entry id; tag each entry `provenance="internal"` in the Sources table. summary mode carries title, tags, author, created_at, full `metadata`, and a ~200-char content preview — enough for the assessment without the cost of full content. Scoping to the curated implementation types keeps `feed`/`bookmark` entries out of the internal set (they belong to the ambient corpus, Step 5).

**`--entry <uuid>` variant:** load the seed entry directly (no graph traversal) and use its content as the topic probe:

```python
distillery_get(entry_id="<uuid>")
```

Record the seed as internal, derive a topic from its title/content, then run the scoped `distillery_search` above with that topic to gather the surrounding internal terrain. If `distillery_get` returns not found, report the error and stop.

Report: `Internal Position: <N> internal entries (scoped to session/github/minutes/reference/idea).`

If `seed_count` is 0, the internal corpus is silent on this topic — note it plainly (see Step 7 edge cases) and continue to Step 5; a disjoint result is itself a finding.

### Step 5: Ambient Signal (radar-style, windowed)

Sense the surroundings with two windowed searches — feeds and bookmarks — bounded by the ambient window from Step 3:

```python
distillery_search(
    query="<topic>",
    entry_type="feed",
    published_after="<now - days, ISO>",
    include_evergreen=<bool>,
    limit=20,
    project="<project if specified>",
)

distillery_search(
    query="<topic>",
    entry_type="bookmark",
    limit=15,
    project="<project if specified>",
)
```

Pass `include_evergreen=true` on the feed search only when `--include-evergreen` was supplied. Bookmarks are user-curated references and are not poller-windowed, so the bookmark search omits `published_after`. Keep the **ambient result set** keyed by entry id; tag each entry `provenance="ambient"`.

The window is bounded by `metadata.published_at` (publication time), not `created_at` — older items polled today are not new intelligence. First-poll backfill items (`metadata.backfill = true`) are excluded by default; surface them with `--include-evergreen`.

Report: `Ambient Signal: <F> feed + <B> bookmark entries (window=<days>d).`

If both ambient searches return nothing, the field (as captured) is silent on this topic — note it plainly (Step 7) and continue; a disjoint result is itself a finding.

### Step 6: Where They Meet (cross-corpus seam)

This is the comparative step. It does **not** rely on the two mechanisms that look obvious but do not bridge the two corpora — see the design corrections below — so it uses **cross-vocabulary search** as the primary path.

**6a. Cross-vocabulary search (primary path).** Internal entries speak implementation-language (symbols, file paths, library names — e.g. `gvproxy`, `vsock`, `SCM_RIGHTS`); ambient entries speak product-language (patterns, product names, capabilities — e.g. `egress-proxy for credentials`, `microVM`). Extract **up to 2** concrete entities/patterns/product-terms from each cluster (the cap below) and query the *other* corpus with them:

```python
# product-terms lifted from the ambient cluster → query the INTERNAL corpus
distillery_search(query="<product-term from ambient>",
                  entry_type=["session", "github", "minutes", "reference", "idea"],
                  limit=10, project="<project if specified>")

# implementation-terms lifted from the internal cluster → query the AMBIENT corpus.
# entry_type is a list, so ONE scoped call covers feeds + bookmarks. The window is
# dropped here — a seam check only asks whether the concept exists in ambient at all.
distillery_search(query="<impl-term from internal>",
                  entry_type=["feed", "bookmark"],
                  limit=10, project="<project if specified>")
```

A cross-query **hit** — non-empty results when a term lifted from one cluster is run against the *other* corpus — is a **seam**: the two corpora connect on a shared concept expressed in different vocabulary. The seam is the *concept*, **not** a shared entry — entries are single-provenance and never appear in both corpus result sets, so never define a seam by entry-id overlap. Record the bridging concept, the source-cluster entry/entries that yielded the term, and the target-corpus hit entries. Cap at **2 concept-terms per direction** (one scoped call each, so ≤4 cross-queries total).

**Report a DISJOINT result as itself a finding.** If a product-term from the ambient cluster returns nothing internal, that is a real signal: *"the field is discussing X; we have no captured position on X."* Carry these disjoint terms into the Assessment as **Exposed** candidates.

**Do NOT use embedding `find_similar` to bridge.** `find_similar` from an internal seed returns only *more internal* entries (implementation-language and product-language occupy different embedding neighborhoods). A seam must be backed by cross-vocabulary search (6a) — **never** claim a seam that embedding similarity alone produced. (Graph bridges are deliberately not used: the graph is too sparse to connect the corpora — see the design note.)

Report: `Where They Meet: <S> cross-vocabulary seams, <D> disjoint ambient terms.`

### Step 7: Synthesize Assessment

You (the executing Claude instance) produce the synthesis — prescriptive, not a raw dump. Produce the **verdict bullets FIRST**, drawing on the internal set (Step 4), the ambient set (Step 5), and the seams/disjoints (Step 6). Each bullet must cite entries with `[Entry <short-id>]` (short-id = first 8 chars of UUID). Use these four directional categories; omit a category with no bullets:

- **Ahead** — we lead, or already have what the field is converging on. Internal coverage is strong and matches or precedes ambient signal. Cite the internal entries.
- **Exposed** — the field has it; we don't. A gap or risk: ambient signal (or a disjoint ambient term from Step 6a) has no captured internal position. Cite the ambient entries and name what is missing internally.
- **Decide** — an open question needing a call. Both corpora touch it but there is no settled internal decision; a seam reveals a choice. Cite both sides.
- **Confirm** — we assume something the field validates or contradicts. An internal assumption that ambient signal either backs up or challenges. Cite the internal assumption and the ambient evidence.

Each bullet is one actionable sentence plus citations — e.g. *"Exposed: the now-GA egress-proxy-for-credentials pattern [Entry 1a2b3c4d, ambient] is not yet a captured requirement in the still-open egress issue [Entry 9f8e7d6c, internal] — add it."*

### Step 8: Edge Cases

- **Sparse internal** (Step 4 `seed_count` = 0): say plainly *"No captured internal position on '<topic>' — the assessment is ambient-only."* Skip the Internal Position section's body but still emit the Ambient Signal and an Assessment dominated by **Exposed** bullets.
- **Sparse ambient** (Step 5 returns nothing): say plainly *"No ambient signal on '<topic>' in the last <days>d — the assessment is internal-only."* Skip the Ambient Signal body; the Assessment leans on **Ahead**/**Confirm** with the caveat that the field's position is uncaptured.
- **Thin coverage** (fewer than 2 entries in either corpus): note thin coverage for that corpus and lower confidence accordingly — do not over-state Ahead/Exposed on a single entry.
- **Both empty**: display the `radar`-style no-results suggestions (capture with `/distill`, sync with `/gh-sync`, add sources with `/watch add`, bookmark with `/bookmark`) and stop.

### Step 9: Dedup Check + Store (only when `--store`)

Default is display-only. When `--store` is passed, first resolve **author** (deferred from Step 2): `git config user.name` → `DISTILLERY_AUTHOR` env var → ask user. Then follow the CONVENTIONS.md dedup-on-store pattern before writing.

```python
distillery_find_similar(content="<assessment summary>", dedup_action=True)
```

Handle by the returned `action` field — `create` (proceed), `skip` (near-exact duplicate), `merge` (very similar exists), `link` (related but distinct) — exactly per CONVENTIONS.md "Canonical Dedup Flow", showing the similarity table and the per-action options. On `link`, include `"related_entries": ["<id>", ...]` in the store metadata. On any `skip`, confirm "Skipped. No new entry was stored." and stop.

On `create` (or "store anyway"):

```python
distillery_store(
    content="<full assessment markdown>",
    entry_type="digest",
    author="<author>",
    project="<project>",
    tags=["compass", "assessment", "ambient"],
    metadata={"period_start": "<YYYY-MM-DD>", "period_end": "<YYYY-MM-DD>"},
)
```

Record the returned `entry_id`. On MCP errors, see CONVENTIONS.md error handling — display and stop.

## Output Format

Guidance-first order — the verdict leads, the evidence follows. Omit any empty section. The inline `[Entry <short-id>, internal|ambient]` citations in every section are the default audit trail; the full `## Sources` table is appended only with `--sources` — by default a one-line summary stands in for it.

```text
# Compass: <topic>

Oriented "<topic>": <I> internal + <A> ambient entries, <S> seams (window=<days>d).

---

## Assessment

**Ahead**
- <one-sentence verdict> [Entry <short-id>, internal]

**Exposed**
- <one-sentence verdict> [Entry <short-id>, ambient]

**Decide**
- <one-sentence verdict> [Entry <short-id>, internal] vs [Entry <short-id>, ambient]

**Confirm**
- <one-sentence verdict> [Entry <short-id>, internal] / [Entry <short-id>, ambient]

---

## Internal Position

<2–3 paragraph narrative of what we have captured, with [Entry <short-id>] citations. Omit body if sparse internal — state so.>

---

## Ambient Signal

<2–3 paragraph narrative of what the field (feeds + bookmarks) is saying in the window, with [Entry <short-id>] citations. Omit body if sparse ambient — state so.>

---

## Where They Meet

<Cross-vocabulary seams (matched concept + both-side entry ids) and disjoint ambient terms ("the field is discussing X; we have no captured position on X"). Omit if neither corpus has entries.>

---

## Sources

Sources: <N> internal, <M> ambient entries cited inline (run `/compass <topic> --sources` for the full table).

---

[digest] Stored: <entry_id>
Project: <project> | Author: <author>
Summary: <first 200 chars of assessment>...
Tags: compass, assessment, ambient
```

The stored block at the bottom appears only when `--store` was passed and a new entry was created.

By default the `## Sources` section is just the one-line summary above (the inline `[Entry <short-id>, internal|ambient]` citations are the audit trail). ONLY when `--sources` is passed, that summary line is replaced by the full per-entry table:

```text
## Sources

| Short ID | Type | Author | Date | Provenance |
|----------|------|--------|------|------------|
| 1a2b3c4d | [feed] | — | 2026-06-12 | ambient |
| 9f8e7d6c | [github] | Alice | 2026-05-30 | internal |
```

## Rules

- NEVER use Bash, Python, or any tool not listed in allowed-tools
- If an MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.
- The Assessment section comes FIRST in the output — verdict before evidence
- Always use `[Entry <short-id>]` citation format (short-id = first 8 chars of UUID); mark each citation `internal` or `ambient`
- Every Assessment bullet must cite at least one entry — never assert a verdict without evidence
- Deduplicate each corpus's result set by entry id; an entry belongs to exactly one provenance (internal vs ambient) — never double-count
- Apply `--project` to ALL searches (internal and ambient) when EXPLICITLY set (strict, no widening); when project is only inferred from the cwd repo, scope softly and auto-widen to unscoped if Internal Position returns nothing (Step 2)
- Internal Position uses ONE plain `distillery_search(entry_type=["session","github","minutes","reference","idea"], output_mode="summary")` call — NO graph expansion (the graph is too sparse to help); the `--entry` variant uses one `distillery_get` then that same scoped search
- Ambient Signal filters on `published_after` (publication time), not ingest time; first-poll backfill (`metadata.backfill=true`) is excluded unless `--include-evergreen`
- Default ambient window is 30 days — respect `--days`
- "Where They Meet" is cross-vocabulary search, NOT embedding similarity: extract entities/product-terms from one cluster and query the other corpus
- /compass is non-graph: never use `expand_graph` or `distillery_relations` — the graph is too sparse to connect the corpora
- NEVER claim a seam that embedding similarity alone produced — a seam requires cross-vocabulary evidence
- A disjoint result (no overlap between corpora on a term) is itself a finding — report it and feed it to the Assessment as an Exposed candidate
- Loop limits: up to 2 concept-terms per direction in Step 6, one scoped `distillery_search` call per term (entry_type list covers feeds+bookmarks in that one call), so ≤4 cross-queries total
- Display-only by default; store only with `--store`
- `--sources` controls the Sources table: default OFF → emit the one-line summary `Sources: <N> internal, <M> ambient entries cited inline (run /compass <topic> --sources for the full table).`; ON → append the full per-entry table instead. The inline `[Entry <short-id>, internal|ambient]` citations always carry short-id + provenance regardless and are the default audit trail
- When storing: follow CONVENTIONS.md dedup-on-store (create/skip/merge/link), use `entry_type="digest"`, include `compass` in tags, and metadata `period_start`/`period_end` as ISO 8601 dates
- `distillery_search` returning empty results is not an error — record 0 and continue
- Omit sections with no content — never display empty sections
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
