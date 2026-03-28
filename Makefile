# Distillery development commands
# Works in devcontainer (system Python) and locally (.venv)

PYTHON ?= $(shell command -v python3 2>/dev/null || echo python)
PYTEST ?= $(shell command -v pytest 2>/dev/null || echo .venv/bin/pytest)
RUFF   ?= $(shell command -v ruff 2>/dev/null || echo .venv/bin/ruff)
MYPY   ?= $(shell command -v mypy 2>/dev/null || echo .venv/bin/mypy)

.PHONY: install test test-unit test-integration test-cov lint format typecheck check ci clean

## Install in editable mode with dev dependencies
install:
	pip install -e ".[dev]"

## Run full test suite
test:
	$(PYTEST) tests/ -v --tb=short

## Run unit tests only
test-unit:
	$(PYTEST) tests/ -m unit -v --tb=short

## Run integration tests only
test-integration:
	$(PYTEST) tests/ -m integration -v --tb=short

## Run tests with coverage
test-cov:
	$(PYTEST) tests/ --cov=src/distillery --cov-report=term-missing --cov-fail-under=80

## Lint with ruff
lint:
	$(RUFF) check src/ tests/

## Format with ruff
format:
	$(RUFF) format src/ tests/

## Type check with mypy
typecheck:
	$(MYPY) --strict src/

## Run all checks (lint + typecheck + test)
check: lint typecheck test

## Run CI pipeline locally (lint + typecheck + test with coverage)
ci: lint typecheck test-cov

## Remove build artifacts
clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache htmlcov coverage.xml .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
