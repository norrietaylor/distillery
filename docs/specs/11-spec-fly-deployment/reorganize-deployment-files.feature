# Source: docs/specs/11-spec-fly-deployment/11-spec-fly-deployment.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Reorganize deployment files into deploy/ directory

  Scenario: Prefect deployment files are moved to deploy/prefect/
    Given the Distillery repository at the current commit
    When the user runs "ls deploy/prefect/"
    Then the output lists "prefect.yaml", "distillery.yaml", and "README.md"

  Scenario: Root directory no longer contains deployment configs
    Given the deployment files have been moved to deploy/prefect/
    When the user runs "ls distillery.yaml" in the repo root
    Then the command exits with a non-zero code
    And stderr contains "No such file"

  Scenario: Git history is preserved after file move
    Given the Prefect deployment files were moved using git mv
    When the user runs "git log --follow deploy/prefect/prefect.yaml"
    Then the output contains commit history predating the move

  Scenario: Prefect deploy command references updated path
    Given the file deploy/prefect/prefect.yaml exists
    When the user reads the comments in deploy/prefect/prefect.yaml
    Then the file contains a reference to "prefect deploy -f deploy/prefect/prefect.yaml"

  Scenario: Dev config cross-references both deployment providers
    Given the file distillery-dev.yaml exists at the repo root
    When the user reads the cross-reference comment in distillery-dev.yaml
    Then the comment references "deploy/prefect/distillery.yaml"
    And the comment references "deploy/fly/distillery-fly.yaml"

  Scenario: Existing tests pass after file reorganization
    Given the deployment files have been moved to deploy/prefect/
    When the user runs "pytest"
    Then the command exits with code 0
    And no test failures are reported
