# Source: docs/specs/08-spec-schema-migration/08-spec-schema-migration.md
# Pattern: State + CLI/Process
# Recommended test type: Integration

Feature: Forward-Only Schema Migration System

  Scenario: Fresh database migrates from version 0 to version 6
    Given a fresh database with no tables
    When the store is initialized
    Then the schema version in _meta is 6
    And the entries table exists with all expected columns
    And the feed_sources table exists
    And the HNSW index exists on the entries table

  Scenario: Migrations are idempotent
    Given a database that has already been migrated to version 6
    When the store is initialized again
    Then the schema version remains 6
    And no errors are raised
    And all tables retain their existing data

  Scenario: Partial migration runs only pending migrations
    Given a database at schema version 3
    When the store is initialized
    Then migrations 4, 5, and 6 are applied
    And migrations 1, 2, and 3 are not re-executed
    And the schema version in _meta is 6

  Scenario: Failed migration rolls back the transaction
    Given a database at schema version 2
    And migration 3 is configured to raise an error
    When the store attempts initialization
    Then a RuntimeError is raised mentioning migration 3
    And the schema version in _meta remains 2
    And the database state is unchanged from before the attempt

  Scenario: Ad-hoc initialization calls are replaced by migration runner
    Given a fresh database with no tables
    When the store is initialized
    Then the initialization calls run_pending_migrations
    And no direct CREATE TABLE or ALTER TABLE calls occur outside the migration system

  Scenario: get_current_schema_version returns the correct version
    Given a database that has been migrated to version 6
    When get_current_schema_version is called with the database connection
    Then the return value is 6
