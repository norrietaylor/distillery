# Clarifying Questions — Round 1

## Q1: Scope
**Q:** Include all 4 workstreams or focus on a subset?
**A:** All 4 workstreams — single spec with 4 demoable units.

## Q2: CI Design
**Q:** Separate workflow or integrate into existing CI?
**A:** Separate workflow — new `eval-pr.yml` triggered on PRs, independent of nightly.

## Q3: RAGAS Dependency
**Q:** How should RAGAS be installed?
**A:** New optional dep group (`[ragas]` or `[eval-ragas]`) in pyproject.toml.

## Q4: Cost Store
**Q:** Where should historical cost data be persisted?
**A:** JSON baseline files — extend existing baseline JSON with cost fields, git-trackable.
