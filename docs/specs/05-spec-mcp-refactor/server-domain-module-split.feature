# Source: docs/specs/05-spec-mcp-refactor/05-spec-mcp-refactor.md
# Pattern: API + CLI/Process
# Recommended test type: Integration

Feature: server.py Domain Module Split

  Scenario: All MCP tools remain functional after module split
    Given the MCP server is initialized with the refactored module structure
    And a test store is seeded with 3 entries
    When a client invokes the "distillery_status" tool
    Then the tool returns a successful response containing entry counts
    And no import errors are raised during tool execution

  Scenario: CRUD handlers respond correctly from their new module location
    Given the MCP server is running with handlers loaded from mcp/tools/crud.py
    And a test store is available
    When a client invokes the "distillery_store" tool with valid entry content
    Then the entry is persisted in the store
    And the response contains the new entry ID

  Scenario: Search handlers respond correctly from their new module location
    Given the MCP server is running with handlers loaded from mcp/tools/search.py
    And a test store is seeded with entries containing the term "machine learning"
    When a client invokes the "distillery_search" tool with query "machine learning"
    Then the response contains matching entries ranked by relevance

  Scenario: Classification handlers respond correctly from their new module location
    Given the MCP server is running with handlers loaded from mcp/tools/classify.py
    And a test store contains an unclassified entry
    When a client invokes the "distillery_review_queue" tool
    Then the response lists entries pending classification review

  Scenario: Quality handlers respond correctly from their new module location
    Given the MCP server is running with handlers loaded from mcp/tools/quality.py
    And a test store contains two near-duplicate entries
    When a client invokes the "distillery_check_dedup" tool with entry content
    Then the response indicates potential duplicates with similarity scores

  Scenario: Analytics handlers respond correctly from their new module location
    Given the MCP server is running with handlers loaded from mcp/tools/analytics.py
    And a test store is seeded with tagged entries
    When a client invokes the "distillery_tag_tree" tool
    Then the response contains a hierarchical tag structure

  Scenario: Feed handlers respond correctly from their new module location
    Given the MCP server is running with handlers loaded from mcp/tools/feeds.py
    And feed sources are configured
    When a client invokes the "distillery_watch" tool with a valid RSS URL
    Then the feed source is registered and the response confirms subscription

  Scenario: Shared utilities are accessible to all domain modules
    Given the MCP server is initialized with the refactored module structure
    When a handler in crud.py accesses the store via the shared context from _common.py
    And a handler in search.py accesses the embedding provider via the same shared context
    Then both handlers execute successfully without import errors

  Scenario: server.py contains only orchestration logic after the split
    Given the refactored MCP server codebase
    When the server starts up and registers all 22 tools
    Then all 22 tools are available in the tool registry
    And each tool dispatches to its corresponding domain module handler

  Scenario: Existing test suite passes without modification after the split
    Given the refactored MCP server with handlers in domain modules
    When the full unit test suite is executed with "pytest -m unit"
    Then all previously passing tests still pass
    And no test requires import path changes to find handlers
