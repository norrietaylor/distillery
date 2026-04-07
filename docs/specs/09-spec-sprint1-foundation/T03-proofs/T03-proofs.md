# T03 Proof Summary: Audit Metrics Scope in distillery_metrics

## Task

Add `scope="audit"` to `_handle_metrics` in `src/distillery/mcp/tools/analytics.py`,
returning a 4-section response (recent_logins, login_summary, active_users,
recent_operations) using `store.query_audit_log()` as the data source.

## Implementation

- Added `"audit"` to `_VALID_METRICS_SCOPES` in `analytics.py`
- Added `scope="audit"` branch in `_handle_metrics` dispatching to `_gather_audit()`
- `_gather_audit()` is a new async function building 4 sections:
  - `recent_logins`: auth events (auth_login, auth_login_failed, auth_org_denied), limit 50
  - `login_summary`: total_logins, unique_users, failed_attempts, org_denials
  - `active_users`: unique users with last_seen and operation_count, ordered by last_seen DESC
  - `recent_operations`: non-auth tool operations, limit 50
- `date_from` filters all sections; `user` filters recent_operations and active_users only
- Returns `INVALID_PARAMS` error if `entry_type` is passed with `scope="audit"`
- Returns `INVALID_PARAMS` error for non-string `date_from` or `user`

## Files Modified

- `src/distillery/mcp/tools/analytics.py` — implementation

## Files Created

- `tests/test_metrics_audit.py` — 27 integration tests

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T03-01-test.txt | test | PASS (27/27) |
| T03-02-lint.txt | lint | PASS |

## Test Results

27 tests, all passed:
- Response structure: 2 tests
- Empty audit log: 3 tests
- Recent logins (auth event filtering): 5 tests
- Recent operations (non-auth filtering): 3 tests
- Login summary totals: 4 tests
- Active users: 3 tests
- date_from filtering: 2 tests
- user filtering: 3 tests
- Incompatible params / validation: 3 tests

## Verification Commands

```bash
python3 -m pytest tests/test_metrics_audit.py -v
python3 -m ruff check src/distillery/mcp/tools/analytics.py tests/test_metrics_audit.py
python3 -m mypy --strict src/distillery/
```
