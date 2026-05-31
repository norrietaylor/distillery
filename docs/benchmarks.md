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

<!-- BENCH:HEADLINE-CARDS:START -->
<div class="grid cards" markdown>

-   __Recall@5__

    ---

    `0.970`

    Headline cell, mean across seeds.

-   __Recall@10__

    ---

    `0.990`

    Headline cell, mean across seeds.

-   __NDCG@10__

    ---

    `0.898`

    Headline cell, mean across seeds.

</div>
<!-- BENCH:HEADLINE-CARDS:END -->

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
[`bench/HEADLINE.md`](https://github.com/norrietaylor/distillery/blob/main/bench/HEADLINE.md).

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
    [bench/LIMITATIONS.md](https://github.com/norrietaylor/distillery/blob/main/bench/LIMITATIONS.md)

## Internal comparison table

**Distillery configurations only.** No competitor rows. Each row is a single Distillery
configuration evaluated against the same LongMemEval-S question set with the same SHA-pinned
dataset and embedding model.

<!-- BENCH:MATRIX:START -->
| Configuration | R@5 | R@10 | NDCG@10 |
|---|---|---|---|
| `hybrid + recency on` (headline) | `0.970` | `0.990` | `0.898` |
| `raw + recency on` | `0.870` | `0.940` | `0.787` |
| `hybrid + recency off` | `0.970` | `0.990` | `0.891` |
| `hybrid + granularity=turn` | `0.980` | `1.000` | `0.680` |
<!-- BENCH:MATRIX:END -->

The `granularity=turn` row is shown for ablation interest only; it is not directly
comparable to the session rows above (see the LIMITATIONS callout).

## Per-question-type breakdown

LongMemEval-S partitions questions into six types. The headline cell scores each
type independently.

<!-- BENCH:PER-TYPE:START -->
| Question type | R@5 | R@10 | NDCG@10 |
|---|---|---|---|
| `knowledge-update` | `—` | `—` | `—` |
| `multi-session` | `1.000` | `1.000` | `0.914` |
| `temporal` | `—` | `—` | `—` |
| `single-session-user` | `0.957` | `0.986` | `0.891` |
| `single-session-preference` | `—` | `—` | `—` |
| `single-session-assistant` | `—` | `—` | `—` |
<!-- BENCH:PER-TYPE:END -->

## Graph features — Cell A regression gate, Cell B deferred

Issue [#458](https://github.com/norrietaylor/distillery/issues/458) splits the bench's
coverage of the graph-enabled retrieval path (PRs [#422](https://github.com/norrietaylor/distillery/pull/422)–[#429](https://github.com/norrietaylor/distillery/pull/429),
epic [#147](https://github.com/norrietaylor/distillery/issues/147)) into two cells. Only
one produces a publishable number.

### Cell A — graph regression gate (DO)

Same config as the HEADLINE cell (`hybrid / session / recency-on / bge-small`, 500q × 5
seeds), re-run with `--expand-graph` enabled. Cell A asks: **does enabling graph
features regress baseline recall when the entry graph is sparse?** The pass criterion
is that Cell A's mean R@5 stays within the variance-gate threshold (default 0.5pp) of
the HEADLINE mean.

!!! success "Status: gate live — first 500q × 5-seed result lands at delta = 0.0pp"

    The graph retrieval PRs ([#422](https://github.com/norrietaylor/distillery/pull/422)–[#429](https://github.com/norrietaylor/distillery/pull/429))
    merged ahead of the 0.5.0 release, and Cell A's regression-gate semantics
    are live. The first full-500q × 5-seed Cell A run on the v0.5.0 commit
    landed at **mean R@5 = 0.972** (stddev 0.000), exactly matching the
    HEADLINE mean of 0.972 over the same 500q sample for a **delta of 0.0pp**
    against the 0.5pp variance-gate threshold (`gate_pass=true`,
    `sample_size_match=true`). Run:
    [`actions/runs/25453787717`](https://github.com/norrietaylor/distillery/actions/runs/25453787717).
    Aggregate receipt: [`bench/results/graph_regression_cell_a.json`](https://github.com/norrietaylor/distillery/blob/main/bench/results/graph_regression_cell_a.json).

    Per the discipline in `bench/LIMITATIONS.md` §(f), this is a regression
    result only — *no* value-add claim is implied. Cell A passing means
    "enabling graph features did not regress baseline recall on
    LongMemEval-S" and nothing more. The graph hypothesis (cross-user /
    cross-session relations) is not exercised by LongMemEval and is deferred
    to Cell B.

- **Workflow.** [`.github/workflows/bench-graph-regression-cell.yml`](https://github.com/norrietaylor/distillery/blob/main/.github/workflows/bench-graph-regression-cell.yml)
  runs nightly at 06:00 UTC, sequenced after the HEADLINE workflow at 05:00 UTC.
  Nightly samples 100q for trending; full-500q runs (gate-relevant) are
  `workflow_dispatch` only and require a sample-size match against the
  committed `variance_baseline.json` before the gate is computed.
- **Aggregate.** Cell A's 5-seed mean + delta vs HEADLINE lands at
  `bench/results/graph_regression_cell_a.json`. Per-seed receipts live as workflow
  artifacts only (90-day retention) and are deliberately not committed — the repo
  must never accumulate a graph-receipt history that could be silently
  re-published as a HEADLINE claim.
- **Default-off.** Graph features remain default-off in production (the existing
  HEADLINE cell does not set `expand_graph`); Cell A exists as a separate axis
  and does not displace the public number.

### Cell B — graph value-add (DEFER)

A claim of the form "graph features improve LongMemEval" is deferred to a
fit-for-purpose eval. LongMemEval is a **single-user, single-session** benchmark
— each question is scored against one user's haystack — and does not exercise the
graph hypothesis (cross-user / cross-session entry relations) that motivates
Distillery's graph features. Measuring graph value-add on LongMemEval would be a
category error analogous to (a) above.

The deferred eval will be one of:

- a multi-hop QA dataset (questions whose answer requires traversing entry
  relations);
- a synthetic team-knowledge eval (multiple authors, cross-author lookups);
- an in-house `/investigate` or `/pour` synthesis eval that scores the value
  the graph adds to multi-document narrative answers.

Until that eval exists, **no public surface** (this page, the README, the blog,
the 0.5.0 release notes) may claim that graph features improve LongMemEval
scores. The 0.5.0 release notes claim "no regression with graph enabled" —
never "graph improves LongMemEval." Full discipline rationale is in
[`bench/LIMITATIONS.md`](https://github.com/norrietaylor/distillery/blob/main/bench/LIMITATIONS.md) §(f).

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
[`bench/METHODOLOGY.md`](https://github.com/norrietaylor/distillery/blob/main/bench/METHODOLOGY.md).

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
characterisation procedure — is in [`bench/README.md`](https://github.com/norrietaylor/distillery/blob/main/bench/README.md).
