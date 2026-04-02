Feature: Webhook Infrastructure (Config + App Composition + Auth + Cooldowns)
  As a Distillery operator
  I want webhook endpoints protected by bearer token authentication and per-endpoint cooldowns
  So that scheduled operations are secure and cannot be triggered excessively

  Background:
    Given the webhook secret environment variable "DISTILLERY_WEBHOOK_SECRET" is set to "wh_test_secret_abc123"
    And the distillery config has webhooks enabled

  # --- Configuration ---

  Scenario: WebhookConfig defaults are applied when YAML section is absent
    Given a YAML config with no "webhooks" section under "server"
    When the config is parsed
    Then "server.webhooks.enabled" is true
    And "server.webhooks.secret_env" is "DISTILLERY_WEBHOOK_SECRET"

  Scenario: WebhookConfig values are parsed from YAML
    Given a YAML config with the following "webhooks" section:
      """yaml
      webhooks:
        enabled: false
        secret_env: MY_CUSTOM_SECRET
      """
    When the config is parsed
    Then "server.webhooks.enabled" is false
    And "server.webhooks.secret_env" is "MY_CUSTOM_SECRET"

  # --- Bearer Token Authentication ---

  Scenario: Request without Authorization header returns 401
    When I send a POST request to "/api/poll" with no Authorization header
    Then the response status is 401
    And the response body is:
      """json
      {"ok": false, "error": "unauthorized"}
      """

  Scenario: Request with incorrect bearer token returns 401
    When I send a POST request to "/api/poll" with header "Authorization: Bearer wrong_token_xyz"
    Then the response status is 401
    And the response body is:
      """json
      {"ok": false, "error": "unauthorized"}
      """

  Scenario: Request with valid bearer token is accepted
    When I send a POST request to "/api/poll" with header "Authorization: Bearer wh_test_secret_abc123"
    Then the response status is not 401

  Scenario: Token comparison uses constant-time algorithm
    Given the webhook auth middleware uses hmac.compare_digest
    When I send a POST request to "/api/poll" with header "Authorization: Bearer wrong_token_xyz"
    Then the token is compared using hmac.compare_digest, not equality operator

  # --- Per-Endpoint Cooldown Tracking ---

  Scenario: Request within cooldown window returns 429
    Given the "/api/poll" endpoint was last called successfully 60 seconds ago
    And the cooldown for "poll" is 300 seconds
    When I send an authenticated POST request to "/api/poll"
    Then the response status is 429
    And the response contains a "Retry-After" header with value "240"
    And the response body is:
      """json
      {"ok": false, "error": "too_early", "retry_after": 240}
      """

  Scenario: Request after cooldown window expires is accepted
    Given the "/api/poll" endpoint was last called successfully 301 seconds ago
    And the cooldown for "poll" is 300 seconds
    When I send an authenticated POST request to "/api/poll"
    Then the response status is not 429

  Scenario Outline: Default cooldown intervals per endpoint
    Given no custom cooldown configuration
    Then the default cooldown for "<endpoint>" is <seconds> seconds

    Examples:
      | endpoint    | seconds |
      | poll        | 300     |
      | rescore     | 3600    |
      | maintenance | 21600   |

  Scenario: Cooldown timestamps are persisted to DuckDB
    Given the "/api/poll" endpoint was called successfully
    And the cooldown timestamp is stored as "webhook_cooldown:poll" in metadata
    When the store is reinitialized
    And I send an authenticated POST request to "/api/poll" within the cooldown window
    Then the response status is 429
    And the cooldown is still enforced from the persisted timestamp

  Scenario: Cooldown timestamps use ISO 8601 format
    When the "/api/poll" endpoint completes successfully
    Then the metadata key "webhook_cooldown:poll" contains a value matching ISO 8601 format

  # --- App Composition ---

  Scenario: Webhook app is mounted alongside MCP app when enabled
    Given transport is "http"
    And webhooks are enabled
    And "DISTILLERY_WEBHOOK_SECRET" is set
    When the server starts
    Then the parent Starlette app has a mount at "/api" for the webhook app
    And the parent Starlette app has a mount at "/" for the MCP app
    And "/api" mount is registered before "/" mount

  Scenario: Webhook app is not mounted when webhooks are disabled
    Given transport is "http"
    And webhooks are disabled in config
    When the server starts
    Then there is no "/api" mount
    And the MCP app is passed directly to uvicorn

  Scenario: Webhook app is not mounted when secret env var is unset
    Given transport is "http"
    And webhooks are enabled
    And "DISTILLERY_WEBHOOK_SECRET" is not set
    When the server starts
    Then there is no "/api" mount
    And the MCP app is passed directly to uvicorn

  Scenario: Existing MCP and OAuth routes are unaffected by webhook composition
    Given the server is running with webhooks enabled
    When I send a request to "/mcp"
    Then the MCP endpoint responds normally
    When I send a request to "/api/poll" with valid auth
    Then the webhook endpoint responds normally

  # --- Rate Limiting ---

  Scenario: Webhook app applies tighter rate limits than MCP
    Given the webhook app has RateLimitMiddleware configured
    Then the rate limit is 10 requests per minute
    And the rate limit is 100 requests per hour

  # --- Store Initialization ---

  Scenario: Webhook request before any MCP client connects initializes store
    Given no MCP client has connected yet
    And the shared state dict has no store initialized
    When I send an authenticated POST request to "/api/poll"
    Then _ensure_store initializes the store using the same logic as MCP lifespan
    And the request completes successfully
