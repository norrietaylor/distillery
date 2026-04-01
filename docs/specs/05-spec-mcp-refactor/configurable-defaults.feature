# Source: docs/specs/05-spec-mcp-refactor/05-spec-mcp-refactor.md
# Pattern: State + API
# Recommended test type: Integration

Feature: Configurable Defaults

  Scenario: Custom dedup_threshold from config affects dedup checking
    Given a distillery.yaml file with defaults.dedup_threshold set to 0.85
    And the MCP server is started with that configuration
    And two entries exist with 0.88 similarity score
    When a client invokes the "distillery_check_dedup" tool for one of those entries
    Then the response identifies the entries as potential duplicates
    And the similarity threshold used is 0.85

  Scenario: Custom dedup_limit from config limits returned duplicates
    Given a distillery.yaml file with defaults.dedup_limit set to 5
    And the MCP server is started with that configuration
    And 10 entries exist that are similar to a target entry
    When a client invokes the "distillery_check_dedup" tool for the target entry
    Then the response contains at most 5 duplicate candidates

  Scenario: Custom stale_days from config affects stale entry detection
    Given a distillery.yaml file with defaults.stale_days set to 14
    And the MCP server is started with that configuration
    And an entry was last modified 15 days ago
    When a client invokes the "distillery_stale" tool
    Then the response lists the 15-day-old entry as stale

  Scenario: Absent defaults section uses built-in fallback values
    Given a distillery.yaml file with no "defaults" section
    When the Config object is loaded from that file
    Then defaults.dedup_threshold is 0.92
    And defaults.dedup_limit is 3
    And defaults.stale_days is 30

  Scenario: Partial defaults section fills missing fields with fallbacks
    Given a distillery.yaml file with only defaults.stale_days set to 7
    When the Config object is loaded from that file
    Then defaults.dedup_threshold is 0.92
    And defaults.dedup_limit is 3
    And defaults.stale_days is 7

  Scenario: DefaultsConfig validates dedup_threshold range
    Given a distillery.yaml file with defaults.dedup_threshold set to 1.5
    When the Config object is loaded from that file
    Then a configuration error is raised indicating dedup_threshold must be between 0 and 1

  Scenario: Handlers read defaults from config object not module constants
    Given the MCP server is started with a config containing defaults.dedup_threshold of 0.80
    When a client invokes "distillery_check_dedup" for an entry with 0.82 similarity
    Then the entry is flagged as a duplicate using the configured 0.80 threshold
    And the handler does not reference any _DEFAULT_DEDUP_THRESHOLD constant
