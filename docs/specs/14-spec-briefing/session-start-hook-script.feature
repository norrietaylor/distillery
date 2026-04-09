# Source: docs/specs/14-spec-briefing/14-spec-briefing.md
# Pattern: CLI/Process (bash hook script with HTTP calls)
# Recommended test type: Integration

Feature: SessionStart hook script

  Scenario: Hook reads session JSON from stdin and derives project name
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And a git repository exists at "/tmp/test-project"
    When the user pipes '{"hook_event_name":"SessionStart","session_id":"abc123","cwd":"/tmp/test-project"}' to the hook script
    Then the output references the project name "test-project"

  Scenario: Hook calls MCP server and produces condensed briefing output
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And the MCP HTTP server is running at the configured DISTILLERY_MCP_URL
    And the knowledge base contains 5 recent entries for the derived project
    When the user pipes a valid SessionStart JSON to the hook script
    Then stdout contains a single-line header with project name, entry count, and summary counts
    And the total output is at most 20 lines

  Scenario: Hook respects DISTILLERY_MCP_URL environment variable
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And DISTILLERY_MCP_URL is set to "http://custom-host:9000/mcp"
    When the user pipes a valid SessionStart JSON to the hook script
    Then the hook sends its HTTP request to "http://custom-host:9000/mcp"

  Scenario: Hook respects DISTILLERY_BRIEFING_LIMIT environment variable
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And DISTILLERY_BRIEFING_LIMIT is set to "3"
    And the MCP HTTP server is running with 10 entries available
    When the user pipes a valid SessionStart JSON to the hook script
    Then the output lists at most 3 recent entries

  Scenario: Hook exits silently when MCP server is unreachable
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And DISTILLERY_MCP_URL points to a non-responsive host
    When the user pipes a valid SessionStart JSON to the hook script
    Then the hook produces no output on stdout
    And the hook exits with code 0
    And the hook completes within 3 seconds

  Scenario: Hook uses 2-second timeout for health check
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And DISTILLERY_MCP_URL points to a host that delays responses by 5 seconds
    When the user pipes a valid SessionStart JSON to the hook script
    Then the hook produces no output on stdout
    And the hook exits with code 0

  Scenario: Hook derives project from git root basename
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And the cwd "/tmp/repos/my-project/src/lib" is inside a git repository rooted at "/tmp/repos/my-project"
    When the user pipes '{"hook_event_name":"SessionStart","session_id":"s1","cwd":"/tmp/repos/my-project/src/lib"}' to the hook script
    Then the output references the project name "my-project"

  Scenario: Hook falls back to cwd basename when not in a git repository
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And the cwd "/tmp/standalone-dir" is not inside any git repository
    When the user pipes '{"hook_event_name":"SessionStart","session_id":"s1","cwd":"/tmp/standalone-dir"}' to the hook script
    Then the output references the project name "standalone-dir"

  Scenario: Hook includes bearer token when DISTILLERY_BEARER_TOKEN is set
    Given the hook script is executable at "scripts/hooks/session-start-briefing.sh"
    And DISTILLERY_BEARER_TOKEN is set to "secret-token-123"
    And the MCP HTTP server is running with authentication required
    When the user pipes a valid SessionStart JSON to the hook script
    Then the HTTP request includes an "Authorization: Bearer secret-token-123" header
    And the hook receives a successful response from the MCP server
