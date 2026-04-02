# Source: docs/specs/02-spec-eval-supplement/02-spec-eval-supplement.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: promptfoo PR CI Gate

  Scenario: promptfoo config defines smoke-test scenarios for critical skill paths
    Given the Distillery repository is checked out
    When the user runs "npx promptfoo@latest eval --config promptfooconfig.yaml --dry-run"
    Then the command exits with code 0
    And stdout lists at least 5 test scenarios
    And the listed scenarios cover distill, recall, bookmark, pour, and watch skills

  Scenario: promptfoo eval completes successfully against MCP server
    Given the Distillery MCP server is running
    And promptfooconfig.yaml is present at the repository root
    When the user runs "npx promptfoo@latest eval --config promptfooconfig.yaml"
    Then the command exits with code 0
    And stdout reports all assertions passed
    And no assertion failures are listed in the output

  Scenario: promptfoo scenarios assert expected MCP tool calls
    Given the Distillery MCP server is running
    And a promptfoo scenario targeting the recall skill is configured
    When the user runs "npx promptfoo@latest eval --config promptfooconfig.yaml"
    Then the eval output confirms the expected MCP tool was called
    And the tool arguments contain the required search query field
    And the response content includes the expected substring

  Scenario: PR eval workflow triggers on pull request events
    Given the repository contains .github/workflows/eval-pr.yml
    And the workflow is configured with "on: pull_request" targeting main
    When a pull request is opened against the main branch
    Then the eval-pr.yml workflow is triggered
    And the workflow installs promptfoo via npx
    And the workflow run completes within 2 minutes

  Scenario: PR eval workflow fails when an assertion fails
    Given the eval-pr.yml workflow is running
    And the promptfoo config contains a scenario with a deliberately failing assertion
    When the promptfoo eval executes in CI
    Then the workflow exits with a non-zero status
    And the workflow log indicates which scenario assertion failed

  Scenario: promptfoo output directories are excluded from version control
    Given promptfoo has been run locally and created a .promptfoo/ directory
    When the user runs "git status"
    Then the .promptfoo/ directory does not appear in untracked files
    And .gitignore contains an entry for .promptfoo/
