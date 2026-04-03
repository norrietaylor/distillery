# Source: docs/specs/08-spec-schema-migration/08-spec-schema-migration.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: Fly.io Migration Documentation

  Scenario: Documentation includes database migrations section
    Given the deploy/fly/README.md file exists
    When a deployer reads the documentation
    Then a "Database Migrations" section is present
    And it explains that additive migrations run automatically on startup

  Scenario: Pre-deploy backup command is documented
    Given the deploy/fly/README.md contains the Database Migrations section
    When a deployer looks for backup instructions
    Then the documentation includes a "fly ssh console" command running "distillery export"
    And the command outputs to a file on the /data volume

  Scenario: Volume snapshot backup is documented as alternative
    Given the deploy/fly/README.md contains the Database Migrations section
    When a deployer looks for alternative backup methods
    Then the documentation includes a "fly volumes snapshots create" command example

  Scenario: Breaking migration procedure is documented end-to-end
    Given the deploy/fly/README.md contains the Database Migrations section
    When a deployer follows the breaking migration procedure
    Then the steps include exporting data before deploy
    And deploying the new version
    And importing with --mode replace
    And verifying the result
    And removing the backup

  Scenario: Rollback procedure is documented
    Given the deploy/fly/README.md contains the Database Migrations section
    When a deployer needs to rollback a failed migration
    Then the documentation describes restoring from a volume snapshot
    And the documentation describes restoring from a JSON backup using "distillery import --mode replace"
