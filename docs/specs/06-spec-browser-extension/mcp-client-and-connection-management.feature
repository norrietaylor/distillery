# Source: docs/specs/06-spec-browser-extension/06-spec-browser-extension.md
# Pattern: Web/UI + API
# Recommended test type: E2E

Feature: MCP Streamable-HTTP Client and Connection Management

  Scenario: Extension connects to local Distillery instance via auto-detect
    Given the Distillery MCP server is running locally on port 8000
    And the extension has auto-detect enabled in options
    When the extension starts up
    Then the popup displays a green indicator with the text "Connected (local)"

  Scenario: Extension falls back to remote server when local is unavailable
    Given no Distillery MCP server is running locally
    And the extension options have a remote URL configured as "https://distillery-mcp.fly.dev/mcp"
    And the user is authenticated via GitHub OAuth
    When the extension starts up
    Then the popup displays a green indicator with the text "Connected (remote)"

  Scenario: Extension shows disconnected status when no server is reachable
    Given no Distillery MCP server is running locally
    And no remote server is reachable
    When the extension starts up
    Then the popup displays a red indicator with the text "Disconnected"

  Scenario: MCP client completes initialize handshake with server
    Given the Distillery MCP server is running locally on port 8000
    When the extension sends an initialize request to the server
    Then the server responds with a valid MCP capabilities object
    And subsequent tool calls include the Mcp-Session-Id header from the initialize response

  Scenario: MCP client calls a tool and receives a streamed result
    Given the extension is connected to a Distillery MCP server
    When the extension calls the "distillery_status" tool via the MCP client
    Then the response contains the server status information
    And the response is parsed from SSE data lines

  Scenario: Options page saves and applies server configuration
    Given the extension options page is open
    When the user sets the remote URL to "https://my-server.example.com/mcp"
    And sets the local port to "9000"
    And disables auto-detect
    And clicks Save
    Then the options are persisted in extension storage
    And the extension attempts to connect to "https://my-server.example.com/mcp"

  Scenario: Client re-triggers OAuth on 401 response from remote server
    Given the extension is connected to a remote Distillery server
    And the stored OAuth token has expired
    When the extension makes a tool call and receives a 401 response
    Then the extension clears the stored token
    And prompts the user to re-authenticate via GitHub OAuth

  Scenario: Client respects Retry-After header on 429 response
    Given the extension is connected to a Distillery MCP server
    When the extension makes a tool call and receives a 429 response with Retry-After of 5 seconds
    Then the extension waits at least 5 seconds before retrying the request

  Scenario: Local server connection skips OAuth authentication
    Given the Distillery MCP server is running locally on port 8000
    When the extension connects to the local server
    Then the connection succeeds without an Authorization header
    And no OAuth prompt is shown to the user
