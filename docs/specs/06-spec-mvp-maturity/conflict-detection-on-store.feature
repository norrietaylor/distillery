# Source: docs/specs/06-spec-mvp-maturity/06-spec-mvp-maturity.md
# Pattern: API + Error handling
# Recommended test type: Integration

Feature: Conflict Detection on Store

  Scenario: Store response includes conflict warnings when contradictions are detected
    Given a knowledge base with an entry stating "Python 2 is the recommended version"
    When the user calls distillery_store with content "Python 3 is the recommended version"
    And the LLM determines the new content contradicts the existing entry
    Then the store response includes a "conflicts" key
    And each conflict entry includes entry_id, content_preview, similarity_score, and conflict_reasoning
    And the new entry is still stored successfully

  Scenario: Store response has no conflicts key when no contradictions exist
    Given a knowledge base with an entry about "Python decorators"
    When the user calls distillery_store with content about "Python generators"
    And the LLM determines there is no contradiction
    Then the store response does not include a "conflicts" key with any entries
    And the new entry is stored successfully

  Scenario: Conflict checking is non-fatal and does not block storage
    Given a knowledge base with existing entries
    When the user calls distillery_store with new content
    And the conflict checker encounters an error during analysis
    Then the new entry is still stored successfully
    And the response does not contain conflict data

  Scenario: ConflictChecker uses configurable similarity threshold
    Given a distillery.yaml with classification.conflict_threshold set to 0.80
    And a knowledge base with entries at similarity scores 0.65 and 0.85 to the new content
    When conflict checking runs for the new content
    Then only the entry with similarity 0.85 is evaluated for contradictions
    And the entry at 0.65 is excluded from conflict analysis

  Scenario: Check conflicts tool analyzes content without storing it
    Given a knowledge base with an entry stating "Use tabs for indentation"
    When the user calls the distillery_check_conflicts MCP tool with content "Use spaces for indentation"
    And the LLM determines a contradiction exists
    Then the response includes conflict details with entry_id and conflict_reasoning
    And no new entry is created in the knowledge base

  Scenario: ConflictChecker identifies multiple conflicting entries
    Given a knowledge base with two entries that contradict the new content
    When the user calls distillery_store with the new content
    And the LLM identifies both entries as conflicting
    Then the store response conflicts list contains 2 conflict entries
    And each has a distinct entry_id and conflict_reasoning
