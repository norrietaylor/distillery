# 08 — Clarifying Questions (Round 1)

## Scope

**Q:** Which Phase 2 infrastructure items should this spec cover?
**A:** Namespace taxonomy (#14) and Port type schemas (#16). Elasticsearch migration deferred.

**Q:** What is the primary goal?
**A:** Team readiness — prepare the data model and storage layer for multi-user / team use.

## Tag Format

**Q:** What tag format should hierarchical tags use?
**A:** Slash-separated (e.g. `project/billing-v2/decisions`).

## Type Validation

**Q:** Should new entry types enforce type-specific required metadata?
**A:** Strict validation — each type defines required metadata keys. Store rejects entries missing them.

## Migration

**Q:** Should existing flat tags be auto-migrated?
**A:** Coexist — old flat tags remain valid, hierarchical tags are opt-in. No migration needed.
