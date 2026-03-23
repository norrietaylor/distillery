# Source: docs/specs/02-spec-distillery-skills/02-spec-distillery-skills.md
# Pattern: CLI/Process + Error Handling
# Recommended test type: Integration

Feature: /pour — Multi-Entry Knowledge Synthesis

  Scenario: Pour synthesizes multiple entries into a cohesive narrative with citations
    Given the Distillery MCP server is running and connected
    And at least 3 entries about "authentication architecture" exist in the knowledge base
    When the user invokes "/pour how does our auth system work?"
    Then the skill calls distillery_search with limit 20
    And a cohesive narrative synthesizing information from multiple entries is displayed
    And inline citations using "[Entry <short-id>]" notation appear in the narrative
    And a source list follows the synthesis showing short ID, entry type, author, date, and first line of content for each cited entry

  Scenario: Pour flags contradictions between entries
    Given the Distillery MCP server is running and connected
    And one entry states "We use JWT tokens" and another states "We use session cookies"
    When the user invokes "/pour authentication strategy"
    Then the synthesis identifies and flags the contradiction between the two entries
    And both conflicting positions are presented with their source citations

  Scenario: Pour identifies knowledge gaps
    Given the Distillery MCP server is running and connected
    And entries about "auth" cover login but not password reset or token refresh
    When the user invokes "/pour authentication system overview"
    Then the synthesis includes a section identifying knowledge gaps
    And the gaps mention areas where entries are thin or missing

  Scenario: Pour falls back to recall behavior when fewer than 2 entries are found
    Given the Distillery MCP server is running and connected
    And only 1 entry matches the query "obscure microservice"
    When the user invokes "/pour obscure microservice"
    Then results are displayed directly in recall format instead of a synthesis
    And the single entry shows similarity score, type badge, content, and provenance

  Scenario: Pour scopes synthesis to a specific project
    Given the Distillery MCP server is running and connected
    And entries exist for projects "alpha" and "beta"
    When the user invokes "/pour deployment strategy --project alpha"
    Then only entries from project "alpha" are included in the synthesis

  Scenario: Pour without arguments prompts the user for a topic
    Given the Distillery MCP server is running and connected
    When the user invokes "/pour" with no arguments
    Then the skill asks the user what topic to synthesize
