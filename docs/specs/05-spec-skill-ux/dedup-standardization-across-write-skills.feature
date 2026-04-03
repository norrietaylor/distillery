# Source: docs/specs/05-spec-skill-ux/05-spec-skill-ux.md
# Pattern: CLI/Process + State
# Recommended test type: Integration

Feature: Dedup Standardization Across Write Skills

  Scenario: /minutes checks for duplicate content before storing a new meeting record
    Given the knowledge base contains a meeting record with content "Q1 planning discussion"
    When the user runs /minutes to store new notes with content similar to "Q1 planning discussion"
    Then the skill presents the dedup outcome showing a similarity match
    And the user is prompted with the 4-outcome options: create, skip, merge, or link
    And no new entry is stored until the user selects an outcome

  Scenario: /minutes with matching meeting_id suggests --update instead of creating a new entry
    Given the knowledge base contains a meeting record with meeting_id "mtg-2026-04-01"
    When the user runs /minutes to store new notes with meeting_id "mtg-2026-04-01"
    Then the skill reports the entry as a duplicate based on meeting_id
    And the skill suggests using --update to modify the existing entry
    And no new entry is created

  Scenario: /minutes --update bypasses dedup checking
    Given the knowledge base contains a meeting record with meeting_id "mtg-2026-04-01"
    When the user runs /minutes --update with meeting_id "mtg-2026-04-01" and updated content
    Then the existing entry is modified with the new content
    And no dedup check is performed

  Scenario: /radar checks for duplicate content before storing a digest
    Given the knowledge base contains a stored digest with content "Weekly security digest"
    And the user runs /radar with --store flag
    When the generated digest content is similar to "Weekly security digest"
    Then the skill presents the dedup outcome showing a similarity match
    And the user is prompted with the 4-outcome options: create, skip, merge, or link

  Scenario: All 4 dedup outcomes are handled identically across write skills
    Given the knowledge base contains an entry with content "existing knowledge"
    When a write skill calls distillery_check_dedup with similar content
    And the dedup result is "merge"
    Then the skill merges the new content into the existing entry
    And the merged entry retains the original entry ID
    And a confirmation message is displayed following the standard format

  Scenario: CONVENTIONS.md documents the canonical dedup flow
    Given the CONVENTIONS.md file has been updated
    When the user reads the Canonical Dedup Flow section
    Then the section describes the distillery_check_dedup call pattern
    And the section lists all 4 outcomes with their user-facing prompts
    And the section specifies that all write skills must follow this flow
