# Source: docs/specs/03-spec-distillery-classification/03-spec-distillery-classification.md
# Pattern: CLI/Process + Error handling
# Recommended test type: Integration

Feature: /classify Skill - Manual Classification & Review Queue

  # Classify by ID mode scenarios

  Scenario: Classify a specific entry by ID shows classification result
    Given the MCP server is running and accessible
    And an unclassified entry exists with id "entry-001"
    When the user invokes "/classify entry-001"
    Then the output displays the assigned entry_type
    And the output displays the confidence as a percentage
    And the output displays the classification reasoning
    And the output displays the suggested tags

  Scenario: Classify entry below threshold notes review queue placement
    Given the MCP server is running and accessible
    And an entry exists with id "entry-002"
    And the classification engine returns confidence below the threshold
    When the user invokes "/classify entry-002"
    Then the output indicates the entry has been sent to the review queue
    And the output displays the low confidence percentage

  Scenario: Reclassify an already-classified entry shows comparison
    Given the MCP server is running and accessible
    And an entry exists with id "entry-003" previously classified as "bookmark" with confidence 72%
    When the user invokes "/classify entry-003"
    Then the output shows the previous classification "bookmark" at 72%
    And the output shows the new classification type and confidence
    And the entry is updated with the new classification

  # Batch inbox mode scenarios

  Scenario: Batch classify all inbox entries displays summary table
    Given the MCP server is running and accessible
    And 5 entries exist with entry_type "inbox"
    When the user invokes "/classify --inbox"
    Then the output displays a markdown table with columns for entry ID, content preview, assigned type, and confidence
    And the table contains 5 rows
    And the output reports totals for classified, sent to review, and already classified

  Scenario: Batch classify with no inbox entries reports none found
    Given the MCP server is running and accessible
    And no entries exist with entry_type "inbox"
    When the user invokes "/classify --inbox"
    Then the output indicates no inbox entries were found to classify

  # Review queue mode scenarios

  Scenario: Review queue displays pending entries for triage
    Given the MCP server is running and accessible
    And 3 entries exist with status "pending_review"
    When the user invokes "/classify --review"
    Then the output displays each pending entry with ID, content preview, current classification, confidence, and reasoning
    And the user is prompted to approve, reclassify, or archive each entry

  Scenario: Approve an entry in review queue sets it to active
    Given the MCP server is running and accessible
    And the review queue is displayed with entry "entry-010"
    When the user selects "approve" for entry "entry-010"
    Then the entry's status is changed to "active"
    And the output confirms the entry was approved

  Scenario: Reclassify an entry in review queue updates its type
    Given the MCP server is running and accessible
    And the review queue is displayed with entry "entry-011" classified as "inbox"
    When the user selects "reclassify" for entry "entry-011" and chooses type "session"
    Then the entry's entry_type is changed to "session"
    And the entry's status is changed to "active"
    And the output confirms the reclassification

  Scenario: Archive an entry in review queue removes it
    Given the MCP server is running and accessible
    And the review queue is displayed with entry "entry-012"
    When the user selects "archive" for entry "entry-012"
    Then the entry's status is changed to "archived"
    And the output confirms the entry was archived

  Scenario: Review queue displays summary after processing all entries
    Given the MCP server is running and accessible
    And the user has triaged all entries in the review queue
    When all entries have been processed
    Then the output displays a summary with counts for approved, reclassified, and archived entries

  # Display and confidence formatting scenarios

  Scenario: Confidence display uses percentage with level indicator
    Given the MCP server is running and accessible
    And an entry is classified with confidence 0.85
    When the classification result is displayed
    Then the confidence shows "85%" with level "high"

  Scenario: Medium confidence is labeled correctly
    Given the MCP server is running and accessible
    And an entry is classified with confidence 0.65
    When the classification result is displayed
    Then the confidence shows "65%" with level "medium"

  Scenario: Low confidence is labeled correctly
    Given the MCP server is running and accessible
    And an entry is classified with confidence 0.45
    When the classification result is displayed
    Then the confidence shows "45%" with level "low"

  # Error handling scenarios

  Scenario: Skill displays help when invoked with no arguments
    Given the MCP server is running and accessible
    When the user invokes "/classify" with no arguments
    Then the output displays help text showing the three available modes
    And the help includes examples for classify by ID, batch inbox, and review queue

  Scenario: Skill reports error for nonexistent entry ID
    Given the MCP server is running and accessible
    And no entry exists with id "entry-999"
    When the user invokes "/classify entry-999"
    Then the output displays an error message indicating the entry was not found

  Scenario: Skill checks MCP server availability on startup
    Given the MCP server is not running
    When the user invokes "/classify --inbox"
    Then the output displays an error indicating the MCP server is unavailable
