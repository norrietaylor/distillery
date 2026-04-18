# Source: docs/specs/16-spec-api-consolidation/16-spec-api-consolidation.md
# Pattern: API
# Recommended test type: Integration

Feature: Extend list Tool with stale_days, group_by, and output Parameters

  Scenario: stale_days filters to entries not accessed in N+ days
    Given the store contains 5 entries where 2 have not been accessed in 30+ days
    When the list tool is called with stale_days=30
    Then the response contains exactly 2 entries
    And each returned entry has a last access timestamp older than 30 days ago

  Scenario: stale_days uses COALESCE of accessed_at and updated_at
    Given the store contains an entry with no accessed_at and updated_at 60 days ago
    And the store contains an entry with accessed_at 10 days ago
    When the list tool is called with stale_days=30
    Then only the entry with no accessed_at is returned
    And the entry with recent accessed_at is excluded

  Scenario: stale_days composes with existing filters
    Given the store contains 3 stale entries of type "session" and 2 stale entries of type "bookmark"
    When the list tool is called with stale_days=30 and entry_type="session"
    Then the response contains exactly 3 entries
    And all returned entries have entry_type "session"

  Scenario: group_by entry_type returns grouped counts
    Given the store contains 5 entries of type "session" and 3 entries of type "bookmark"
    When the list tool is called with group_by="entry_type"
    Then the response format is {"groups": [...], "total_entries": 8, "total_groups": 2}
    And the groups contain {"value": "session", "count": 5} and {"value": "bookmark", "count": 3}

  Scenario: group_by results are ordered by count descending
    Given the store contains entries with 10 of type "session", 5 of type "bookmark", and 2 of type "note"
    When the list tool is called with group_by="entry_type"
    Then the first group has value "session" with count 10
    And the second group has value "bookmark" with count 5
    And the third group has value "note" with count 2

  Scenario: group_by tags with tag_prefix replicates tag_tree functionality
    Given the store contains entries tagged "topic/python", "topic/rust", and "project/distillery"
    When the list tool is called with group_by="tags" and tag_prefix="topic/"
    Then the response contains groups for "topic/python" and "topic/rust"
    And the "project/distillery" tag is not included in the results

  Scenario: output stats returns aggregate metrics
    Given the store contains entries of various types and statuses
    When the list tool is called with output="stats"
    Then the response contains entries_by_type with counts per entry type
    And the response contains entries_by_status with counts per status
    And the response contains total_entries as an integer
    And the response contains storage_bytes as an integer

  Scenario: group_by and output stats are mutually exclusive
    Given the store contains entries
    When the list tool is called with group_by="entry_type" and output="stats"
    Then a validation error is returned
    And the error message indicates group_by and output="stats" cannot be combined

  Scenario: default list results are ordered by created_at descending
    Given the store contains 3 entries created at different times
    When the list tool is called with no special parameters
    Then the entries are returned in descending order of created_at
