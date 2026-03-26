Feature: CLI Entry Point and Dependency Cleanup
  As a developer
  I want a working `distillery` CLI with status and health commands
  So that I can verify my local setup without launching the MCP server

  Background:
    Given a valid distillery.yaml configuration file
    And DuckDB is accessible at the configured database path

  Scenario: distillery status displays database statistics
    When I run `distillery status`
    Then the output contains "total_entries"
    And the output contains "entries_by_type"
    And the output contains "entries_by_status"
    And the output contains "database_path"
    And the output contains "embedding_model"
    And the exit code is 0

  Scenario: distillery health verifies database connectivity
    When I run `distillery health`
    Then the output contains "OK"
    And the exit code is 0

  Scenario: distillery health reports failure for unreachable database
    Given an invalid database path in the configuration
    When I run `distillery health`
    Then the exit code is 1

  Scenario: distillery --version prints the package version
    When I run `distillery --version`
    Then the output contains "distillery 0.1.0"
    And the exit code is 0

  Scenario: distillery with no subcommand prints help
    When I run `distillery`
    Then the output contains "usage"
    And the exit code is 0

  Scenario: distillery with invalid subcommand shows error
    When I run `distillery frobnicate`
    Then the exit code is not 0

  Scenario: CLI respects --config override
    Given a custom config file at "/tmp/test-distillery.yaml"
    When I run `distillery status --config /tmp/test-distillery.yaml`
    Then the configuration is loaded from "/tmp/test-distillery.yaml"
    And the exit code is 0

  Scenario: CLI uses DISTILLERY_CONFIG environment variable
    Given the DISTILLERY_CONFIG environment variable is set to a valid config path
    When I run `distillery status`
    Then the configuration is loaded from the environment variable path
    And the exit code is 0

  Scenario: Core dependencies exclude dev tools
    When I run `pip install .` without the dev extra
    Then pytest is not installed
    And mypy is not installed
    And ruff is not installed
    And duckdb is installed
    And httpx is installed
    And mcp is installed

  Scenario: Dev dependencies include all tooling
    When I run `pip install ".[dev]"`
    Then pytest is installed
    And pytest-asyncio is installed
    And pytest-cov is installed
    And mypy is installed
    And ruff is installed
    And types-PyYAML is installed

  Scenario: CLI module passes strict linting and type checking
    When I run `ruff check src/distillery/cli.py`
    Then the exit code is 0
    When I run `mypy --strict src/distillery/cli.py`
    Then the exit code is 0
