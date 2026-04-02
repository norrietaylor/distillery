# Source: docs/specs/06-spec-browser-extension/06-spec-browser-extension.md
# Pattern: Web/UI
# Recommended test type: E2E

Feature: GitHub OAuth Flow and Auth Management

  Scenario: User initiates GitHub OAuth sign-in for remote server
    Given the extension is configured with a remote Distillery server URL
    And the user is not authenticated
    When the user clicks "Sign in with GitHub" in the popup
    Then a GitHub authorization page opens requesting the "user" scope

  Scenario: Successful OAuth displays GitHub username in popup
    Given the user has completed the GitHub OAuth flow
    And the authorization code has been exchanged for an access token
    When the popup is opened
    Then the popup header displays the authenticated GitHub username
    And the connection indicator shows "Connected (remote)"

  Scenario: OAuth token is stored securely in extension storage
    Given the user has completed the GitHub OAuth flow
    When the access token is received
    Then the token is stored in chrome.storage.local
    And the token is used in Authorization headers for subsequent MCP requests

  Scenario: Sign-out clears token and disconnects from remote server
    Given the user is authenticated via GitHub OAuth
    And connected to a remote Distillery server
    When the user clicks "Sign out" in the popup
    Then the stored OAuth token is cleared
    And the popup shows the "Sign in with GitHub" prompt
    And the connection indicator shows "Disconnected"

  Scenario: Expired token triggers re-authentication prompt
    Given the user was previously authenticated
    And the stored OAuth token has expired
    When the extension makes a request to the remote server and receives a 401 response
    Then the stored token is cleared
    And the user is prompted to sign in again

  Scenario: Local connection works without OAuth prompt
    Given the extension is connected to a local Distillery instance
    When the popup is opened
    Then no "Sign in with GitHub" button is displayed
    And the popup shows the locally configured author name
    And the connection indicator shows "Connected (local)"

  Scenario: OAuth client ID is configurable in extension options
    Given the extension options page is open
    When the user enters a custom GitHub OAuth client ID
    And saves the options
    Then the next OAuth flow uses the custom client ID in the authorization URL
