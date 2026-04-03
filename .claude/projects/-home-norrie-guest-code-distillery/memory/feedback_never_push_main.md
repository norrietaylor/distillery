---
name: never-push-main
description: Never push directly to main — always use feature branches and PRs
type: feedback
---

Never push commits directly to main. Always create a feature branch and PR.

**Why:** User explicitly requested this workflow. Commits landed on main had to be reverted and moved to a branch.

**How to apply:** After implementation tasks complete, create a feature branch before committing. Use `gh pr create` for review. Never `git push origin main`.
