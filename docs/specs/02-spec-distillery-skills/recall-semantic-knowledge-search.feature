# Source: docs/specs/02-spec-distillery-skills/02-spec-distillery-skills.md
# Pattern: CLI/Process + Error Handling
# Recommended test type: Integration

Feature: /recall — Semantic Knowledge Search

  Scenario: Recall returns formatted results for a natural language query
    Given the Distillery MCP server is running and connected
    And entries about "distributed caching" exist in the knowledge base
    When the user invokes "/recall distributed caching strategies"
    Then the skill calls distillery_search with query "distributed caching strategies" and limit 10
    And results are displayed with similarity score as percentage
    And each result shows an entry type badge, full content, and provenance line
    And the provenance line contains entry ID, author, project, and created_at timestamp

  Scenario: Recall applies filter flags to narrow results
    Given the Distillery MCP server is running and connected
    And entries of type "session" and "bookmark" exist in the knowledge base
    When the user invokes "/recall caching --type session --author Alice --limit 5"
    Then the skill calls distillery_search with type filter "session", author filter "Alice", and limit 5
    And only entries matching the filters are displayed

  Scenario: Recall reports no results and suggests broadening the query
    Given the Distillery MCP server is running and connected
    And no entries match the query "quantum teleportation protocols"
    When the user invokes "/recall quantum teleportation protocols"
    Then a message is displayed indicating no results were found
    And a suggestion to broaden or rephrase the query is included

  Scenario: Recall without arguments prompts the user for a query
    Given the Distillery MCP server is running and connected
    When the user invokes "/recall" with no arguments
    Then the skill asks the user what they want to search for

  Scenario: Recall displays tags when entries have them
    Given the Distillery MCP server is running and connected
    And an entry with tags "caching" and "architecture" exists
    When the user invokes "/recall caching"
    Then the matching entry result includes the tags "caching" and "architecture"
