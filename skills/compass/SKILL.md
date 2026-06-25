---
name: compass
description: "Contrast internal implementation knowledge against ambient intelligence, find where they meet, and emit a directional assessment (ahead / exposed / decide / confirm)"
allowed-tools:
  - "mcp__*__distillery_status"
  - "mcp__*__distillery_search"
  - "mcp__*__distillery_list"
  - "mcp__*__distillery_find_similar"
  - "mcp__*__distillery_relations"
  - "mcp__*__distillery_store"
context: fork
effort: high
---

<!-- Trigger phrases: compass, /compass, where do we stand vs the field, ahead or behind, what should we do about, /compass <topic> -->

# Compass — Internal vs Ambient Directional Assessment

Compass contrasts **internal implementation** knowledge (sessions, github, minutes, reference, idea) against **ambient intelligence** (feeds + bookmarks), locates where the two corpora connect, and emits a **directional assessment** — Ahead / Exposed / Decide / Confirm — *first*, before the supporting detail.

It pairs with the existing skills: `radar` senses the surroundings, `investigate` maps the internal terrain — `compass` puts the two together and points somewhere. The assessment is the product; the corpora sections are the evidence.

<!-- Design note (#652): two corrections are baked into "Where They Meet". (1) Graph `bridges` are NOT a reliable seam-finder — a live KB showed orphan_rate 0.9977, so global bridges return almost nothing; treat them as the rare case, not the primary path. (2) Embedding `find_similar` from an internal seed returns only MORE internal entries — implementation-language ("gvproxy, vsock") and product-language ("egress-proxy creds, microVM") occupy different embedding neighborhoods, so similarity alone does NOT bridge vocabularies. The seam step is therefore cross-vocabulary search: extract concrete entities/patterns/product-terms from one cluster and query the other corpus, and report a disjoint result as itself a finding. -->

## When to Use

- "Where do we stand on X vs. the field, and what should we do?" (`/compass <topic>`)
- Comparing internal progress against external/ambient signal to surface gaps and risks
- "ahead or behind on X", "what should we do about X", "where do we stand vs the field"
- Pre-decision check: is the field discussing something we have no captured position on?
- Starting from a specific entry and orienting it against ambient signal (`/compass --entry <uuid>`)

## Process

### Step 1: Check MCP

See CONVENTIONS.md — skip if already confirmed this conversation.

### Step 2: Determine Author & Project

Determine author and project per CONVENTIONS.md (Author & Project Resolution). Although `/compass` is display-only unless `--store` is passed, project is needed to scope both corpus searches via `--project`, and author is used for project-resolution context and for the dedup-on-store check.

- **Author**: `git config user.name` → `DISTILLERY_AUTHOR` env var → ask user. Cache for the conversation.
- **Project**: `--project` flag if provided → `basename $(git rev-parse --show-toplevel)` → ask user. Cache for the conversation.

If already resolved earlier in the conversation, reuse the cached values.

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

Compute `published_after = (now - <days>).isoformat()` where `<days>` is `--days` if provided, otherwise 30. Bare invocation (`/compass <topic>`) runs the whole flow with defaults.

### Step 4: Internal Position (investigate-style)

Map the internal terrain with one graph-expanded search over the implementation corpora (sessions, github, minutes, reference, idea). This fuses the seed search and a 2-hop relationship traversal server-side, returning seeds plus their graph neighbours — with inline content — in ONE round-trip:

```python
distillery_search(
    query="<topic>",
    expand_graph=True,
    expand_hops=2,
    limit=20,
    output_mode="full",
    project="<project if specified>",
)
```

The envelope is `{results: [...], count, graph_expansion: {seed_count, expanded_count}}`. Each result carries `provenance` (`"search"` = seed, `"graph"` = reached via a relation), and graph results add `depth`, `parent_id`, and `relation_type`. Keep the **internal result set** keyed by entry id; tag each entry `provenance="internal"` in the Sources table.

When the topic is implementation-flavoured, the seeds are typically curated types (`session`, `github`, `minutes`, `reference`, `idea`). Note any ambient-type entries (`feed`, `bookmark`) that surface here — they belong to the ambient corpus and are folded into Step 5 instead of double-counted.

**`--entry <uuid>` variant:** when seeding from a specific entry, traverse its relationships directly — it is the sole seed, so this is one traverse, not a fan-out:

```python
distillery_relations(action="traverse", entry_id="<uuid>", hops=2, direction="both")
```

Record the seed and each traversed node as internal. If the traverse returns empty `nodes`/`edges`, that is not an error — record the seed alone and continue.

Report: `Internal Position: <seed_count> seeds + <expanded_count> via relationships (hops=2).`

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

**6a. Cross-vocabulary search (primary path).** Internal entries speak implementation-language (symbols, file paths, library names — e.g. `gvproxy`, `vsock`, `SCM_RIGHTS`); ambient entries speak product-language (patterns, product names, capabilities — e.g. `egress-proxy for credentials`, `microVM`). Extract 2–4 concrete entities/patterns/product-terms from each cluster and query the *other* corpus with them:

```python
# product-terms extracted from the ambient cluster → query the internal corpus
distillery_search(query="<product-term from ambient>", limit=10, project="<project if specified>")

# implementation-terms extracted from the internal cluster → query the ambient corpus
distillery_search(query="<impl-term from internal>", entry_type="feed", limit=10,
                  published_after="<now - days, ISO>", include_evergreen=<bool>,
                  project="<project if specified>")
```

Run up to 3 such cross-queries per direction (≤6 total). Any entry returned that already sits in the *other* corpus's result set is a **seam** — a place where the two corpora actually connect on a shared concept under different vocabulary. Record the matched concept and the entry ids on both sides.

**Report a DISJOINT result as itself a finding.** If a product-term from the ambient cluster returns nothing internal, that is a real signal: *"the field is discussing X; we have no captured position on X."* Carry these disjoint terms into the Assessment as **Exposed** candidates.

**6b. Graph bridges (rare case, best-effort — NOT the primary path).** A genuine graph edge between an internal and an ambient entry is the strongest possible seam, but on a sparse graph it almost never exists (a live KB measured `orphan_rate=0.9977`, `bridges` returned `node_count=2`). Check best-effort and only if cheap:

```python
distillery_relations(action="metrics", metric="bridges", scope="global", limit=5)
```

If this returns the `INTERNAL` "NetworkX not installed" error, emit the one-line note `Run \`pip install distillery-mcp[graph]\` to enable bridges.` and skip the rest of 6b — do not treat it as a hard failure. If `results` is empty or no bridge connects an internal id to an ambient id, say so in one line and move on. Never block the seam analysis on graph bridges.

**Do NOT use embedding `find_similar` to bridge.** `find_similar` from an internal seed returns only *more internal* entries (implementation-language and product-language occupy different embedding neighborhoods). A seam must be backed by cross-vocabulary search (6a) or a real graph edge (6b) — **never** claim a seam that embedding similarity alone produced.

Report: `Where They Meet: <S> cross-vocabulary seams, <D> disjoint ambient terms, <G> graph bridges.`

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

Default is display-only. When `--store` is passed, follow the CONVENTIONS.md dedup-on-store pattern before writing.

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

Guidance-first order — the verdict leads, the evidence follows. Omit any empty section.

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

<2–3 paragraph narrative of what we have captured, with [Entry <short-id>] citations and the relationship map if relations exist. Omit body if sparse internal — state so.>

---

## Ambient Signal

<2–3 paragraph narrative of what the field (feeds + bookmarks) is saying in the window, with [Entry <short-id>] citations. Omit body if sparse ambient — state so.>

---

## Where They Meet

<Cross-vocabulary seams (matched concept + both-side entry ids), disjoint ambient terms ("the field is discussing X; we have no captured position on X"), and any graph bridge found. Omit if neither corpus has entries.>

---

## Sources

| Short ID | Type | Author | Date | Provenance |
|----------|------|--------|------|------------|
| 1a2b3c4d | [feed] | — | 2026-06-12 | ambient |
| 9f8e7d6c | [github] | Alice | 2026-05-30 | internal |

---

[digest] Stored: <entry_id>
Project: <project> | Author: <author>
Summary: <first 200 chars of assessment>...
Tags: compass, assessment, ambient
```

The stored block at the bottom appears only when `--store` was passed and a new entry was created.

## Rules

- NEVER use Bash, Python, or any tool not listed in allowed-tools
- If an MCP tool call fails, report the error to the user and STOP. Do not attempt workarounds.
- The Assessment section comes FIRST in the output — verdict before evidence
- Always use `[Entry <short-id>]` citation format (short-id = first 8 chars of UUID); mark each citation `internal` or `ambient`
- Every Assessment bullet must cite at least one entry — never assert a verdict without evidence
- Deduplicate each corpus's result set by entry id; an entry belongs to exactly one provenance (internal vs ambient) — never double-count
- Apply `--project` to ALL searches (internal and ambient) when set
- Internal Position uses one `distillery_search(expand_graph=true, expand_hops=2, output_mode="full")` call; the `--entry` variant uses one `distillery_relations(action="traverse", hops=2, direction="both")`
- Ambient Signal filters on `published_after` (publication time), not ingest time; first-poll backfill (`metadata.backfill=true`) is excluded unless `--include-evergreen`
- Default ambient window is 30 days — respect `--days`
- "Where They Meet" is cross-vocabulary search, NOT embedding similarity: extract entities/product-terms from one cluster and query the other corpus
- Graph bridges are best-effort and the rare case — never required, never the primary seam path; a sparse-graph empty result is not an error
- NEVER claim a seam that embedding similarity alone produced — a seam requires cross-vocabulary evidence or a real graph edge
- A disjoint result (no overlap between corpora on a term) is itself a finding — report it and feed it to the Assessment as an Exposed candidate
- Loop limits: up to 3 cross-vocabulary queries per direction (≤6 total) in Step 6
- Display-only by default; store only with `--store`
- When storing: follow CONVENTIONS.md dedup-on-store (create/skip/merge/link), use `entry_type="digest"`, include `compass` in tags, and metadata `period_start`/`period_end` as ISO 8601 dates
- When `distillery_relations(action="metrics")` returns the `"NetworkX not installed"` `INTERNAL` error, emit the one-line `pip install distillery-mcp[graph]` note and continue — treat any other relations error per CONVENTIONS.md error handling
- `distillery_relations`/`distillery_search` returning empty results is not an error — record 0 and continue
- Omit sections with no content — never display empty sections
- On MCP errors, see CONVENTIONS.md error handling — display and stop
- No retry loops — report errors and stop
