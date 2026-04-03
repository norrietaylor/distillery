# Clarifying Questions — Round 1

## Q1: DuckDB Version Pin
**Q:** Pin to ~=1.2.0 (issue) or ~=1.5.0 (current installed)?
**A:** Pin to ~=1.5.0 — current installed version, allows patches, blocks minor bumps.

## Q2: Export/Import
**Q:** Implement full CLI commands now or defer?
**A:** Yes, implement now — first-class CLI commands for backup/restore.

## Q3: Rollback
**Q:** Forward-only or full rollback support?
**A:** Forward-only — backup before upgrade is the rollback strategy.

## Q4: Fly Deployment
**Q:** Include Fly.io migration strategy?
**A:** Document only — add migration notes to deploy/fly/README.md.
