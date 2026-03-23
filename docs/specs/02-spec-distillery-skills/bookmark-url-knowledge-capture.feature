# Source: docs/specs/02-spec-distillery-skills/02-spec-distillery-skills.md
# Pattern: CLI/Process + Error Handling
# Recommended test type: Integration

Feature: /bookmark — URL Knowledge Capture

  Scenario: Bookmark fetches URL content and stores a summary
    Given the Distillery MCP server is running and connected
    And the URL "https://example.com/article" is accessible
    When the user invokes "/bookmark https://example.com/article"
    Then the skill fetches the URL content using WebFetch
    And a concise 2-4 sentence summary of the content is generated
    And the skill calls distillery_store with entry_type "bookmark" and metadata containing the URL
    And the user sees a confirmation with entry ID, URL, summary preview, and tags

  Scenario: Bookmark parses hashtag-style tags from arguments
    Given the Distillery MCP server is running and connected
    And the URL "https://example.com/caching-guide" is accessible
    When the user invokes "/bookmark https://example.com/caching-guide #caching #architecture"
    Then the stored entry includes tags "caching" and "architecture"
    And the confirmation message displays the applied tags

  Scenario: Bookmark handles inaccessible URL by requesting manual summary
    Given the Distillery MCP server is running and connected
    And the URL "https://internal.corp/private-doc" is not accessible via WebFetch
    When the user invokes "/bookmark https://internal.corp/private-doc"
    Then the skill informs the user that the URL could not be fetched
    And the skill asks the user to provide a manual summary

  Scenario: Bookmark detects duplicate URL and warns the user
    Given the Distillery MCP server is running and connected
    And a bookmark for "https://example.com/article" already exists in the knowledge base
    When the user invokes "/bookmark https://example.com/article"
    Then the skill calls distillery_find_similar and detects the existing bookmark
    And the duplicate entry is displayed to the user
    And the user is asked whether to store anyway or skip

  Scenario: Bookmark without URL argument prompts the user
    Given the Distillery MCP server is running and connected
    When the user invokes "/bookmark" with no arguments
    Then the skill asks the user for a URL to bookmark

  Scenario: Bookmark stores only summary content, not raw HTML
    Given the Distillery MCP server is running and connected
    And the URL "https://example.com/article" returns an HTML page
    When the user invokes "/bookmark https://example.com/article"
    Then the stored entry content contains a summary and key points
    And the stored entry content does not contain raw HTML tags
