Feature: Webhook Handlers (Poll + Rescore + Maintenance)
  As a Distillery operator
  I want webhook endpoints that perform feed polling, rescoring, and KB maintenance
  So that these operations run on schedule without manual MCP invocation

  Background:
    Given the webhook secret environment variable "DISTILLERY_WEBHOOK_SECRET" is set to "wh_test_secret_abc123"
    And the distillery config has webhooks enabled
    And the store is initialized with an embedding provider
    And all requests use header "Authorization: Bearer wh_test_secret_abc123"

  # --- POST /api/poll ---

  Scenario: Poll endpoint returns expected response shape
    Given 2 feed sources are configured in the store
    And the FeedPoller polls 2 sources, fetches 5 items, and stores 3 new items
    When I send a POST request to "/api/poll"
    Then the response status is 200
    And the response body matches:
      """json
      {
        "ok": true,
        "data": {
          "sources_polled": 2,
          "items_fetched": 5,
          "items_stored": 3,
          "errors": []
        }
      }
      """

  Scenario: Poll endpoint reports partial errors in response
    Given 2 feed sources are configured
    And 1 source fails with error "timeout fetching https://example.com/feed.xml"
    When I send a POST request to "/api/poll"
    Then the response status is 200
    And "data.errors" contains "timeout fetching https://example.com/feed.xml"
    And "ok" is true

  Scenario: Poll endpoint updates cooldown after success
    When I send a POST request to "/api/poll"
    And the response status is 200
    Then the metadata key "webhook_cooldown:poll" is updated to the current timestamp

  Scenario: Poll endpoint does not update cooldown on error
    Given the FeedPoller raises an unhandled exception
    When I send a POST request to "/api/poll"
    Then the response status is 500
    And the metadata key "webhook_cooldown:poll" is not updated

  Scenario: Poll endpoint logs operation start and completion
    When I send a POST request to "/api/poll"
    Then an INFO log is emitted containing "poll" and "start"
    And an INFO log is emitted containing "poll" and "complete"

  # --- POST /api/rescore ---

  Scenario: Rescore endpoint uses default limit of 200
    When I send a POST request to "/api/rescore" with no body
    Then the FeedPoller rescore is called with limit=200
    And the response status is 200
    And the response body matches:
      """json
      {
        "ok": true,
        "data": {
          "rescored": 200,
          "upgraded": 12,
          "downgraded": 8
        }
      }
      """

  Scenario: Rescore endpoint accepts custom limit
    When I send a POST request to "/api/rescore" with body:
      """json
      {"limit": 50}
      """
    Then the FeedPoller rescore is called with limit=50
    And the response status is 200
    And "data.rescored" is 50

  Scenario: Rescore endpoint rejects invalid body
    When I send a POST request to "/api/rescore" with body:
      """json
      {"limit": "not_a_number"}
      """
    Then the response status is 400
    And the response body matches:
      """json
      {"ok": false, "error": "<message>"}
      """

  Scenario: Rescore endpoint updates cooldown after success
    When I send a POST request to "/api/rescore"
    And the response status is 200
    Then the metadata key "webhook_cooldown:rescore" is updated to the current timestamp

  Scenario: Rescore endpoint logs operation start and completion
    When I send a POST request to "/api/rescore"
    Then an INFO log is emitted containing "rescore" and "start"
    And an INFO log is emitted containing "rescore" and "complete"

  # --- POST /api/maintenance ---

  Scenario: Maintenance endpoint runs all five operations sequentially
    When I send a POST request to "/api/maintenance"
    Then the response status is 200
    And the following operations were executed in order:
      | operation          |
      | metrics            |
      | quality            |
      | stale_detection    |
      | interests          |
      | source_suggestions |

  Scenario: Maintenance endpoint returns aggregate results
    When I send a POST request to "/api/maintenance"
    Then the response status is 200
    And the response body contains:
      """json
      {
        "ok": true,
        "data": {
          "metrics": {},
          "quality": {},
          "stale_count": 3,
          "top_interests": [],
          "suggested_sources": [],
          "digest_entry_id": "<uuid>"
        }
      }
      """

  Scenario: Maintenance endpoint stores digest entry with correct metadata
    When I send a POST request to "/api/maintenance"
    Then a new entry is created in the store with:
      | field      | value                    |
      | entry_type | session                  |
      | author     | distillery-maintenance   |
    And the entry tags include "system/digest", "system/weekly", and "system/maintenance"
    And the entry metadata contains "period_start" as an ISO 8601 date
    And the entry metadata contains "period_end" as an ISO 8601 date

  Scenario: Maintenance digest entry contains a one-paragraph summary
    When I send a POST request to "/api/maintenance"
    Then the stored digest entry content is a single paragraph (no blank lines)
    And the content summarizes the maintenance results

  Scenario: Maintenance endpoint returns the digest entry ID
    When I send a POST request to "/api/maintenance"
    Then "data.digest_entry_id" is a valid UUID4 string
    And the entry with that ID exists in the store

  Scenario: Maintenance endpoint uses configured parameters
    When I send a POST request to "/api/maintenance"
    Then metrics are computed with a 7-day period
    And stale detection uses 30-day threshold with limit 10
    And interests are computed for 30 days with top 10
    And source suggestions are limited to max 3

  Scenario: Maintenance endpoint updates cooldown after success
    When I send a POST request to "/api/maintenance"
    And the response status is 200
    Then the metadata key "webhook_cooldown:maintenance" is updated to the current timestamp

  Scenario: Maintenance endpoint logs operation start and completion
    When I send a POST request to "/api/maintenance"
    Then an INFO log is emitted containing "maintenance" and "start"
    And an INFO log is emitted containing "maintenance" and "complete"

  # --- Error Handling ---

  Scenario: Internal error returns 500 with standard error shape
    Given an internal error occurs during poll execution
    When I send a POST request to "/api/poll"
    Then the response status is 500
    And the response body matches:
      """json
      {"ok": false, "error": "<descriptive message>"}
      """

  Scenario: Internal error during maintenance does not store digest
    Given an error occurs during the metrics operation
    When I send a POST request to "/api/maintenance"
    Then the response status is 500
    And no digest entry is created in the store
