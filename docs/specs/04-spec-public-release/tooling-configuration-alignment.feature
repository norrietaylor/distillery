# Source: docs/specs/04-spec-public-release/04-spec-public-release.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: Tooling Configuration Alignment

  Scenario: Ruff lint passes with expanded rule set
    Given pyproject.toml ruff lint select includes "E", "W", "F", "I", "N", "UP", "B", "C4", "SIM"
    And pyproject.toml ruff lint ignore includes "E501"
    And pyproject.toml ruff lint isort sets known-first-party to "distillery"
    When a developer runs "ruff check src/ tests/"
    Then the command exits with code 0
    And no lint errors are reported on stdout

  Scenario: Mypy strict passes with test override
    Given pyproject.toml mypy overrides disable strict defs for "tests.*" module
    When a developer runs "mypy --strict src/distillery/"
    Then the command exits with code 0
    And no type errors are reported

  Scenario: Pytest passes with strict markers and updated config
    Given pyproject.toml pytest addopts includes "-v", "--strict-markers", "--tb=short"
    And pyproject.toml pytest markers include "unit" and "integration"
    When a developer runs "pytest"
    Then the command exits with code 0
    And all tests pass
