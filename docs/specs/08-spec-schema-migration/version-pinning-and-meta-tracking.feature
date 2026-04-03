# Source: docs/specs/08-spec-schema-migration/08-spec-schema-migration.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Version Pinning and _meta Version Tracking

  Scenario: DuckDB version is pinned to compatible release range
    Given the distillery package is installed from the current pyproject.toml
    When the user runs "pip show duckdb"
    Then the installed DuckDB version starts with "1.5."

  Scenario: Schema version is recorded in _meta on fresh startup
    Given a fresh database with no existing _meta table
    When the store is initialized
    Then the _meta table contains a "schema_version" key with a numeric value
    And the _meta table contains a "duckdb_version" key matching the installed DuckDB version

  Scenario: VSS extension version is tracked in _meta
    Given a fresh database with no existing _meta table
    When the store is initialized
    Then the _meta table contains a "vss_version" key with a non-empty value

  Scenario: DuckDB version mismatch logs a warning
    Given a database where _meta contains duckdb_version "0.9.0"
    When the store is initialized with DuckDB version "1.5.1"
    Then a warning is logged indicating a DuckDB version mismatch
    And the _meta duckdb_version is updated to "1.5.1"

  Scenario: Startup log reports schema version and DuckDB version
    Given a database at schema version 6
    When the store is initialized
    Then the startup log contains "Schema at version 6"
    And the startup log contains "DuckDB 1.5"

  Scenario: distillery status displays schema and DuckDB versions
    Given the store has been initialized
    When the user runs "distillery status"
    Then the output contains the current schema version number
    And the output contains the current DuckDB version
