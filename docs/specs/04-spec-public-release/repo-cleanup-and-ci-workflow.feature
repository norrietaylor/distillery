# Source: docs/specs/04-spec-public-release/04-spec-public-release.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Repo Cleanup & CI Workflow

  Scenario: No compiled Python files are tracked in git
    Given the repository has been cleaned of binary artifacts
    When a developer runs "git ls-files '*.pyc'"
    Then the command produces no output
    And no __pycache__ directories appear in tracked files

  Scenario: Brainstorm document is relocated to docs directory
    Given the repository cleanup has been performed
    When a developer checks for distillery-brainstorm.md at the repo root
    Then the file does not exist at the repo root
    And the file exists at docs/distillery-brainstorm.md
    And git log shows the file move was performed with history preservation

  Scenario: CI workflow file exists with required quality gates
    Given the repository includes .github/workflows/ci.yml
    When a developer reads the CI workflow configuration
    Then the workflow triggers on push to main
    And the workflow triggers on pull requests to main
    And the workflow runs on ubuntu-latest with Python 3.11
    And the workflow includes a step that runs "ruff check src/ tests/"
    And the workflow includes a step that runs "mypy --strict src/distillery/"
    And the workflow includes a step that runs "pytest"

  Scenario: CI workflow fails when any quality gate fails
    Given the CI workflow is configured with lint, typecheck, and test steps
    When any one of the quality gate steps exits with a non-zero code
    Then the overall workflow run is marked as failed
    And the pull request cannot merge with a failed status
