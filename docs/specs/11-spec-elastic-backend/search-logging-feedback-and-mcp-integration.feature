# Source: docs/specs/11-spec-elastic-backend/11-spec-elastic-backend.md
# Unit: 3 — Search Logging, Feedback, and MCP Integration
# Pattern: Logging operations + MCP lifecycle + CLI health
# Recommended test type: Unit + Integration

Feature: Search Logging, Feedback, and MCP Integration

  # --- Search Logging ---

  Scenario: log_search indexes a search log document
    Given an initialized ElasticsearchStore with a mock ES client
    When log_search() is called with query "async patterns", result IDs ["id-1", "id-2"], scores [0.92, 0.85], and session_id "sess-abc"
    Then a document is indexed in "distillery_search_log"
    And the document contains the query "async patterns"
    And the document contains result_ids ["id-1", "id-2"]
    And the document contains scores [0.92, 0.85]
    And the document contains session_id "sess-abc"
    And the document contains a timestamp

  Scenario: log_search handles empty result set
    Given an initialized ElasticsearchStore with a mock ES client
    When log_search() is called with query "obscure topic", result IDs [], scores [], and session_id "sess-xyz"
    Then a document is indexed in "distillery_search_log"
    And the document contains empty result_ids and scores

  # --- Feedback Logging ---

  Scenario: log_feedback indexes a feedback log document
    Given an initialized ElasticsearchStore with a mock ES client
    When log_feedback() is called with search_id "search-1", entry_id "entry-1", and signal "relevant"
    Then a document is indexed in "distillery_feedback_log"
    And the document contains search_id "search-1"
    And the document contains entry_id "entry-1"
    And the document contains signal "relevant"
    And the document contains a timestamp

  Scenario: log_feedback accepts different signal types
    Given an initialized ElasticsearchStore with a mock ES client
    When log_feedback() is called with signal "not_relevant"
    Then a document is indexed in "distillery_feedback_log" with signal "not_relevant"
    When log_feedback() is called with signal "partial"
    Then a document is indexed in "distillery_feedback_log" with signal "partial"

  # --- MCP Server Integration ---

  Scenario: MCP server instantiates ElasticsearchStore when config says elasticsearch
    Given a distillery.yaml with backend "elasticsearch" and valid connection settings
    And the required environment variables are set
    When the MCP server lifespan() starts
    Then an ElasticsearchStore instance is created
    And it is passed the async ES client, embedding provider, and config
    And the store is used for all MCP tool operations

  Scenario: MCP server falls back to DuckDB when config says duckdb
    Given a distillery.yaml with backend "duckdb"
    When the MCP server lifespan() starts
    Then a DuckDB store instance is created
    And no ElasticsearchStore is instantiated

  Scenario: MCP server closes the async ES client on shutdown
    Given a running MCP server with an ElasticsearchStore backend
    When the MCP server lifespan() shuts down
    Then the AsyncElasticsearch client close() method is called
    And no connection resources are leaked

  # --- distillery_status Tool ---

  Scenario: distillery_status reports Elasticsearch-specific stats
    Given a running MCP server with an ElasticsearchStore backend
    And the indices contain documents
    When the distillery_status tool is called
    Then the response includes backend type "elasticsearch"
    And the response includes index document counts
    And the response includes index sizes
    And the response includes the embedding model name

  # --- distillery health CLI ---

  Scenario: distillery health verifies ES connectivity
    Given a distillery.yaml with backend "elasticsearch"
    And the Elasticsearch cluster is reachable
    When "distillery health" CLI command is run
    Then the command calls client.info() on the ES client
    And the output reports connection status as healthy
    And the output includes cluster health information

  Scenario: distillery health reports failure when ES is unreachable
    Given a distillery.yaml with backend "elasticsearch"
    And the Elasticsearch cluster is not reachable
    When "distillery health" CLI command is run
    Then the output reports connection status as unhealthy
    And an appropriate error message is displayed

  # --- Error Handling ---

  Scenario: ES NotFoundError maps to KeyError on get
    Given an initialized ElasticsearchStore with a mock ES client
    And the ES client raises NotFoundError for id "missing-1"
    When get() is called with id "missing-1"
    Then the result is None

  Scenario: ES ConflictError maps to ValueError on update
    Given an initialized ElasticsearchStore with a mock ES client
    And the ES client raises ConflictError for id "conflict-1"
    When update() is called with id "conflict-1"
    Then a ValueError is raised with an appropriate message

  Scenario: ES ConnectionError is handled gracefully
    Given an initialized ElasticsearchStore with a mock ES client
    And the ES client raises ConnectionError
    When any store operation is attempted
    Then a connection error is raised with a descriptive message
    And the error does not expose internal ES client details
