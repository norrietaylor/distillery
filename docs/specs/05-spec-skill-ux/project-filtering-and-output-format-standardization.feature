# Source: docs/specs/05-spec-skill-ux/05-spec-skill-ux.md
# Pattern: CLI/Process
# Recommended test type: Integration

Feature: --project Filtering and Output Format Standardization

  Scenario: /classify --inbox filters pending entries by project
    Given the knowledge base contains 5 pending entries across projects "alpha" and "beta"
    When the user runs /classify --inbox --project alpha
    Then only entries belonging to project "alpha" are listed
    And entries from project "beta" are not displayed

  Scenario: /classify --review filters review queue entries by project
    Given the knowledge base contains entries in the review queue from projects "alpha" and "beta"
    When the user runs /classify --review --project beta
    Then only review queue entries belonging to project "beta" are listed
    And entries from project "alpha" are not displayed

  Scenario: /minutes --list filters meeting records by project
    Given the knowledge base contains meeting records for projects "alpha" and "beta"
    When the user runs /minutes --list --project alpha
    Then only meeting records belonging to project "alpha" are returned
    And the count matches the number of "alpha" meeting records

  Scenario: /radar scopes digest generation to a specific project
    Given the knowledge base contains feed entries from projects "alpha" and "beta"
    When the user runs /radar --project alpha
    Then the generated digest only includes entries from project "alpha"
    And entries from project "beta" are excluded from the digest

  Scenario: Write skill confirmation follows the standard format template
    Given the user stores a new entry using /distill with project "alpha" and tags "python, async"
    When the entry is successfully stored
    Then the confirmation output shows the entry type label on the first line
    And the confirmation includes the entry ID
    And the confirmation shows "Project: alpha | Author: <author>" on the second line
    And the confirmation shows a summary truncated to 200 characters
    And the confirmation shows "Tags: python, async" on the last line

  Scenario: All write skills produce identically formatted confirmations
    Given the user stores entries using /distill, /bookmark, /minutes, and /radar --store
    When each entry is successfully stored
    Then every confirmation follows the same format template
    And each confirmation includes entry_type, entry ID, project, author, summary, and tags

  Scenario: CONVENTIONS.md Entry Types table lists all valid entry types
    Given the CONVENTIONS.md file has been updated
    When the user reads the Entry Types section
    Then the table contains at least 5 entry types: session, bookmark, minutes, feed, digest
    And each row lists the producing skill and required metadata fields
