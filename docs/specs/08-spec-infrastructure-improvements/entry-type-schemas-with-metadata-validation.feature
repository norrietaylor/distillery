# Source: docs/specs/08-spec-infrastructure-improvements/08-spec-infrastructure-improvements.md
# Pattern: State + API + Error Handling
# Recommended test type: Integration

Feature: Entry Type Schemas with Metadata Validation

  Scenario: Person entry with valid metadata is stored successfully
    Given an in-memory DuckDB store is initialized
    When a user stores an entry with entry_type "person" and metadata {"expertise": ["python", "duckdb"], "github_username": "dev1"}
    Then the entry is stored successfully and returns a valid UUID
    And the stored entry's metadata contains "expertise" with value ["python", "duckdb"]

  Scenario: Person entry missing required expertise field is rejected
    Given an in-memory DuckDB store is initialized
    When a user attempts to store an entry with entry_type "person" and metadata {"github_username": "dev1"}
    Then a ValueError is raised
    And the error message indicates "expertise" is a required field

  Scenario: Github entry with valid metadata is stored successfully
    Given an in-memory DuckDB store is initialized
    When a user stores an entry with entry_type "github" and metadata {"repo": "org/repo", "ref_type": "pr", "ref_number": 42}
    Then the entry is stored successfully and returns a valid UUID
    And the stored entry's metadata contains "repo" with value "org/repo"

  Scenario: Github entry with invalid ref_type is rejected
    Given an in-memory DuckDB store is initialized
    When a user attempts to store an entry with entry_type "github" and metadata {"repo": "org/repo", "ref_type": "commit", "ref_number": 1}
    Then a ValueError is raised
    And the error message indicates "ref_type" must be one of "issue", "pr", "discussion", "release"

  Scenario: Project entry missing required repo field is rejected
    Given an in-memory DuckDB store is initialized
    When a user attempts to store an entry with entry_type "project" and metadata {"status": "active"}
    Then a ValueError is raised
    And the error message indicates "repo" is a required field

  Scenario: Digest entry with valid date range is stored successfully
    Given an in-memory DuckDB store is initialized
    When a user stores an entry with entry_type "digest" and metadata {"period_start": "2026-03-01", "period_end": "2026-03-07"}
    Then the entry is stored successfully and returns a valid UUID

  Scenario: Existing entry types accept any metadata without validation
    Given an in-memory DuckDB store is initialized
    When a user stores an entry with entry_type "session" and metadata {"arbitrary_key": "any_value"}
    Then the entry is stored successfully and returns a valid UUID
    And no validation error is raised

  Scenario: Existing entry types with empty metadata are accepted
    Given an in-memory DuckDB store is initialized
    When a user stores an entry with entry_type "bookmark" and metadata {}
    Then the entry is stored successfully and returns a valid UUID

  Scenario: Update re-validates metadata for typed entries
    Given an in-memory DuckDB store with a stored "person" entry containing metadata {"expertise": ["python"]}
    When a user updates that entry's metadata to {"github_username": "dev1"}
    Then a ValueError is raised
    And the error message indicates "expertise" is a required field
    And the original entry metadata is unchanged

  Scenario: MCP store tool returns validation errors for invalid metadata
    Given the MCP server is running
    When a user calls distillery_store with entry_type "person" and metadata {"team": "backend"}
    Then the MCP response contains a validation error
    And the error indicates "expertise" is required

  Scenario: MCP store tool succeeds for valid typed metadata
    Given the MCP server is running
    When a user calls distillery_store with entry_type "github" and metadata {"repo": "org/repo", "ref_type": "issue", "ref_number": 7}
    Then the MCP response contains a valid entry ID
    And no error is present in the response

  Scenario: Type schemas MCP tool returns all schema definitions
    Given the MCP server is running
    When a user calls distillery_type_schemas
    Then the response contains schemas for "person", "project", "digest", and "github"
    And the "person" schema lists "expertise" as required with type "list[str]"
    And the "github" schema lists "repo", "ref_type", and "ref_number" as required
    And the "session" type has no required metadata fields listed
