# Benchmarks

Distillery runs the [LongMemEval](https://arxiv.org/html/2410.10813v1) retrieval bench
nightly against its own pipeline. This page surfaces the most recent headline numbers, the
configurations Distillery ships, and — equally important — the things this number does
*not* claim.

This page is wired up before any number lands. The cells below show placeholders until the
first stable nightly run completes and the variance gate (5-seed back-to-back execution,
stddev ≤ 0.5pp on R@5) confirms the bench is a useful regression signal. No number is
displayed here until that gate is green.

## Headline

The pre-registered headline triplet — Recall@5, Recall@10, NDCG@10 — for the headline cell
(`retrieval=hybrid, granularity=session, recency=on, embed=bge-small`).

<div class="grid cards" markdown>

-   __Recall@5__

    ---

    <!-- TODO: populated by first nightly -->
    `—`

    Headline cell, mean across seeds.

-   __Recall@10__

    ---

    <!-- TODO: populated by first nightly -->
    `—`

    Headline cell, mean across seeds.

-   __NDCG@10__

    ---

    <!-- TODO: populated by first nightly -->
    `—`

    Headline cell, mean across seeds.

</div>

## Configuration

The headline cell is pre-registered and immutable without an ADR. It does not change to
chase a number.

| Axis | Headline value |
|---|---|
| Retrieval | `hybrid` (BM25 + vector via Reciprocal Rank Fusion) |
| Granularity | `session` (one document per haystack session) |
| Recency | `on` (90-day linear decay, `recency_min_weight=0.5`) |
| Embed model | `bge-small` (`BAAI/bge-small-en-v1.5`, 384-dim, fastembed) |

Full pre-registration rationale and change-control rules live in
[`bench/HEADLINE.md`](../bench/HEADLINE.md).

## What this number does NOT claim

!!! warning "Read this before citing any number on this page"

    - These numbers are **retrieval metrics** (R@k, NDCG@k). They are **not comparable** to
      LongMemEval QA-accuracy leaderboard entries — the LongMemEval paper's primary metric
      is GPT-4o-judged QA accuracy, which requires a generator stack Distillery does not
      ship.
    - These numbers are **Distillery vs. Distillery only**. There are no competitor rows
      anywhere on this page, in the README, or in the auto-generated `bench/results/`
      summaries. Cross-system retrieval-vs-QA comparisons are a known category error.
    - **Cross-granularity** rows (`session` vs `turn`) are non-comparable to one another —
      the corpus_id space differs, so R@k means different things in each row.
    - **Cross-embed-model** rows carry an HNSW-construction caveat: the index is rebuilt
      per model, so insertion-order and seed effects are part of the score.
    - The headline number is the **mean** of multiple seeds. The corresponding stddev lives
      alongside it in `bench/results/variance_baseline.json`.

    Read the full limitations before citing this number →
    [bench/LIMITATIONS.md](../bench/LIMITATIONS.md)

## Internal comparison table

**Distillery configurations only.** No competitor rows. Each row is a single Distillery
configuration evaluated against the same LongMemEval-S question set with the same SHA-pinned
dataset and embedding model.

| Configuration | R@5 | R@10 | NDCG@10 |
|---|---|---|---|
| `hybrid + recency on` (headline) | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |
| `raw + recency on` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |
| `hybrid + recency off` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |
| `hybrid + granularity=turn` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |

The `granularity=turn` row is shown for ablation interest only; it is not directly
comparable to the session rows above (see the LIMITATIONS callout).

## Per-question-type breakdown

LongMemEval-S partitions questions into six types. The headline cell scores each
type independently.

| Question type | R@5 | R@10 | NDCG@10 |
|---|---|---|---|
| `knowledge-update` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |
| `multi-session` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |
| `temporal` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |
| `single-session-user` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |
| `single-session-preference` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |
| `single-session-assistant` | <!-- placeholder --> `—` | <!-- placeholder --> `—` | <!-- placeholder --> `—` |

## Methodology

The bench instantiates an in-memory `DuckDBStore` per question, fixes the PRNG seed before
ingestion to neutralise HNSW insertion-order non-determinism, ingests `haystack_sessions`
as entries with `metadata.session_id` populated, then runs `store.search(query, limit=50)`
and maps the returned session_ids back to the gold `answer_session_ids` for scoring.

Scoring is a textbook `dcg`/`ndcg`/`evaluate_retrieval` reimplementation in
`src/distillery/eval/scoring.py`, adapted to the existing `RetrievalMetrics` shape from
`src/distillery/eval/retrieval_scorer.py`. Every JSONL line carries a SHA panel
(`git_sha`, `dataset_revision_sha`, `embed_model_sha`, `python_version`) so any number on
this page can be reproduced bit-for-bit.

Full methodology and dataset citation:
[`bench/METHODOLOGY.md`](../bench/METHODOLOGY.md).

Dataset citation: Wu et al., *LongMemEval: Benchmarking Chat Assistants on Long-Term
Interactive Memory*, ICLR 2025 — [arxiv:2410.10813](https://arxiv.org/html/2410.10813v1).

## Reproduction

The bench runs offline. fastembed downloads model weights once, the dataset loader pins the
HuggingFace revision, and there is no API call in the hot loop.

```bash
pip install -e ".[dev,fastembed]"

distillery bench longmemeval \
    --retrieval hybrid \
    --granularity session \
    --recency on \
    --embed-model bge-small \
    --seeds 1
```

Outputs land in `bench/results/results_longmemeval_<mode>_<embed>_<UTC>.jsonl` plus a
`summary.json` next to it. The canonical reproduction guide — including the 5-seed variance
characterisation procedure — is in [`bench/README.md`](../bench/README.md).
