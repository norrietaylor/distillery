# Source: docs/specs/06-spec-mvp-maturity/06-spec-mvp-maturity.md
# Pattern: API + State
# Recommended test type: Integration

Feature: Usage Metrics Dashboard

  Scenario: Metrics tool returns all required top-level categories
    Given a knowledge base with stored entries and search history
    When the user calls the distillery_metrics MCP tool
    Then the response contains the keys "entries", "activity", "search", "quality", "staleness", and "storage"

  Scenario: Entry metrics include counts by type, status, and source
    Given a knowledge base with 10 entries across 3 types and 2 statuses
    When the user calls the distillery_metrics MCP tool
    Then the "entries" section includes the total count of 10
    And the "entries" section includes a breakdown by entry type
    And the "entries" section includes a breakdown by status
    And the "entries" section includes a breakdown by source

  Scenario: Activity metrics reflect entries created and updated in time windows
    Given a knowledge base with entries created 5, 20, and 60 days ago
    And entries updated 3 and 45 days ago
    When the user calls the distillery_metrics MCP tool
    Then the "activity" section reports entries created in last 7, 30, and 90 days
    And the "activity" section reports entries updated in last 7, 30, and 90 days

  Scenario: Search metrics aggregate data from search_log
    Given a search_log with 50 searches, 15 of which occurred in the last 7 days
    When the user calls the distillery_metrics MCP tool
    Then the "search" section includes total_searches of 50
    And the "search" section includes searches in last 7 and 30 days
    And the "search" section includes average results per search

  Scenario: Quality metrics reflect feedback signal data
    Given a feedback_log with 30 total signals, 18 of which are positive
    When the user calls the distillery_metrics MCP tool
    Then the "quality" section includes a positive feedback rate of 0.6
    And the "quality" section includes total feedback signals of 30

  Scenario: Staleness metrics count entries beyond the access threshold
    Given a knowledge base where 7 entries have not been accessed in over 30 days
    And 3 of those are of type "decision" and 4 are of type "snippet"
    When the user calls the distillery_metrics MCP tool
    Then the "staleness" section reports 7 stale entries
    And the "staleness" section includes a count by entry type

  Scenario: Storage metrics report database file size and embedding info
    Given a knowledge base backed by a DuckDB file on disk
    When the user calls the distillery_metrics MCP tool
    Then the "storage" section includes the database file size
    And the "storage" section includes the embedding model name
    And the "storage" section includes the embedding dimensions

  Scenario: Metrics tool returns zeros for empty database
    Given a freshly initialized knowledge base with no entries and no search history
    When the user calls the distillery_metrics MCP tool
    Then all count fields in the response are 0
    And the response structure includes all top-level keys

  Scenario: Period_days parameter adjusts the recent activity window
    Given a knowledge base with entries and searches spanning 90 days
    When the user calls the distillery_metrics MCP tool with period_days set to 7
    Then the activity and search metrics reflect only the last 7 days

  Scenario: Metrics tool does not modify any data
    Given a knowledge base with 5 entries and a search_log with 10 rows
    When the user calls the distillery_metrics MCP tool
    Then the entry count remains 5
    And the search_log row count remains 10
    And no accessed_at timestamps are modified
