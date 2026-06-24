# Source: docs/specs/18-spec-edge-by-default-and-link-suggestion/18-spec-edge-by-default-and-link-suggestion.md
# Pattern: State + CLI/Process
# Recommended test type: Integration

Feature: Relation-candidate review surface

  Scenario: A pending candidate is persisted as an entry_relations row with review metadata
    Given two stored entries with no edge between them
    When a candidate edge is persisted with metadata.review_status "pending" and a suggestion_score
    Then an entry_relations row exists for that pair carrying review_status "pending"
    And no new database table was created to hold the candidate

  Scenario: The list action returns pending candidates ordered by score descending
    Given two pending candidates exist with suggestion_scores 0.72 and 0.65
    When the distillery_relations list-candidates action is invoked
    Then both candidates are returned with their endpoint ids, relation type, and score
    And the candidate scoring 0.72 is listed before the one scoring 0.65

  Scenario: Pending candidates are excluded from default get_related results
    Given a pending candidate edge between entry A and entry B
    When get_related is called for entry A with default options
    Then entry B is not present in the related results
    But the pending candidate is returned by the candidate-listing action

  Scenario: Accepting a candidate promotes it to a live edge
    Given a pending candidate edge between entry A and entry B
    When the distillery_relations resolve action accepts that candidate
    Then the row's review_status flag is cleared
    And entry B now appears in the default get_related results for entry A

  Scenario: Rejecting a candidate removes the row
    Given a pending candidate edge between entry A and entry C
    When the distillery_relations resolve action rejects that candidate
    Then no entry_relations row exists for the A-to-C pair
    And entry C does not appear in get_related results for entry A

  Scenario: Resolving an already-resolved candidate is a no-op success
    Given a candidate that was already accepted
    When the resolve action is invoked again on the same candidate
    Then the action returns a success result
    And the live edge and its state are unchanged
