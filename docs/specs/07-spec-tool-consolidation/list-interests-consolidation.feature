# Source: docs/specs/07-spec-tool-consolidation/07-spec-tool-consolidation.md
# Pattern: API + CLI/Process
# Recommended test type: Integration

Feature: List and Interests Consolidation plus Eval Updates

  Scenario: List with review output mode returns pending review entries with classification details
    Given the MCP server has entries with status "pending_review" and classification metadata
    When a caller invokes distillery_list with status "pending_review" and output_mode "review"
    Then the response contains only entries with status "pending_review"
    And each entry includes confidence and classification_reasoning fields from its metadata

  Scenario: List with default output mode returns standard entry listing
    Given the MCP server has entries with mixed statuses
    When a caller invokes distillery_list with no output_mode parameter
    Then the response contains entries in the standard list format
    And no confidence or classification_reasoning fields are added to the output

  Scenario: The review_queue tool is no longer registered
    Given the MCP server is running
    When a caller attempts to invoke distillery_review_queue
    Then the server returns a tool-not-found error
    And distillery_review_queue does not appear in the tool listing

  Scenario: Interests with suggest_sources returns feed source suggestions
    Given the MCP server has stored interests and existing feed sources
    When a caller invokes distillery_interests with suggest_sources true
    Then the response contains the standard interests data
    And the response appends a list of feed source suggestions
    And the number of suggestions does not exceed the default of 5

  Scenario: Interests with custom max_suggestions limits suggestion count
    Given the MCP server has stored interests and many potential feed sources
    When a caller invokes distillery_interests with suggest_sources true and max_suggestions 2
    Then the response contains at most 2 feed source suggestions

  Scenario: Interests without suggest_sources returns only interests data
    Given the MCP server has stored interests
    When a caller invokes distillery_interests with no suggest_sources parameter
    Then the response contains the standard interests data
    And no feed source suggestions are included in the response

  Scenario: The suggest_sources tool is no longer registered
    Given the MCP server is running
    When a caller attempts to invoke distillery_suggest_sources
    Then the server returns a tool-not-found error
    And distillery_suggest_sources does not appear in the tool listing

  Scenario: MCP server reports 16 registered tools after consolidation
    Given all tool consolidation changes are applied
    When the MCP server starts
    Then the server reports exactly 16 registered tools
    And none of the 6 removed tool names appear in the tool listing

  Scenario: Eval scenarios reference only consolidated tool names
    Given the eval scenario YAML files in tests/eval/scenarios/
    When the eval suite is executed
    Then all scenarios pass without referencing removed tool names
    And assertions use the consolidated tool names and new parameters
