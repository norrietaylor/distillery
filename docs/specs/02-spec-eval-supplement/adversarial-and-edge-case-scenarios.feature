# Source: docs/specs/02-spec-eval-supplement/02-spec-eval-supplement.md
# Pattern: Error Handling + CLI/Process
# Recommended test type: Integration

Feature: Adversarial and Edge-Case Scenarios

  Scenario: Empty string prompt produces graceful response
    Given the Distillery MCP server is running
    When the user invokes the distill skill with an empty string as content
    Then the response contains a user-friendly message indicating the input is invalid
    And the response does not contain a stack trace or raw exception

  Scenario: Extremely long content is handled without crash
    Given the Distillery MCP server is running
    When the user invokes the distill skill with content exceeding 10000 characters
    Then the system processes the request without crashing
    And the response is a valid user-facing message
    And no "internal error" string appears in the response

  Scenario: Unicode edge cases are handled gracefully
    Given the Distillery MCP server is running
    When the user invokes the distill skill with content containing RTL text, zero-width characters, and emoji sequences
    Then the entry is stored successfully
    And the stored content preserves the original unicode characters

  Scenario: Recall search against empty knowledge base returns helpful message
    Given the knowledge base contains zero entries
    When the user invokes the recall skill with a search query
    Then the response contains a message indicating no matching entries were found
    And the response does not contain a stack trace or "internal error"

  Scenario: Pour synthesis with no matching entries returns graceful response
    Given the knowledge base contains entries unrelated to the query topic
    When the user invokes the pour skill with a query that matches nothing
    Then the response indicates no relevant entries are available for synthesis
    And the response does not contain a raw exception or error traceback

  Scenario: Similarity score at link threshold classifies correctly
    Given two entries with a similarity score of exactly 0.60
    When the deduplication checker evaluates the pair
    Then the classification result is "link"
    And no merge or skip action is taken

  Scenario: Similarity score at merge threshold classifies correctly
    Given two entries with a similarity score of exactly 0.80
    When the deduplication checker evaluates the pair
    Then the classification result is "merge"
    And no skip action is taken

  Scenario: Similarity score at skip threshold classifies correctly
    Given two entries with a similarity score of exactly 0.95
    When the deduplication checker evaluates the pair
    Then the classification result is "skip"

  Scenario: Rapid sequential store and search calls produce consistent results
    Given the Distillery MCP server is running
    When the user stores an entry and immediately searches for it in the same prompt
    Then the search results include the just-stored entry
    And no data loss or corruption is observed

  Scenario: Multiple store operations in a single prompt all succeed
    Given the Distillery MCP server is running
    When the user stores 3 entries in rapid succession within a single prompt
    Then all 3 entries are persisted in the knowledge base
    And a subsequent search returns all 3 entries

  Scenario: MCP tool returning an error produces graceful degradation
    Given the Distillery MCP server is running
    And an MCP tool is configured to return an error response
    When the user invokes a skill that depends on the failing tool
    Then the response contains a user-facing error message explaining the failure
    And the response does not contain a stack trace or "internal error"

  Scenario: Simulated timeout produces user-friendly error
    Given the Distillery MCP server is running
    And an MCP tool is configured to simulate a timeout
    When the user invokes a skill that calls the timed-out tool
    Then the response contains a message indicating the operation timed out
    And the response suggests the user retry or check system status

  Scenario: All adversarial scenarios assert absence of raw errors
    Given the adversarial scenario file tests/eval/scenarios/adversarial.yaml is loaded
    When each scenario in the file is executed
    Then no scenario response contains a Python traceback
    And no scenario response contains the string "internal error"
    And every scenario response contains user-friendly messaging

  Scenario: Adversarial scenarios are tagged with category metadata
    Given the adversarial scenario file tests/eval/scenarios/adversarial.yaml is loaded
    When the scenarios are parsed
    Then each scenario includes a category metadata field
    And the categories include malformed_input, empty_store, boundary, concurrent, and missing_dependency

  Scenario: Nightly CI automatically includes adversarial scenarios
    Given the nightly eval workflow loads all YAML from the scenarios directory
    And adversarial.yaml is present in tests/eval/scenarios/
    When the nightly eval suite runs
    Then adversarial scenarios are included in the run
    And all adversarial scenarios pass
