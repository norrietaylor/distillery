# T03 Proof Artifacts: Tooling Configuration Alignment

## Summary

Task T03 updated `pyproject.toml` to align ruff, mypy, and pytest configuration with agentry conventions. The expanded ruff lint rules surfaced violations in source and test files, all of which were fixed so that all three quality gates pass cleanly.

## Configuration Changes Made

### pyproject.toml additions
- `[tool.ruff.lint]` with `select = ["E", "W", "F", "I", "N", "UP", "B", "C4", "SIM"]` and `ignore = ["E501"]`
- `[tool.ruff.lint.isort]` with `known-first-party = ["distillery"]`
- `[[tool.mypy.overrides]]` for `tests.*` relaxing `disallow_untyped_defs` and `disallow_incomplete_defs`
- `[tool.pytest.ini_options]` extended with `addopts = ["-v", "--strict-markers", "--tb=short"]` and `markers` for `unit` and `integration`

### Code fixes to pass expanded rules
- `src/distillery/models.py`: Changed `EntryType`, `EntrySource`, `EntryStatus` from `str, Enum` to `StrEnum` (UP042)
- `src/distillery/classification/models.py`: Changed `DeduplicationAction` from `str, Enum` to `StrEnum` (UP042)
- `src/distillery/embedding/jina.py`: Simplified if/else to single expression (SIM108)
- `src/distillery/embedding/openai.py`: Used `contextlib.suppress` instead of `try/except/pass` (SIM105)
- `src/distillery/store/duckdb.py`: Added `strict=True` to three `zip()` calls (B905)
- Multiple test files: Converted `dict(key=val)` calls to `{"key": val}` literals (C408), added `strict=True` to `zip()` (B905)
- Auto-fixed 89 violations (I001 import order, UP037 quoted annotations, UP045 Optional -> X|None, UP015 mode arg, UP035 List->list, UP006 List annotation, UP017 timezone.utc, UP037 quoted annotations)

## Proof Artifacts

| File | Type | Command | Status |
|------|------|---------|--------|
| T03-01-cli.txt | cli | `ruff check src/ tests/` | PASS |
| T03-02-cli.txt | cli | `mypy --strict src/distillery/` | PASS |
| T03-03-cli.txt | cli | `pytest` | PASS |

## Results

All three quality gates pass with zero errors after configuration and code changes.
