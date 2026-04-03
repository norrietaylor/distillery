# Source: docs/specs/07-spec-tool-consolidation/07-spec-tool-consolidation.md
# Pattern: API + CLI/Process
# Recommended test type: Integration

Feature: Similarity Consolidation -- find_similar absorbs check_dedup and check_conflicts

  Scenario: Basic similarity search without dedup or conflict flags
    Given the MCP server is running with several stored entries
    When a caller invokes distillery_find_similar with content "async Python patterns"
    Then the response contains a list of similar entries ranked by similarity score
    And no dedup or conflict fields are included in the response

  Scenario: Dedup action returns dedup recommendation alongside similar entries
    Given the MCP server is running with an entry about "async Python patterns"
    When a caller invokes distillery_find_similar with content "async Python patterns" and dedup_action true
    Then the response contains a dedup field with an action value of "skip", "merge", "link", or "create"
    And the dedup field contains a similar_entries list

  Scenario: Dedup action recommends skip for near-duplicate content
    Given the MCP server contains an entry with content "How to use asyncio in Python 3.11"
    When a caller invokes distillery_find_similar with content "How to use asyncio in Python 3.11" and dedup_action true
    Then the dedup action is "skip"
    And the similar_entries list includes the matching entry with similarity above 0.95

  Scenario: Dedup action recommends create for novel content
    Given the MCP server has no entries similar to "quantum computing error correction"
    When a caller invokes distillery_find_similar with content "quantum computing error correction" and dedup_action true
    Then the dedup action is "create"
    And the similar_entries list is empty or contains only low-similarity entries

  Scenario: Conflict check returns conflict prompts for LLM resolution
    Given the MCP server contains entries with potentially conflicting information
    When a caller invokes distillery_find_similar with content "Python best practices" and conflict_check true
    Then each similar entry in the response includes a conflict_prompt field
    And the conflict_prompt contains enough context for an LLM to evaluate the conflict

  Scenario: Conflict resolution pass 2 processes LLM responses
    Given a caller has received conflict prompts from a previous find_similar call
    When the caller invokes distillery_find_similar with llm_responses containing resolution decisions
    Then the response includes the resolved conflict outcomes
    And each resolution references the original entries involved

  Scenario: The check_dedup tool is no longer registered
    Given the MCP server is running
    When a caller attempts to invoke distillery_check_dedup
    Then the server returns a tool-not-found error
    And distillery_check_dedup does not appear in the tool listing

  Scenario: The check_conflicts tool is no longer registered
    Given the MCP server is running
    When a caller attempts to invoke distillery_check_conflicts
    Then the server returns a tool-not-found error
    And distillery_check_conflicts does not appear in the tool listing
