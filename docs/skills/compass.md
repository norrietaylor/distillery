# /compass — Internal vs Ambient Directional Assessment

Contrasts your **internal implementation** knowledge (sessions, GitHub, minutes, reference, idea) against **ambient intelligence** (feeds + bookmarks), locates where the two corpora connect, and emits a **directional assessment** — Ahead / Exposed / Decide / Confirm — *first*, before the supporting detail. The assessment is the product; the corpus sections are the evidence.

Where `/radar` senses the surroundings and `/investigate` maps the internal terrain, `/compass` puts the two together and points somewhere.

## Usage

```text
/compass sandbox networking            # Orient on a topic
/compass agent eval harnesses --days 14 # Custom ambient window (default 30)
/compass --entry <uuid>                 # Seed from a specific entry instead of a topic
/compass build hermeticity --project distillery  # Scope every search to a project
/compass --include-evergreen            # Include first-poll backfill in ambient signal
/compass sandbox networking --store     # Persist the assessment (default: display-only)
```

**Trigger phrases:** "compass", "where do we stand vs the field", "ahead or behind on X", "what should we do about X"

## When to Use

- "Where do we stand on X vs. the field, and what should we do?"
- Comparing internal progress against external/ambient signal to surface gaps and risks
- Pre-decision check: is the field discussing something you have no captured position on?
- Orienting a specific entry against ambient signal (`--entry <uuid>`)

## What It Does

### Internal Position (non-graph search)

Maps the internal terrain with **one** plain semantic search scoped to the implementation corpora (`session`, `github`, `minutes`, `reference`, `idea`) in `summary` mode. There is **no graph expansion** — the knowledge graph is sparse (orphan-heavy), so a graph walk adds latency without signal. The `--entry <uuid>` variant loads the seed entry directly, derives a topic from it, then runs the same scoped search to gather the surrounding terrain.

### Ambient Signal (radar-style, windowed)

Senses the surroundings with two windowed searches — feeds and bookmarks — bounded by the ambient window (default 30 days). The window is bounded by `metadata.published_at` (publication time), not ingest time, so older items polled today are not counted as new intelligence. First-poll backfill (`metadata.backfill = true`) is excluded unless `--include-evergreen` is passed.

### Where They Meet (cross-corpus seam)

The comparative step uses **cross-vocabulary search**, not embedding similarity or graph edges. Internal entries speak implementation-language (symbols, file paths, library names); ambient entries speak product-language (patterns, product names, capabilities) — the two occupy different embedding neighborhoods. Compass extracts up to 2 concrete entities/terms from each cluster and queries the *other* corpus with them (≤4 cross-queries total). A cross-query **hit** is a seam — the corpora connect on a shared concept expressed in different vocabulary. A **disjoint** result (the field discusses X, you have no captured position on X) is itself a finding and becomes an *Exposed* candidate.

### Assessment

The verdict leads. Each bullet cites entries with `[Entry <short-id>]` (first 8 chars of the UUID), marked `internal` or `ambient`, across four categories (any empty category is omitted):

- **Ahead** — you lead, or already have what the field is converging on.
- **Exposed** — the field has it; you don't. A gap or risk.
- **Decide** — an open question both corpora touch but no settled internal decision exists.
- **Confirm** — an internal assumption the ambient signal validates or challenges.

## Output Format

```text
# Compass: sandbox networking

Oriented "sandbox networking": 6 internal + 4 ambient entries, 2 seams (window=30d).

## Assessment

**Ahead**
- We already ship the vsock transport the field is now converging on [Entry 9f8e7d6c, internal]

**Exposed**
- The now-GA egress-proxy-for-credentials pattern [Entry 1a2b3c4d, ambient] is not a captured requirement in the still-open egress issue [Entry 9f8e7d6c, internal] — add it

## Internal Position
<2–3 paragraph narrative with [Entry <short-id>] citations>

## Ambient Signal
<2–3 paragraph narrative of what feeds + bookmarks are saying in the window>

## Where They Meet
<Cross-vocabulary seams and disjoint ambient terms>

## Sources
| Short ID | Type | Author | Date | Provenance |
|----------|------|--------|------|------------|
| 1a2b3c4d | [feed] | — | 2026-06-12 | ambient |
| 9f8e7d6c | [github] | Alice | 2026-05-30 | internal |
```

## Options

| Flag | Description |
|------|-------------|
| `--days <n>` | Ambient look-back window in days (default 30), applied via `published_after` |
| `--project <name>` | Scope every search (internal and ambient) to this project |
| `--entry <uuid>` | Seed the Internal Position from a specific entry instead of a topic search |
| `--include-evergreen` | Include older / first-poll backfill items in the ambient candidate set |
| `--store` | Store the assessment as a `digest` entry (default: display-only) |

## Tips

- The verdict comes **first** — read the Assessment, then dig into the evidence sections below it.
- A disjoint result is a feature, not a miss: "the field is discussing X; we have no captured position on X" is exactly the kind of gap `/compass` exists to surface.
- When the project is only inferred from your cwd (no `--project`), compass scopes softly and auto-widens to all projects if the internal search comes up empty — the topic often lives in another repo.
- Display-only by default; pass `--store` to persist with tags `compass/assessment/ambient` for later retrieval.
- Pairs with `/radar` (ambient digest) and `/investigate` (internal deep context) — `/compass` is the directional synthesis of the two.
