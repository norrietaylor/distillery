# Source: docs/specs/06-spec-mvp-maturity/06-spec-mvp-maturity.md
# Pattern: State + API
# Recommended test type: Integration

Feature: Implicit Retrieval Feedback

  Scenario: Search call is logged with query and result details
    Given a knowledge base with 3 stored entries
    When the user calls distillery_search with query "python decorators"
    Then the search_log table contains a new row with query "python decorators"
    And the logged row includes the returned entry IDs and their similarity scores
    And the logged row has a timestamp within the last few seconds

  Scenario: Positive feedback is recorded when a search result is subsequently retrieved
    Given a knowledge base with an entry "E1" about "python decorators"
    And the user has called distillery_search with query "decorators" which returned entry "E1"
    When the user calls distillery_get for entry "E1" within 5 minutes of the search
    Then the feedback_log table contains a positive signal for that search and entry "E1"

  Scenario: Feedback is not recorded when retrieval occurs after the time window
    Given a knowledge base with an entry "E1" about "python decorators"
    And the user has called distillery_search with query "decorators" which returned entry "E1"
    When the user calls distillery_get for entry "E1" after 6 minutes have elapsed
    Then no feedback signal is recorded in the feedback_log table for that search

  Scenario: Feedback time window is configurable via distillery.yaml
    Given a distillery.yaml with classification.feedback_window_minutes set to 10
    And a knowledge base with an entry "E1"
    And the user has called distillery_search which returned entry "E1"
    When the user calls distillery_get for entry "E1" after 8 minutes have elapsed
    Then a positive feedback signal is recorded in the feedback_log table

  Scenario: Quality metrics tool returns aggregate feedback statistics
    Given a knowledge base that has been searched 20 times
    And 8 of those searches resulted in positive feedback signals
    When the user calls the distillery_quality MCP tool
    Then the response includes "total_searches" equal to 20
    And the response includes "positive_rate" equal to 0.4
    And the response includes an "average_result_count" value
    And the response includes a per-entry-type breakdown

  Scenario: Search and feedback tables are created during store initialization
    Given a fresh DuckDB database with no existing tables
    When the store is initialized via DuckDBStore.initialize()
    Then the search_log table exists and accepts inserts
    And the feedback_log table exists and accepts inserts
