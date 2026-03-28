# Source: docs/specs/06-spec-mvp-maturity/06-spec-mvp-maturity.md
# Pattern: State + API
# Recommended test type: Integration

Feature: Stale Entry Detection

  Scenario: Entry accessed via get has its accessed_at timestamp updated
    Given a knowledge base with an entry "E1" that has not been accessed in 40 days
    When the user calls distillery_get for entry "E1"
    Then the accessed_at column for entry "E1" is updated to the current time
    And entry "E1" no longer appears in stale results for a 30-day threshold

  Scenario: Entry returned by search has its accessed_at timestamp updated
    Given a knowledge base with an entry "E1" that has not been accessed in 40 days
    When the user calls distillery_search and entry "E1" is in the results
    Then the accessed_at column for entry "E1" is updated to the current time

  Scenario: Stale tool returns entries not accessed within the threshold
    Given a knowledge base with 5 entries
    And 2 entries have not been accessed in 45 days
    And 3 entries were accessed within the last 10 days
    When the user calls the distillery_stale MCP tool with default parameters
    Then the response contains exactly 2 entries
    And each result includes id, content_preview, entry_type, author, project, last_accessed, and days_since_access

  Scenario: Stale tool content_preview is limited to 200 characters
    Given a knowledge base with a stale entry whose content is 500 characters long
    When the user calls the distillery_stale MCP tool
    Then the content_preview field in the result is at most 200 characters

  Scenario: Stale tool respects custom days parameter
    Given a knowledge base with entries last accessed 15, 25, and 35 days ago
    When the user calls the distillery_stale MCP tool with days set to 20
    Then the response contains 2 entries (those at 25 and 35 days)
    And the entry last accessed 15 days ago is not included

  Scenario: Stale tool filters by entry_type when specified
    Given a knowledge base with stale entries of types "decision" and "snippet"
    When the user calls the distillery_stale MCP tool with entry_type set to "decision"
    Then the response contains only entries of type "decision"

  Scenario: Entries without accessed_at fall back to updated_at for staleness
    Given a knowledge base with a legacy entry that has no accessed_at value
    And the entry was last updated 60 days ago
    When the user calls the distillery_stale MCP tool with days set to 30
    Then the entry appears in the stale results
    And its last_accessed field reflects the updated_at value

  Scenario: Staleness threshold default is configurable via distillery.yaml
    Given a distillery.yaml with classification.stale_days set to 15
    And a knowledge base with an entry last accessed 20 days ago
    When the user calls the distillery_stale MCP tool with no days parameter
    Then the entry appears in the stale results using the 15-day configured default
