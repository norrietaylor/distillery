# Clarifying Questions — Round 1

## Q1: Retrieval Quality Measurement
**Answer:** Implicit feedback. Track which search results users actually use (click/reference) vs ignore. No extra user action needed.

## Q2: Content Lifecycle Policy
**Answer:** Manual archive only. No auto-archival. Add a `distillery_stale` tool that lists candidates for human review.

## Q3: Conflict Detection
**Answer:** Flag on store. When storing a new entry, detect semantic similarity + opposing sentiment/facts. Return warnings like dedup.

## Q4: Single-User Validation
**Answer:** Metrics dashboard tool. A `distillery_metrics` MCP tool showing entry counts over time, search frequency, feedback scores.
