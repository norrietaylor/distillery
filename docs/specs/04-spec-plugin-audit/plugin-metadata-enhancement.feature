# Source: docs/specs/04-spec-plugin-audit/04-spec-plugin-audit.md
# Pattern: State (configuration enables secure secret storage at runtime)
# Recommended test type: Integration

Feature: Plugin Metadata Enhancement

  Scenario: Sensitive API key is stored in OS keychain via userConfig
    Given the plugin.json declares jina_api_key with sensitive set to true
    When a user installs the plugin and is prompted to configure jina_api_key
    Then the value is stored in the OS keychain (macOS Keychain, Windows Credential Manager, or Linux Secret Service)
    And the API key is not written to any plaintext config file on disk

  Scenario: GitHub client secret is stored securely via userConfig
    Given the plugin.json declares github_client_secret with sensitive set to true
    When a user configures the GitHub OAuth client secret during plugin setup
    Then the secret is stored in the OS keychain
    And the secret is not visible in plugin.json or any user-readable config file

  Scenario: Non-sensitive config field is stored in standard config
    Given the plugin.json declares github_client_id without sensitive set to true
    When a user configures the GitHub OAuth client ID
    Then the value is stored in the standard plugin configuration
    And the value is readable by the plugin at runtime

  Scenario: Each userConfig field includes a descriptive help message
    Given the plugin.json contains userConfig entries for jina_api_key, github_client_id, and github_client_secret
    When a user is prompted to configure these fields during plugin installation
    Then each prompt displays a description explaining the field's purpose
    And each description indicates where to obtain the value

  Scenario: CONVENTIONS.md directs developers to use userConfig for API keys
    Given a developer reads CONVENTIONS.md for API key management guidance
    When they look up the recommended approach for configuring secrets
    Then the documentation recommends userConfig as the primary method
    And environment variables are listed as a fallback alternative

  Scenario: Plugin runtime retrieves sensitive keys from keychain at startup
    Given the plugin has been installed with jina_api_key stored via userConfig
    When the MCP server starts and initializes the Jina embedding provider
    Then the API key is retrieved from the OS keychain
    And the embedding provider authenticates successfully with the retrieved key
