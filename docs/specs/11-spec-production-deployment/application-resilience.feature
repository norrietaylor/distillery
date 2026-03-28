# Source: docs/specs/11-spec-production-deployment/11-spec-production-deployment.md
# Pattern: Error handling + API + State
# Recommended test type: Integration

Feature: Application Resilience

  Scenario: Store initializes when VSS extension is unavailable
    Given a DuckDB store configured with an in-memory database
    And the VSS extension installation is forced to fail
    When the store is initialized
    Then the store completes initialization without raising an error
    And the store reports vss_available as false
    And a warning log message contains "VSS" and the failure reason

  Scenario: HNSW index creation is skipped when VSS is unavailable
    Given a DuckDB store that has initialized with vss_available as false
    When index creation is attempted
    Then no HNSW index is created
    And a warning log message contains "HNSW index not created, falling back to brute-force search"

  Scenario: Semantic search returns results without HNSW index
    Given a DuckDB store initialized without VSS
    And 3 entries have been stored with embeddings
    When a semantic search is performed with a query embedding
    Then the search returns results ranked by cosine similarity
    And the number of results matches the requested limit

  Scenario: Find similar returns results without HNSW index
    Given a DuckDB store initialized without VSS
    And 3 entries have been stored with embeddings
    When find_similar is called for one of the stored entries
    Then similar entries are returned ranked by cosine similarity score

  Scenario: Store retries initialization on transient connection failure
    Given a DuckDB store configured with an in-memory database
    And the database connection fails with a ConnectionException on the first attempt
    And the database connection succeeds on the second attempt
    When the store is initialized
    Then the store completes initialization successfully
    And the initialization was attempted 2 times

  Scenario: Store retries up to 3 times with exponential backoff
    Given a DuckDB store configured with an in-memory database
    And the database connection fails with IOException on all attempts
    When the store is initialized
    Then the initialization raises an error after 3 retry attempts
    And the retry delays follow exponential backoff pattern of 1s, 2s, 4s

  Scenario: Health endpoint returns server status with VSS available
    Given the MCP server is running with HTTP transport
    And VSS is loaded successfully
    When an HTTP GET request is sent to /health
    Then the response status is 200
    And the response body contains "status": "ok"
    And the response body contains "vss_available": true
    And the response body contains "store_initialized": true

  Scenario: Health endpoint reports VSS unavailable
    Given the MCP server is running with HTTP transport
    And VSS extension failed to load
    When an HTTP GET request is sent to /health
    Then the response status is 200
    And the response body contains "status": "ok"
    And the response body contains "vss_available": false

  Scenario: Health endpoint does not require authentication
    Given the MCP server is running with HTTP transport and GitHub OAuth enabled
    When an unauthenticated HTTP GET request is sent to /health
    Then the response status is 200
    And the response body contains "status": "ok"
