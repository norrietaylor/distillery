# T01 Proof Summary — GitHub Token Passthrough for Private Repo Polling

## Task

Wire `GITHUB_TOKEN` through `_build_adapter()` to `GitHubAdapter`, verify redirect following,
ensure token never leaks to metadata/logs, and confirm unauthenticated fallback works.

## Changes Made

- `src/distillery/feeds/poller.py` — `_build_adapter()` now reads `GITHUB_TOKEN` from env
  and passes it to `GitHubAdapter(token=...)`. Added DEBUG-level log indicating auth vs
  unauth mode (token value is never logged).
- `src/distillery/feeds/github.py` — Added `follow_redirects=True` to `httpx.Client` in
  `GitHubAdapter.fetch()`.
- `tests/test_poller.py` — Added `TestBuildAdapterGitHubToken` class with 3 tests.
- `tests/test_security.py` — Added 3 new tests to `TestSecretRedactFilter` covering
  `ghp_`, `github_pat_`, and `gho_` token redaction in log output.

## Proof Artifacts

| File | Type | Status |
|------|------|--------|
| T01-01-test.txt | test | PASS — 6 new tests pass |
| T01-02-cli.txt | cli (mypy) | PASS — no type errors in modified files |

## Security Verification

- Token is passed as constructor argument, never stored in entry metadata (confirmed by
  reviewing `_item_to_entry_kwargs` — only `source_url`, `source_type`, `external_id`,
  `relevance_score`, `title`, `item_url`, `published_at` are stored).
- DEBUG log messages describe auth mode but never log the token value itself.
- `security.py` already contained `ghp_`, `gho_`, `github_pat_` redaction patterns;
  three new tests confirm they work on log record args as well as messages.
