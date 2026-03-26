Feature: MCP Server E2E Tests
  As a maintainer
  I want end-to-end tests exercising the full MCP server lifecycle
  So that protocol-level regressions are caught automatically

  Background:
    Given an MCP server created via create_server()
    And the server uses StubEmbeddingProvider (no API keys)
    And the server uses in-memory DuckDB

  Scenario: Store and retrieve round-trip
    When I call distillery_store with content "Test entry" and entry_type "inbox" and author "e2e"
    Then the response contains an entry_id
    When I call distillery_get with that entry_id
    Then the response contains content "Test entry"
    And the response contains entry_type "inbox"
    And the response contains author "e2e"

  Scenario: Store and search round-trip
    Given I store 3 entries with different content
    When I call distillery_search with query "test"
    Then the response contains a list of results
    And each result has an entry and a score field

  Scenario: Store and find_similar round-trip
    Given I store an entry with content "Similar content test"
    When I call distillery_find_similar with content "Similar content test"
    Then the response contains results with score fields
    And the response structure includes entry objects

  Scenario: Classify, review queue, and resolve round-trip
    Given I store an entry with content "Needs classification"
    When I call distillery_classify with that entry_id and confidence 0.3
    Then the entry status is "pending_review"
    When I call distillery_review_queue
    Then the response contains the classified entry
    And the entry shows content_preview and confidence
    When I call distillery_resolve_review with action "approve"
    Then the entry status is "active"
    And the metadata contains "reviewed_at"

  Scenario: Store and check_dedup round-trip
    Given I store an entry with content "Unique knowledge item"
    When I call distillery_check_dedup with content "Unique knowledge item"
    Then the response contains an action field
    And the response contains a highest_score field
    And the response contains a reasoning field

  Scenario: Store, update, and get round-trip
    Given I store an entry with content "Original content"
    When I call distillery_update with new content "Updated content"
    And I call distillery_get with that entry_id
    Then the content is "Updated content"
    And the version is 2

  Scenario: Store and list with pagination
    Given I store 5 entries with sequential content
    When I call distillery_list with limit 2 and offset 0
    Then 2 entries are returned
    And entries are ordered newest first
    When I call distillery_list with limit 2 and offset 2
    Then 2 different entries are returned

  Scenario: Status reflects stored entries
    When I call distillery_status on an empty database
    Then total_entries is 0
    When I store 3 entries of type "session"
    And I call distillery_status
    Then total_entries is 3
    And entries_by_type contains "session" with count 3

  Scenario: Error path — get non-existent entry
    When I call distillery_get with entry_id "non-existent-uuid"
    Then the response contains error true
    And the response contains code "NOT_FOUND"

  Scenario: Error path — store with missing required fields
    When I call distillery_store with only content "incomplete"
    Then the response contains error true
    And the response contains code "INVALID_INPUT"

  Scenario: All E2E tests use shared conftest fixtures
    Then tests/test_e2e_mcp.py imports from conftest
    And all tests are marked with @pytest.mark.integration

  Scenario: Each E2E test exercises multiple tools
    Then every test scenario calls at least 2 different MCP tools
    And responses are validated for full JSON structure
