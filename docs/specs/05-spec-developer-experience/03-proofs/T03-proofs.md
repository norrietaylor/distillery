# T03: CI Hardening - Proof Summary

## Task
Expand CI to test Python 3.11/3.12/3.13 with pip caching, enforce 80% coverage threshold,
upload coverage artifacts, and apply @pytest.mark.unit/@pytest.mark.integration markers
to all test files.

## Proof Artifacts

| File | Type | Status | Description |
|------|------|--------|-------------|
| T03-01-test.txt | test | PASS | Unit-marked tests: 234 collected, marker applied to 7 files |
| T03-02-test.txt | test | PASS | Integration-marked tests: 191 collected and passing, marker applied to 5 files |
| T03-03-cli.txt | cli | PASS | Coverage 83.78% >= 80% threshold; coverage.xml generated |
| T03-04-file.txt | file | PASS | ci.yml matrix, pip caching, coverage step, artifact upload verified |

## Changes Made

### .github/workflows/ci.yml
- Added matrix strategy: Python 3.11, 3.12, 3.13 with fail-fast: false
- Added pip caching via `cache: "pip"` in actions/setup-python@v5
- Replaced bare `pytest` with `pytest --cov=src/distillery --cov-report=xml --cov-report=term-missing --cov-fail-under=80`
- Added `actions/upload-artifact@v4` step to upload `coverage.xml` per Python version with 14-day retention

### pyproject.toml
- Added `[tool.coverage.run]` section with `omit` for `__main__.py` entry-point scripts
- Added `[tool.coverage.report]` section with `fail_under = 80` and `show_missing = true`

### Test Files - Unit Markers Applied
- `tests/test_classification_engine.py`
- `tests/test_cli.py`
- `tests/test_config.py`
- `tests/test_dedup.py`
- `tests/test_embedding.py`
- `tests/test_entry.py`
- `tests/test_store_protocol.py`

### Test Files - Integration Markers Applied
- `tests/test_duckdb_store.py`
- `tests/test_mcp_classify.py`
- `tests/test_mcp_dedup.py`
- `tests/test_mcp_server.py`
- `tests/test_store_integration.py`

## Coverage Result
Total coverage: 83.78% (threshold: 80%) - PASS
