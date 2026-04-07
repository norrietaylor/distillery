# Clarifying Questions — Round 1

## Scope

- **Q:** Should #62 (DuckDB versioning) be included?
- **A:** Skip — already fully implemented (migrations.py, schema_version, duckdb_version, vss_version tracked)

## #74: GitHub PAT for Private Repos

- **Q:** What level of per-source auth?
- **A:** Global `GITHUB_TOKEN` only — single env var shared by all GitHub sources. Poller must pass token to adapter.

## #148: Audit Log Metrics

- **Q:** Scope of audit metrics response?
- **A:** Full scope as proposed in issue — recent_logins, login_summary, active_users, recent_operations, with optional date_from/user filters.

- **Q:** Layering for audit log reads?
- **A:** Add `query_audit_log` method to DistilleryStore protocol — consistent with existing patterns.
