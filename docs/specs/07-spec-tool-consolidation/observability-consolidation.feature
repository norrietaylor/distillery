# Source: docs/specs/07-spec-tool-consolidation/07-spec-tool-consolidation.md
# Pattern: API + CLI/Process
# Recommended test type: Integration

Feature: Observability Consolidation -- metrics absorbs status and quality

  Scenario: Summary scope returns entry counts and database info
    Given the MCP server is running with entries stored in the database
    When a caller invokes distillery_metrics with scope "summary"
    Then the response contains entry counts grouped by type and status
    And the response contains database size information
    And the response contains the embedding model identifier

  Scenario: Full scope returns the complete metrics payload
    Given the MCP server is running with entries and search history
    When a caller invokes distillery_metrics with scope "full"
    Then the response contains entry counts, activity, search, quality, staleness, and storage sections
    And no section from the previous metrics output is missing

  Scenario: Full scope is the default when no scope is provided
    Given the MCP server is running
    When a caller invokes distillery_metrics with no scope parameter
    Then the response is identical in structure to a call with scope "full"

  Scenario: Search quality scope returns search feedback data
    Given the MCP server is running with recorded search feedback
    When a caller invokes distillery_metrics with scope "search_quality"
    Then the response contains search totals and feedback rates
    And the response contains a quality breakdown section

  Scenario: The status tool is no longer registered
    Given the MCP server is running
    When a caller attempts to invoke distillery_status
    Then the server returns a tool-not-found error
    And distillery_status does not appear in the tool listing

  Scenario: The quality tool is no longer registered
    Given the MCP server is running
    When a caller attempts to invoke distillery_quality
    Then the server returns a tool-not-found error
    And distillery_quality does not appear in the tool listing

  Scenario: Skills use metrics with summary scope for health checks
    Given a skill invokes the MCP server for a health check
    When the skill calls distillery_metrics with scope "summary"
    Then a successful response is returned with entry counts
    And the skill can determine the server is healthy from the response
