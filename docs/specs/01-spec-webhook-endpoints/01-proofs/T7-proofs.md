# T7 Proof Summary

**Task:** T01.4 — Write tests for webhook auth, cooldowns, app composition, and disabled state

**Status:** PASS

## Artifacts

| File | Type | Status |
|------|------|--------|
| T7-01-test.txt | test | PASS |
| T7-02-cli.txt | cli | PASS |

## Results

- **T7-01-test.txt**: `pytest tests/test_webhooks.py -v` — 7 tests collected, 7 passed
- **T7-02-cli.txt**: `ruff check tests/test_webhooks.py` — All checks passed

## Tests implemented

1. `test_auth_missing_token` — POST /poll without Authorization header returns 401
2. `test_auth_wrong_token` — POST with wrong bearer token returns 401
3. `test_auth_valid_token` — POST with correct bearer token returns 200
4. `test_cooldown_enforced` — First request succeeds, immediate second returns 429 with Retry-After
5. `test_cooldown_persisted` — Cooldown written to DuckDB is visible to a new app instance using same store
6. `test_app_composition` — Parent Starlette app mounts both /api/* and /mcp paths correctly
7. `test_webhooks_disabled` — No /api routes when disabled via config flag or missing secret env var
