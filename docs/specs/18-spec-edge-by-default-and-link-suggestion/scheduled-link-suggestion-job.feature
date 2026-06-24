# Source: docs/specs/18-spec-edge-by-default-and-link-suggestion/18-spec-edge-by-default-and-link-suggestion.md
# Pattern: State + CLI/Process
# Recommended test type: Integration

Feature: Scheduled link-suggestion job

  Scenario: High-confidence pairs are auto-created and mid-confidence pairs are queued
    Given a graph seeded with one candidate pair scoring above auto_create_threshold 0.85
    And one candidate pair scoring within the review band [0.60, 0.85)
    When the distillery_relations suggest_links action runs with default config
    Then one new live "related" edge exists for the above-threshold pair
    And one pending candidate exists for the review-band pair
    And the response counts report edges_created 1 and candidates_queued 1

  Scenario: Sub-floor candidates are discarded and counted
    Given a candidate pair scoring below review_floor 0.60
    When the suggest_links action runs
    Then no edge and no pending candidate are created for that pair
    And the response discarded count includes that pair

  Scenario: suggest_links performs no LLM inference
    Given a seeded graph with stored embeddings and existing adjacency
    When the suggest_links action runs
    Then candidates are scored using link_prediction and find_similar over stored data only
    And no embedding or LLM inference request is issued

  Scenario: The action reports sweep counts and respects the candidate bound
    Given more candidate pairs available than max_candidates_per_run
    When the suggest_links action runs
    Then the response includes edges_created, candidates_queued, discarded, and nodes_scanned counts
    And the sweep stops at max_candidates_per_run
    And a log entry records that the bound truncated the sweep

  Scenario: A pair with an existing live edge or pending row is not re-queued
    Given a candidate pair that already has a pending candidate row
    When the suggest_links action runs
    Then no second pending row is created for that pair

  Scenario: A second consecutive run converges to zero changes
    Given suggest_links has already run once on a seeded graph
    When suggest_links is run a second time immediately after
    Then the response reports edges_created 0
    And the response reports candidates_queued 0
