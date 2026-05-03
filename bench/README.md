# bench/ — Distillery LongMemEval bench

This directory contains the discipline scaffolding, methodology, and (once
nightly automation lands) the auditable result receipts for Distillery's run
of the LongMemEval benchmark.

**Read these first, in order:**

1. [`HEADLINE.md`](./HEADLINE.md) — the pre-registered headline configuration
   cell and metric triplet. Immutable without an ADR.
2. [`LIMITATIONS.md`](./LIMITATIONS.md) — what the published numbers do and do
   not claim. Read before quoting any number.
3. [`METHODOLOGY.md`](./METHODOLOGY.md) — dataset, per-question protocol,
   metric definitions, variance gate.

## Quick reproduction

```bash
pip install -e ".[dev,fastembed]"
distillery bench longmemeval \
    --retrieval hybrid \
    --granularity session \
    --recency on \
    --embed-model bge-small
```

The CLI flags above will be wired by the `bench/cli-bench-subcommand` slice
(W2-cli). Until that lands, this command is the documented interface and not
yet executable.

Result JSONL files (one line per question, with the SHA provenance panel) will
be written to `bench/results/` — that directory will be populated by the
nightly automation slice (W2-workflow-yaml). A `bench/results/SUMMARY.md`
table will be auto-updated per nightly run, and a `bench/badge.json` (Shields
endpoint format) will carry the latest headline triplet for the README badges.

## What is *not* in this directory

- No competitor comparison tables (see [`LIMITATIONS.md`](./LIMITATIONS.md) §(d)).
- No QA-accuracy numbers (see [`LIMITATIONS.md`](./LIMITATIONS.md) §(a)).
- No bench numbers from before the variance gate has been characterised
  (rule (6) of the project's publication discipline).

## Structure (after all slices land)

```
bench/
  HEADLINE.md          # pre-registered headline cell + metric triplet
  LIMITATIONS.md       # what the numbers do not claim
  METHODOLOGY.md       # dataset, protocol, metrics, variance gate
  README.md            # this file
  badge.json           # Shields endpoint — populated by nightly automation
  results/             # auditable per-run JSONL receipts + SUMMARY.md
                       #   populated by nightly automation
```
