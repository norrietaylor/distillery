# Methodology

This document describes how the Distillery LongMemEval bench is run, scored,
and audited. It is the spec a reader needs to verify that the published
numbers correspond to a reproducible procedure.

For the limitations of these numbers, see [`LIMITATIONS.md`](./LIMITATIONS.md).
For the pre-registered headline configuration, see [`HEADLINE.md`](./HEADLINE.md).

## Dataset

- **Source.** HuggingFace dataset
  [`xiaowu0162/longmemeval-cleaned`](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned).
- **Split.** LongMemEval-S — the 115K-token-haystack variant. File:
  `longmemeval_s_cleaned.json`. ~500 questions.
- **Pin.** The dataset is downloaded via
  `huggingface_hub.snapshot_download(repo_id=..., revision=<commit_sha>)`. The
  commit SHA is hard-coded as a constant in
  `src/distillery/eval/longmemeval_dataset.py` and verified at load time.
  Until the dataset loader lands the pin, this slot reads:
  - `dataset_revision_sha = <TBD — populated by W1-dataset-loader>`
- **Integrity check.** SHA-256 of `longmemeval_s_cleaned.json` is compared
  against a constant in code. Mismatch ⇒ load fails loud, no silent fallback.
- **Cache.** `$XDG_CACHE_HOME/distillery/longmemeval/` (defaults to
  `~/.cache/distillery/longmemeval/`).
- **Known upstream issue.** The dataset config raises a `FeaturesError` on the
  `answer` column under some `datasets` versions. The loader handles this by
  reading the JSON file directly rather than going through `datasets.load_dataset`.

## Per-question protocol

Every question in the dataset is evaluated in isolation:

1. Instantiate a fresh `DuckDBStore(":memory:")`. No state survives between
   questions.
2. Set fixed PRNG seeds **before each question**:
   - `random.seed(seed)`
   - `numpy.random.seed(seed)`
   - any framework-specific seed (DuckDB, fastembed batching) that affects
     ordering
   This neutralises HNSW insertion-order non-determinism so that re-runs at the
   same seed produce identical rankings.
3. Ingest each item from `haystack_sessions` as a Distillery entry. The
   `haystack_session_id` (or `<sess>_turn_<n>` derivative for per-turn
   granularity) is stored on `entry.metadata.session_id` so it can be recovered
   from `SearchResult` after retrieval.
4. Call `store.search(question, limit=50)`. Top-50 is wide enough that R@5,
   R@10, and NDCG@10 are not truncated.
5. Map each `SearchResult.entry.metadata["session_id"]` back through the
   haystack to derive the predicted `answer_session_id`. Compare predicted
   ranking to the gold `answer_session_ids` from the dataset.
6. Emit one JSONL record per question with: question id, ranked predictions,
   distances, gold answer set, the per-question metric values, and the SHA
   panel.

A unit test (`tests/eval/test_session_id_round_trip.py`, landing with the
W1-fastembed slice) guards the round-trip — without it, a regression in
metadata persistence would silently report 0% recall.

## Metrics

The headline triplet:

- **R@5** — Recall at 5: of the gold answer sessions for a question, what
  fraction appear in the top 5 retrieved? Averaged across questions.
- **R@10** — Recall at 10: same as above, top 10.
- **NDCG@10** — Normalised Discounted Cumulative Gain at 10: rewards getting
  gold answer sessions ranked highly within the top 10. Normalised so a
  perfect ranking scores 1.0.

Plain English:

- R@5 = "Did we put the right answer in the top 5? How often?"
- R@10 = "Did we put the right answer in the top 10? How often?"
- NDCG@10 = "When we did, how high did we put it?"

Implementations will live in `src/distillery/eval/scoring.py` — that module
will be populated by the W1-scoring slice, alongside its 12-row test table.
This file will link to it directly once it lands. The functions are textbook
`dcg`, `ndcg`, and
`evaluate_retrieval` — reimplemented from scratch (not lifted from any other
project) and validated by a 12-row test table that pins behaviour on edge
cases (empty gold set, no hits, perfect ranking, etc.).

The bench also reuses the existing project type
`src/distillery/eval/retrieval_scorer.RetrievalMetrics` so that R@k / P@k / MRR
have the same shape across the eval suite and the bench.

## Variance protocol

Per publication discipline rule (6), the **first production run is a 5-seed
back-to-back execution of the headline cell**. We compute mean and standard
deviation of R@5 across the five runs.

- **If stddev(R@5) ≤ 0.5 percentage points:** the bench is a usable regression
  signal. Numbers may be published with the variance reported alongside the
  point estimate.
- **If stddev(R@5) > 0.5 percentage points:** the bench is too noisy to be a
  regression signal in its current form. Halt rollout. Audit determinism in
  this order: HNSW insertion order, RRF tie-break, fastembed batching, DuckDB
  query plan stability. Do not publish a number until the audit closes.

The 5-seed result lands at `bench/results/variance_baseline.json` and is
referenced from every public surface that quotes the headline.

## Reproducibility envelope

Every published number ships with the SHA panel from
[`LIMITATIONS.md`](./LIMITATIONS.md) §(e):

- `git_sha` (Distillery commit)
- `dataset_revision_sha` (HuggingFace revision)
- `embed_model_sha` (model file digest)
- `python_version`

Anyone with these four values, the dataset cache, and `pip install -e ".[dev,fastembed]"`
should reproduce the same JSONL output bit-for-bit at the same seed.

## Citation

If you cite the LongMemEval dataset itself, cite the original paper:

> Wu, D. et al. *LongMemEval: Benchmarking Chat Assistants on Long-Term
> Interactive Memory.* ICLR 2025. <https://arxiv.org/html/2410.10813v1>

Distillery's run of the bench is **not** an official LongMemEval result and
should not be cited as one — see [`LIMITATIONS.md`](./LIMITATIONS.md) §(a).
