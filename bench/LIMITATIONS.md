# Limitations — read this before quoting any number

This file is the precondition for the LongMemEval bench existing in this
project. **If any limitation listed here ever becomes unsupportable, the
LongMemEval dataset is dropped from the project — not weakened in framing.**

Reviewers: read this file before approving any PR that lands a number.

---

## WHAT THIS NUMBER DOES NOT CLAIM

The headline triplet (R@5, R@10, NDCG@10) measures **retrieval recall and
ranking quality** of the Distillery store on the LongMemEval-S corpus. It does
**not** claim — and must not be cited as claiming — any of the following.

### (a) Not comparable to the LongMemEval QA-accuracy leaderboard

LongMemEval's *official primary metric* is **GPT-4o-judged QA accuracy** —
a generator reads the retrieved context and answers the question, and a judge
LLM scores correctness. This is described in the paper's §3.4 (Wu et al.,
[arxiv 2410.10813](https://arxiv.org/html/2410.10813v1)). R@k and NDCG@k are
diagnostic supplements that the paper itself uses for ablation, not the primary
score.

Distillery is a **retrieval layer**, not a QA system. It has no generator and
no judge. So Distillery reports retrieval metrics — the diagnostic supplements —
and **never** the primary QA-accuracy metric.

Mixing the two is a **category error**. You cannot say "Distillery scores 0.X"
on the same axis as a leaderboard entry that scores QA accuracy. They are
different quantities measured in different units against different rubrics.

This exact pattern — quoting recall numbers next to QA-accuracy numbers as if
they were comparable — is what Mempalace's
[issue #875](https://github.com/mempalace/mempalace/issues/875) cites as the
cause of their retraction. We do not repeat it here.

### (b) Cross-granularity numbers are non-comparable

The bench supports two granularities:

- `granularity=session` — one corpus document per haystack session. Document IDs
  look like `<sess>`.
- `granularity=turn` — one corpus document per user turn within a session.
  Document IDs look like `<sess>_turn_<n>`.

These produce different `corpus_id` namespaces and different corpus sizes. A
"top-5 hit" in the per-turn corpus is a different event from a "top-5 hit" in
the per-session corpus. **Comparing R@k across granularities is meaningless.**
Numbers from different granularities are reported in separate tables and must
never be averaged, ranked, or graphed against each other on a shared axis.

### (c) Cross-embed-model numbers carry an HNSW caveat

Different embedding models produce vectors of different dimensionality and
different similarity-distribution shape. The HNSW index (via DuckDB VSS) is
constructed from those vectors — so changing the embed model changes the graph,
not just the points.

This means a `bge-small` vs `bge-large` comparison is a **system-level**
comparison (different model + different graph), not a pure model comparison.
Cross-embed-model results are reported with this caveat in line. They are
useful for "which configuration should we ship" decisions; they are not
suitable for claims of the form "model X is better than model Y."

### (d) No competitor comparison tables — anywhere

This project publishes **Distillery-vs-Distillery comparisons only**. No table,
chart, badge, blog post, or slide produced by this project will compare a
Distillery number against a Mempalace, LangChain, LlamaIndex, vector-DB-vendor,
or any other third-party number. Internal ablations only — raw vs hybrid,
recency on vs off, granularity session vs turn, etc.

This is rule (3) of the project's publication discipline. The reason is the
same one as (a): the underlying numbers are not comparable across systems
without controlling for the QA generator, judge model, prompt, retrieval-chunk
shape, and embed model — none of which we control across the table.

### (e) No SHAs ⇒ not a claim

Every number this project publishes ships with a provenance panel:

- `git_sha` — the Distillery commit that produced the run
- `dataset_revision_sha` — the HuggingFace dataset commit
- `embed_model_sha` — the model file digest
- `python_version` — the interpreter

A number without all four is not a Distillery claim. Reviewers, blog readers,
and downstream tooling should treat any LongMemEval-shaped number that does not
carry this panel as folklore until the panel is reconstructed.

### (f) No graph value-add claim on LongMemEval (Cell A is a regression gate, Cell B is deferred)

LongMemEval is a **single-user, single-session** benchmark. Each question is
scored against a haystack of sessions belonging to one user; nothing in the
dataset exercises the graph hypothesis (cross-user / cross-session entry
relations) that motivates Distillery's graph features (PRs #422–#429, epic
#147).

The bench's coverage of the graph-enabled retrieval path is therefore split
into two cells, **only one of which produces a publishable number**:

- **Cell A — graph regression gate (DO).** The same headline cell config
  (`hybrid / session / recency-on / bge-small`, 500q × 5 seeds) re-run with
  `--expand-graph` enabled. Pass criterion: Cell A's mean R@5 must be within
  the variance-gate threshold (default 0.5pp) of the HEADLINE mean. This
  catches *accidental regressions* on the graph-enabled path. It is
  filed under HEADLINE-shaped infrastructure (`bench-graph-regression-cell.yml`,
  `bench/results/graph_regression_cell_a.json`) and the 0.5.0 release notes
  may say "no regression with graph enabled" if the gate passes.

  **Status (until graph PRs land).** PRs #422–#429 are still open at the
  time this discipline note ships. Until they merge, `--expand-graph` is
  *metadata and output-routing only* in the LongMemEval runner: the flag
  records the `expand_graph` axis on every receipt and routes Cell A
  outputs into a separate subdirectory so receipts cannot be confused with
  HEADLINE, but the underlying `store.search` call site is unchanged.
  Cell A is therefore a forward-compatible scaffold for the regression
  gate, not yet an active measurement of the graph-enabled path. Once
  the graph PRs merge, the runner is wired to invoke graph-enabled
  retrieval at the same call site and the gate becomes live without
  further workflow or docs changes.

- **Cell B — graph value-add (DEFER).** A claim of the form "graph features
  improve LongMemEval" is **not supported** because LongMemEval doesn't
  contain the structure graph features are designed to exploit. Such a
  claim is deferred to a fit-for-purpose eval — multi-hop QA, a synthetic
  team-knowledge eval, or a `/investigate` / `/pour` synthesis eval — once
  one exists. Until then, no public surface (README, blog, slide, this
  page) may claim that graph features improve LongMemEval scores.

Concretely, this means: a Cell A run with mean R@5 *higher* than HEADLINE
is **not a value-add result** — it is within the noise band the variance
gate already characterises (`bench/results/variance_baseline.json`), and
LongMemEval is the wrong measurement instrument for the value-add question
regardless. The 0.5.0 release notes claim "no regression with graph
enabled" — never "graph improves LongMemEval."

---

## What this means in practice

- A badge on the README shows the headline triplet **with a link to this file**.
- The MkDocs benchmarks page leads with a callout pointing here.
- Internal ablation tables are clearly labelled "Distillery configurations only."
- Per-question JSONL receipts (`results_*.jsonl`) and per-cell `summary_*.json` files always carry the SHA panel; the aggregated `bench/results/SUMMARY.md` is regenerated from them.
- A reviewer who finds a number anywhere in the project without the SHA panel
  should reject the PR or open an issue to retract.

## The escape hatch

> **If any limitation in this file becomes unsupportable, the LongMemEval
> dataset is dropped from the project, not weakened in framing.**

Concretely, that means: if discipline (a)–(f) cannot all be honoured — for
example, if the project is pressured to publish a single QA-accuracy-shaped
number, or to compare against another system on a shared axis, or to drop SHA
provenance for convenience — the correct response is to remove the LongMemEval
bench from this repository, not to soften this file.
