# Source: docs/specs/16-spec-api-consolidation/16-spec-api-consolidation.md
# Pattern: API
# Recommended test type: Integration

Feature: Remove Absorbed Tools and Move Poll/Rescore to Webhooks

  Scenario: MCP server exposes exactly 16 tools after consolidation
    Given the MCP server is started
    When a client calls list_tools
    Then exactly 16 tools are returned
    And no tool named "distillery_stale" is in the list
    And no tool named "distillery_aggregate" is in the list
    And no tool named "distillery_tag_tree" is in the list
    And no tool named "distillery_metrics" is in the list
    And no tool named "distillery_interests" is in the list
    And no tool named "distillery_type_schemas" is in the list
    And no tool named "distillery_poll" is in the list
    And no tool named "distillery_rescore" is in the list

  Scenario: Entry type schemas are served as an MCP resource
    Given the MCP server is started
    When a client requests the resource "distillery://schemas/entry-types"
    Then a JSON document is returned containing the entry type schema definitions

  Scenario: Poll webhook endpoint accepts requests and returns results
    Given the MCP server is running in HTTP mode with a valid bearer token
    And feed sources are configured in the store
    When a POST request is sent to /hooks/poll with the bearer token
    Then the response status is 200
    And the response body contains aggregate poll results (sources_polled, items_fetched, items_stored, errors)

  Scenario: Poll webhook accepts optional source_url parameter
    Given the MCP server is running in HTTP mode with a valid bearer token
    And a feed source "https://example.com/feed" is configured
    When a POST request is sent to /hooks/poll?source_url=https://example.com/feed with the bearer token
    Then only the specified source is polled
    And the response contains results for that single source

  Scenario: Rescore webhook endpoint accepts requests and returns statistics
    Given the MCP server is running in HTTP mode with a valid bearer token
    And the store contains entries with embeddings
    When a POST request is sent to /hooks/rescore with the bearer token
    Then the response status is 200
    And the response body contains rescore statistics

  Scenario: Rescore webhook accepts optional limit parameter
    Given the MCP server is running in HTTP mode with a valid bearer token
    And the store contains 100 entries with embeddings
    When a POST request is sent to /hooks/rescore?limit=50 with the bearer token
    Then at most 50 entries are rescored
    And the response indicates how many entries were processed

  Scenario: Webhook endpoints reject unauthenticated requests
    Given the MCP server is running in HTTP mode
    When a POST request is sent to /hooks/poll without a bearer token
    Then the response status is 401
    And no poll operation is executed
