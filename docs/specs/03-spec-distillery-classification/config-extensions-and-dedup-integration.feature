# Source: docs/specs/03-spec-distillery-classification/03-spec-distillery-classification.md
# Pattern: State + CLI/Process
# Recommended test type: Integration

Feature: Config Extensions & Dedup Integration into /distill

  # Config Extensions scenarios

  Scenario: Config loads dedup thresholds from distillery.yaml
    Given a distillery.yaml file with classification section containing dedup_skip_threshold 0.90
    And dedup_merge_threshold 0.75
    And dedup_link_threshold 0.55
    And dedup_limit 8
    When the configuration is loaded
    Then ClassificationConfig.dedup_skip_threshold is 0.90
    And ClassificationConfig.dedup_merge_threshold is 0.75
    And ClassificationConfig.dedup_link_threshold is 0.55
    And ClassificationConfig.dedup_limit is 8

  Scenario: Config uses default dedup thresholds when not specified
    Given a distillery.yaml file with no dedup threshold settings
    When the configuration is loaded
    Then ClassificationConfig.dedup_skip_threshold is 0.95
    And ClassificationConfig.dedup_merge_threshold is 0.80
    And ClassificationConfig.dedup_link_threshold is 0.60
    And ClassificationConfig.dedup_limit is 5

  Scenario: Config validation rejects thresholds with incorrect ordering
    Given a distillery.yaml file with dedup_link_threshold 0.90 and dedup_merge_threshold 0.70
    When the configuration is loaded
    Then a validation error is raised indicating threshold ordering is invalid
    And the error message specifies that link_threshold must be less than or equal to merge_threshold

  Scenario: Config validation rejects skip threshold below merge threshold
    Given a distillery.yaml file with dedup_skip_threshold 0.70 and dedup_merge_threshold 0.80
    When the configuration is loaded
    Then a validation error is raised indicating threshold ordering is invalid

  Scenario: Config validation rejects thresholds outside 0-1 range
    Given a distillery.yaml file with dedup_skip_threshold 1.5
    When the configuration is loaded
    Then a validation error is raised indicating the threshold is out of range

  # distillery_check_dedup MCP tool scenarios

  Scenario: Check dedup tool returns skip for near-duplicate content
    Given the MCP server is running with a test store
    And the store contains an entry very similar to the input content (score >= 0.95)
    When the distillery_check_dedup tool is called with the input content
    Then the response action is "skip"
    And the response includes the similar entry details
    And the reasoning explains the content is a duplicate

  Scenario: Check dedup tool returns merge for overlapping content
    Given the MCP server is running with a test store
    And the store contains an entry moderately similar to the input (score between 0.80 and 0.95)
    When the distillery_check_dedup tool is called with the input content
    Then the response action is "merge"
    And the response includes the similar entry to merge with

  Scenario: Check dedup tool returns create for novel content
    Given the MCP server is running with a test store
    And the store contains no entries similar to the input (all scores below 0.60)
    When the distillery_check_dedup tool is called with the input content
    Then the response action is "create"

  # /distill dedup integration scenarios

  Scenario: Distill skill calls dedup check before storing content
    Given the /distill skill is invoked with new content
    And the MCP server is running
    When the skill processes the content
    Then the distillery_check_dedup tool is called before any store operation
    And the dedup result determines the subsequent action

  Scenario: Distill skill skips storing when dedup returns skip
    Given the /distill skill is invoked with content that is a near-duplicate
    And distillery_check_dedup returns action "skip" with the duplicate entry
    When the skill processes the dedup result
    Then the skill displays the duplicate entry to the user
    And the skill does not create a new entry in the store

  Scenario: Distill skill merges content when dedup returns merge
    Given the /distill skill is invoked with content that overlaps an existing entry
    And distillery_check_dedup returns action "merge" with the similar entry
    When the user confirms the merge
    Then the existing entry is updated with the new content appended
    And distillery_classify is called on the updated entry

  Scenario: Distill skill links related entries when dedup returns link
    Given the /distill skill is invoked with content related to existing entries
    And distillery_check_dedup returns action "link" with related entry IDs
    When the skill stores the new entry
    Then the new entry's metadata.related_entries contains the linked entry IDs
    And distillery_classify is called on the new entry

  Scenario: Distill skill stores normally and classifies when dedup returns create
    Given the /distill skill is invoked with novel content
    And distillery_check_dedup returns action "create"
    When the skill stores the new entry
    Then a new entry is created in the store
    And distillery_classify is called on the new entry
