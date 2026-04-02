# Clarifying Questions — Round 1

## Q1: Scope
**Q:** How should we scope the ~25 action items?
**A:** Split into two specs. Spec A: skill/plugin quality. Spec B: MCP server refactoring + test gaps.

## Q2: server.py Split
**Q:** Include server.py split or defer?
**A:** Include — split into 7 domain modules per issue proposal.

## Q3: Test Coverage
**Q:** What coverage target for middleware and handlers?
**A:** 100% middleware + all 22 handlers.

## Q4: Module Structure
**Q:** Follow the issue's 7-module proposal?
**A:** Yes — crud.py, search.py, classify.py, quality.py, analytics.py, feeds.py, meta.py.

## Q5: Skill Directory
**Q:** Move skills from `.claude-plugin/skills/` to `skills/`?
**A:** Keep at `.claude-plugin/skills/` — user doesn't want skills auto-loading when developing in this repo.
