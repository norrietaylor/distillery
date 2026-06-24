# Source: docs/specs/18-spec-edge-by-default-and-link-suggestion/18-spec-edge-by-default-and-link-suggestion.md
# Pattern: API + State
# Recommended test type: Integration

Feature: Wire link-suggestion into /api/maintenance

  Scenario: Maintenance run includes a link_suggestion block in its response
    Given a seeded store and link_suggestion.enabled is True
    When an authenticated POST request is sent to /api/maintenance
    Then the response status is 200
    And the response JSON contains a "link_suggestion" block
    And that block carries the suggest_links count keys edges_created, candidates_queued, discarded, and nodes_scanned

  Scenario: The link-suggestion phase runs after the existing phases
    Given a seeded store and link_suggestion.enabled is True
    When an authenticated POST request is sent to /api/maintenance
    Then the poll, rescore, and classify-batch phases complete before the link-suggestion phase
    And the link-suggestion phase output appears alongside the other phase results

  Scenario: A disabled link-suggestion phase reports enabled false while other phases run
    Given link_suggestion.enabled is False
    When an authenticated POST request is sent to /api/maintenance
    Then the response "link_suggestion" block reports "enabled" is False with no sweep performed
    And the poll, rescore, and classify-batch phases still complete

  Scenario: A failure in the link-suggestion phase does not abort completed phases
    Given the earlier maintenance phases have completed successfully
    And the link-suggestion phase raises an error during execution
    When the maintenance run reaches the link-suggestion phase
    Then the failure is logged and reported in the response
    And the already-completed phase results remain present in the response

  Scenario: The phase requires no new credentials beyond existing bearer auth
    Given the existing maintenance bearer token
    When an authenticated POST request is sent to /api/maintenance with link_suggestion enabled
    Then the link-suggestion phase completes without requesting any new credential
    And no external network call is made by the phase
