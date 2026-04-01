# Source: docs/specs/05-spec-mcp-refactor/05-spec-mcp-refactor.md
# Pattern: API
# Recommended test type: Unit

Feature: Error Code Standardization and Validation Helpers

  Scenario: Invalid parameters return INVALID_PARAMS error code
    Given the MCP server is running with standardized error codes
    When a client invokes the "distillery_search" tool with a negative limit value
    Then the response contains error code "INVALID_PARAMS"
    And the error message describes the invalid parameter

  Scenario: Resource not found returns NOT_FOUND error code
    Given the MCP server is running with standardized error codes
    And no entry exists with ID "nonexistent-uuid"
    When a client invokes the "distillery_get" tool with ID "nonexistent-uuid"
    Then the response contains error code "NOT_FOUND"
    And the error message identifies the missing resource

  Scenario: Duplicate detection returns CONFLICT error code
    Given the MCP server is running with standardized error codes
    And an entry with identical content already exists in the store
    When a client invokes the "distillery_store" tool with that same content
    Then the response contains error code "CONFLICT"
    And the error message references the existing duplicate entry

  Scenario: Unexpected server error returns INTERNAL error code
    Given the MCP server is running with standardized error codes
    And the store backend is configured to raise an unexpected exception
    When a client invokes any tool that accesses the store
    Then the response contains error code "INTERNAL"
    And the error message does not expose stack traces or file paths

  Scenario: No handler uses legacy INVALID_INPUT or VALIDATION_ERROR codes
    Given the MCP server is running with all 22 tools registered
    When a client sends invalid parameters to each of the 22 tools
    Then every error response uses the code "INVALID_PARAMS"
    And no response contains the code "INVALID_INPUT" or "VALIDATION_ERROR"

  Scenario: validate_limit rejects out-of-range values
    Given the validate_limit helper is configured with min=1 max=1000 default=50
    When validate_limit is called with value 0
    Then an INVALID_PARAMS error is returned with a message about the valid range
    When validate_limit is called with value 1001
    Then an INVALID_PARAMS error is returned with a message about the valid range

  Scenario: validate_limit uses default when no value is provided
    Given the validate_limit helper is configured with min=1 max=1000 default=50
    When validate_limit is called with no value
    Then the returned value is 50

  Scenario: validate_required identifies all missing fields
    Given a request with fields "query" and "project" missing
    When validate_required is called checking for "query", "project", and "limit"
    Then an INVALID_PARAMS error is returned listing both "query" and "project" as missing
    And the field "limit" is not listed as missing

  Scenario: tool_error produces consistent error response format
    Given the tool_error helper
    When tool_error is called with code "NOT_FOUND" and message "Entry xyz not found"
    Then the returned response has is_error set to true
    And the response body contains the error code "NOT_FOUND" and the message "Entry xyz not found"

  Scenario: Search handler uses validate_limit instead of inline validation
    Given the MCP server is running with validation helpers
    When a client invokes "distillery_search" with limit set to 5000
    Then the response contains an INVALID_PARAMS error about the limit range
    And the error format matches the standardized tool_error output
