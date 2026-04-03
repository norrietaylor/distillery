# Clarifying Questions — Round 1

## Q1: Scope
**Q:** How should we scope the 15 items?
**A:** High + Medium priority (items 1-8). Low priority deferred.

## Q2: Radar Consent
**Q:** /radar auto-stores digests. Fix approach?
**A:** Make `--no-store` the default. Require `--store` to persist.

## Q3: Tune Apply
**Q:** /tune manual YAML editing. Fix approach?
**A:** Add `distillery_configure` MCP tool that applies config changes at runtime.
