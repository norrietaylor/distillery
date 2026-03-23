# Source: docs/specs/02-spec-distillery-skills/02-spec-distillery-skills.md
# Pattern: CLI/Process + Error Handling
# Recommended test type: Integration

Feature: /distill — Session Knowledge Capture

  Scenario: Distill captures session knowledge and returns stored entry ID
    Given the Distillery MCP server is running and connected
    And at least one decision or insight exists in the current session context
    When the user invokes "/distill"
    Then the skill calls distillery_store with entry_type "session"
    And the stored entry ID is displayed to the user in a confirmation message
    And the stored content contains a distilled summary of decisions and insights

  Scenario: Distill with explicit content stores the provided text
    Given the Distillery MCP server is running and connected
    When the user invokes "/distill 'We decided to use DuckDB for local storage'"
    Then the skill calls distillery_store with content containing "We decided to use DuckDB for local storage"
    And the stored entry ID is displayed to the user

  Scenario: Duplicate detection warns before storing similar content
    Given the Distillery MCP server is running and connected
    And an entry about "DuckDB storage decision" already exists in the knowledge base
    When the user invokes "/distill" with content similar to the existing entry
    Then the skill calls distillery_find_similar and receives a match with score >= 0.8
    And the similar entry content is displayed to the user
    And the user is asked to choose: store anyway, merge with existing, or skip

  Scenario: User chooses to skip when duplicate is detected
    Given the duplicate detection has found a similar entry
    And the user is presented with the store/merge/skip choice
    When the user selects "skip"
    Then no new entry is stored
    And the skill confirms the action was skipped

  Scenario: Distill asks for clarification when session context is unclear
    Given the Distillery MCP server is running and connected
    And the current session has no clear decisions or insights
    When the user invokes "/distill"
    Then the skill asks the user what to capture before proceeding

  Scenario: Distill displays setup message when MCP server is unavailable
    Given the Distillery MCP server is not configured or not running
    When the user invokes "/distill"
    Then an error message is displayed indicating the MCP server is unavailable
    And a reference to "docs/mcp-setup.md" is included in the message
