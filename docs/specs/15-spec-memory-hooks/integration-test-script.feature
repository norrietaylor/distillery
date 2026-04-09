# Source: docs/specs/15-spec-memory-hooks/15-spec-memory-hooks.md
# Pattern: CLI/Process + Error Handling
# Recommended test type: Integration

Feature: Integration test script

  Scenario: Test script validates UserPromptSubmit counter and nudge interval
    Given the test script is installed at scripts/hooks/test-hooks.sh
    And the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    When the user runs "bash scripts/hooks/test-hooks.sh"
    Then stdout contains a PASS result for UserPromptSubmit counter increment tests
    And stdout contains a PASS result for nudge firing at the configured interval
    And the command exits with code 0

  Scenario: Test script validates PreCompact extraction flow with mocked dependencies
    Given the test script is installed at scripts/hooks/test-hooks.sh
    And the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    When the user runs "bash scripts/hooks/test-hooks.sh"
    Then stdout contains a PASS result for PreCompact reading transcript
    And stdout contains a PASS result for PreCompact calling extraction
    And stdout contains a PASS result for PreCompact outputting summary
    And the command exits with code 0

  Scenario: Test script validates SessionStart delegation
    Given the test script is installed at scripts/hooks/test-hooks.sh
    And the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    When the user runs "bash scripts/hooks/test-hooks.sh"
    Then stdout contains a PASS result for SessionStart delegation
    And the command exits with code 0

  Scenario: Test script validates silent failure on unreachable server
    Given the test script is installed at scripts/hooks/test-hooks.sh
    And the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    When the user runs "bash scripts/hooks/test-hooks.sh"
    Then stdout contains a PASS result for silent failure when MCP server is unreachable
    And all hook invocations in the test exit with code 0

  Scenario: Test script mocks MCP server with nc listener
    Given the test script is installed at scripts/hooks/test-hooks.sh
    When the user runs "bash scripts/hooks/test-hooks.sh"
    Then a mock MCP server is started during the test run that returns success JSON
    And the mock server is cleaned up after the test completes

  Scenario: Test script mocks claude CLI with a stub script
    Given the test script is installed at scripts/hooks/test-hooks.sh
    When the user runs "bash scripts/hooks/test-hooks.sh"
    Then a mock claude CLI is used during the test that returns sample extraction JSON
    And the mock claude CLI is cleaned up after the test completes

  Scenario: Test script cleans up counter files after tests
    Given the test script is installed at scripts/hooks/test-hooks.sh
    When the user runs "bash scripts/hooks/test-hooks.sh"
    Then no /tmp/distillery-prompt-count-* files from the test remain after completion

  Scenario: Full test suite passes end to end
    Given the test script is installed at scripts/hooks/test-hooks.sh
    And the dispatcher script is installed at scripts/hooks/distillery-hooks.sh
    When the user runs "bash scripts/hooks/test-hooks.sh"
    Then all reported tests show PASS
    And the command exits with code 0
