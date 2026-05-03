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

---

## What this means in practice

- A badge on the README shows the headline triplet **with a link to this file**.
- The MkDocs benchmarks page leads with a callout pointing here.
- Internal ablation tables are clearly labelled "Distillery configurations only."
- Per-question JSONL receipts and `summary.json` files always carry the SHA panel.
- A reviewer who finds a number anywhere in the project without the SHA panel
  should reject the PR or open an issue to retract.

## The escape hatch

> **If any limitation in this file becomes unsupportable, the LongMemEval
> dataset is dropped from the project, not weakened in framing.**

Concretely, that means: if discipline (a)–(e) cannot all be honoured — for
example, if the project is pressured to publish a single QA-accuracy-shaped
number, or to compare against another system on a shared axis, or to drop SHA
provenance for convenience — the correct response is to remove the LongMemEval
bench from this repository, not to soften this file.
