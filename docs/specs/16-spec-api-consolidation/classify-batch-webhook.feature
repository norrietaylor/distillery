# Source: docs/specs/16-spec-api-consolidation/16-spec-api-consolidation.md
# Pattern: API + CLI/Process
# Recommended test type: Integration

Feature: Add classify-batch Webhook with Heuristic Mode

  Scenario: LLM mode classifies inbox entries using ClassificationEngine
    Given the store contains 5 entries with status "inbox"
    And classification mode is set to "llm"
    When a POST request is sent to /hooks/classify-batch with the bearer token
    Then the response contains classified count, pending_review count, errors count, and by_type breakdown
    And entries with confidence >= threshold have status "active"
    And entries with confidence < threshold have status "pending_review"

  Scenario: Heuristic mode classifies entries using embedding similarity
    Given the store contains 10 active entries of type "session" and 10 active entries of type "bookmark"
    And the store contains 3 entries with status "inbox"
    And classification mode is set to "heuristic"
    When a POST request is sent to /hooks/classify-batch?mode=heuristic with the bearer token
    Then the response contains classified and pending_review counts
    And classification was performed without any LLM API calls

  Scenario: Heuristic mode computes centroids from existing entries by type
    Given the store contains 5 active entries of type "session" with embeddings
    And the store contains 5 active entries of type "bookmark" with embeddings
    And the store contains an inbox entry whose embedding is similar to "session" entries
    When heuristic classification runs on the inbox entry
    Then the entry is classified as type "session"
    And the classification used cosine similarity against type cluster centroids

  Scenario: Heuristic mode requires minimum 3 entries per type for centroid
    Given the store contains 2 active entries of type "session" with embeddings
    And the store contains an inbox entry
    When heuristic classification runs
    Then "session" is not used as a candidate type for classification
    And the inbox entry falls back to status "pending_review"

  Scenario: Heuristic mode falls back to pending_review when no centroid meets threshold
    Given the store contains active entries of various types with embeddings
    And the store contains an inbox entry whose embedding has less than 0.5 similarity to all centroids
    When heuristic classification runs on the inbox entry
    Then the entry status is set to "pending_review"

  Scenario: classify-batch accepts optional entry_type filter
    Given the store contains 3 entries with status "inbox" and 2 entries with status "pending_review"
    When a POST request is sent to /hooks/classify-batch?entry_type=inbox with the bearer token
    Then only the 3 inbox entries are processed
    And the pending_review entries are not reclassified

  Scenario: classify-batch returns structured result format
    Given the store contains inbox entries
    When a POST request is sent to /hooks/classify-batch with the bearer token
    Then the response body contains keys "classified", "pending_review", "errors", and "by_type"
    And "by_type" maps assigned types to their counts

  Scenario: Classification mode is configurable via configure tool
    Given classification mode is set to "llm"
    When the configure tool is called with section="classification" key="mode" value="heuristic"
    Then classification mode is updated to "heuristic"
    And subsequent classify-batch calls use heuristic mode by default

  Scenario: classify-batch webhook requires authentication in hosted mode
    Given the MCP server is running in HTTP mode
    When a POST request is sent to /hooks/classify-batch without a bearer token
    Then the response status is 401
    And no classification is performed

  Scenario: classify-batch handles empty inbox gracefully
    Given the store contains no entries with status "inbox"
    When a POST request is sent to /hooks/classify-batch with the bearer token
    Then the response contains classified=0, pending_review=0, errors=0
    And by_type is an empty object

  Scenario: CLI command triggers classification via webhook
    Given the MCP server is running in HTTP mode
    When the user runs "distillery maintenance classify --mode heuristic"
    Then the command exits with code 0
    And the output displays classification results
