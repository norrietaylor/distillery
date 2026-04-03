# Clarifying Questions — Round 1

## Q1: Migration
**Q:** How to handle transition for existing skill references?
**A:** Hard remove immediately — remove tools and update all skills/tests in one PR.

## Q2: Eval
**Q:** Update eval scenarios?
**A:** Yes — update all eval YAML and promptfoo configs to use new tool names/params.

## Q3: Ordering
**Q:** Sequential or parallel consolidation?
**A:** All at once — single PR consolidating all 6 tools.
