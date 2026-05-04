# Headline configuration (pre-registered)

This file pre-registers the single configuration cell of the LongMemEval bench whose
results may be cited as the "Distillery LongMemEval headline." It is committed
**before any number lands**, so that the choice of cell cannot be retro-fitted to
whatever scored best.

## The headline cell

| Axis           | Value         |
|----------------|---------------|
| `retrieval`    | `hybrid`      |
| `granularity`  | `session`     |
| `recency`      | `on`          |
| `embed`        | `bge-small`   |

These four values together define one — and only one — cell of the bench matrix.
Other cells (raw retrieval, per-turn granularity, recency off, alternate embed
models) exist as Distillery-vs-Distillery ablations. They are **not** the headline
and must never be quoted as such.

## The headline metric

The headline is **always** published as a triplet:

- **R@5** — recall at 5
- **R@10** — recall at 10
- **NDCG@10** — normalised discounted cumulative gain at 10

No single one of these is "the" number. Quoting one in isolation — on a badge,
in a blog post, in a slide — is a discipline violation. Three values, every time,
or none.

## Change control

The headline cell is immutable without:

1. A merged Architecture Decision Record under `docs/adr/` explaining why the
   cell is changing and what is being given up.
2. A corresponding update to this file in the same PR as the ADR.
3. The full headline triplet recomputed on the new cell, with provenance
   (code SHA, dataset SHA, model SHA), before any number from the new cell is
   published anywhere.

A headline that drifts silently is the failure mode this file exists to prevent.

## Rationale

This pre-registration is rule (1) of the project's publication discipline
("Pre-register the headline cell"). It exists to head off two specific
cautionary tales:

- **LongMemEval** itself ([Wu et al., ICLR 2025](https://arxiv.org/html/2410.10813v1)) —
  the paper's primary metric is GPT-4o-judged QA accuracy (§3.4). Distillery is
  a retrieval layer and does not produce that number. Pre-registering the cell
  *and* the metric triplet keeps the framing honest about what we are measuring.
- **Mempalace #875** ([github.com/mempalace/mempalace/issues/875](https://github.com/mempalace/mempalace/issues/875)) —
  retracted LongMemEval claims after configuration drift, top-k bypass artefacts,
  and metric-mixing with QA accuracy. The lesson is that without a pre-registered
  cell + triplet, a project will over time anoint whichever number looks best on
  whichever axis happened to win that night.
